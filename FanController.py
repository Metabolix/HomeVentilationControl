from machine import Pin, ADC, PWM
from time import ticks_us, ticks_diff
from Timestamp import Timestamp

class TachyInput:
    def __init__(self, pin, timeout):
        self.timeout = timeout * 1000
        self.valid_diff = [-1, -1]
        self.valid_time = [0, 0]
        self.valid_i = 0

        self.prev_time = ticks_us()
        self.good_diff = 0
        self.bad_diff = 0
        self.bad_count = 0
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self.pin.irq(lambda p: self._irq(), trigger = Pin.IRQ_FALLING)

    def _irq(self):
        now = ticks_us()
        diff = ticks_diff(now, self.prev_time)
        self.prev_time = now
        # Reject outliers in data, accept between 80 % and 133 %.
        if diff * 3 < self.good_diff * 4 < diff * 5:
            self.good_diff = diff
            self.valid_diff[self.valid_i ^ 1] = diff
            self.valid_time[self.valid_i ^ 1] = now
            self.valid_i = self.valid_i ^ 1
            self.bad_count = 0
        elif diff * 2 < self.bad_diff * 3 < diff * 4:
            self.bad_count += 1
            # When the same value repeats, accept it eventually.
            if self.bad_count > 8:
                self.good_diff = diff
        else:
            self.bad_count = 1
            self.bad_diff = diff

    def diff_us(self):
        i = self.valid_i
        diff = self.valid_diff[i]
        if diff >= self.timeout or ticks_diff(ticks_us(), self.valid_time[i]) >= self.timeout:
            self.valid_diff[i] = diff = -1
        return diff

class FanController:
    def __init__(
        self, *,
        pin_switch_on = None, pin_switch_own = None,
        pin_voltage_adc = None, ctrl_translate = None,
        pin_tachy = None,
        pin_pwm_out = None,
    ):
        self.pin_switch_on = pin_switch_on is not None and Pin(pin_switch_on, Pin.IN, pull = Pin.PULL_UP)
        self.pin_switch_own = pin_switch_own is not None and Pin(pin_switch_own, Pin.IN, pull = Pin.PULL_UP)

        self.voltage_adc = pin_voltage_adc is not None and ADC(pin_voltage_adc)
        self.ctrl_translate = ctrl_translate or self.VilpeECoFlow125P700
        self.ctrl_level = (0, "?")
        self.ctrl_timestamp = Timestamp(None)
        self.ctrl_rpm = 0

        tachy_off_time = 2_000 # Over 2 seconds = less than 30 rpm will be considered "off".
        self.tachy_input = pin_tachy is not None and TachyInput(pin_tachy, tachy_off_time)
        self._rpm_change_timestamp = Timestamp()
        self._rpm_stable_threshold = 20
        self.rpm = self._old_rpm = 0
        self.rpm_stable = False

        self.pwm_output = pin_pwm_out is not None and PWM(Pin(pin_pwm_out, Pin.OUT, value = 0))
        if self.pwm_output:
            self.pwm_output.freq(10_000)
            self.pwm_output.duty_u16(0)
        self._output_target_rpm = 0
        self._output_pwm_value = 0
        self._output_stored = False
        self._output_timestamp = None
        self._output_stable_threshold = 100
        self._output_limits = (270, 3200, 3200, 65535)
        self._output_memory = [(270, 3200), (666, 5630), (1875, 14250), (1885, 14700), (2428, 19300), (2545, 19650), (3000, 24600)]
        self.target_rpm = None
        self.output_stable = False

    def set_rpm(self, rpm):
        self.target_rpm = rpm

    def update(self):
        self.switch_on = 1 - self.pin_switch_on() if self.pin_switch_on else 0
        self.switch_own = 1 - self.pin_switch_own() if self.pin_switch_own else 0
        self._update_ctrl()
        self._update_tachy()
        self._update_output()

    def _update_tachy(self):
        dt = self.tachy_input and self.tachy_input.diff_us() or -1
        self.rpm = 60_000_000 // dt if dt > 0 else 0
        if abs(self.rpm - self._old_rpm) > self._rpm_stable_threshold:
            self._rpm_change_timestamp = Timestamp()
        self._old_rpm = ((7 * self._old_rpm) + self.rpm) // 8
        self.rpm_stable = not self._rpm_change_timestamp.between(0, 5_000)

    def _update_ctrl(self):
        mv = 0
        if self.voltage_adc:
            # Take 16 samples to avoid ADC fluctuation. 12-bit ADC, max 0xfff0.
            adc_u16 = 0
            for i in range(16):
                adc_u16 += self.voltage_adc.read_u16()
            adc_u16 = adc_u16 >> 4

            # Voltage divider: GND, 324k, ADC, 324k, 536k, real_volts.
            # 12-bit ADC max = 3.3 V / 0xfff0.
            # Theoretical value:
            #mv = adc_u16 * (324 * 2 + 536) / 324 * 3300 / 0xfff0
            # Reality: Adjusted with multimeter measurements.
            #mv = (adc_u16 - 145) * 0.181941
            mv = max(0, (adc_u16 - 145) * 9831 // 54034)

        self.ctrl_millivolts = mv
        self.ctrl_rpm = self.VilpeECoFlow125P700(mv, self.ctrl_rpm)[0]

        # Update timestamp when the manual control level changes.
        l = self.ctrl_translate(self.ctrl_millivolts)
        if l != self.ctrl_level:
            self.ctrl_level = l
            self.ctrl_timestamp = Timestamp()
        else:
            self.ctrl_timestamp.update()

    @classmethod
    def LapetekVirgola5600XH(self, mv):
        # Lapetek Virgola 5600XH kitchen hood has 8 levels (above zero).
        # Internal DIP switches are used to select 4 of the modes for use.
        # Voltages (actually 12 V PWM) are between 1_100 mV and 12_000 mV.
        return (max(0, min(8, (mv + 500) // 1400)), "DIP")

    @classmethod
    def VilpeECoIdeal(self, mv):
        # Vilpe ECo Ideal is configured from 0 to 100 % in steps of 10 %.
        # 10 % = 1890 mV and 100 % = 9960 mV.
        return (max(0, min(100, round(10 * (mv - 940) // 897, -1))), "%")

    @classmethod
    def VilpeECoFlow125P700(self, mv, old_rpm = 0):
        # Vilpe ECo Flow rpm rises linearly with voltage between lowes and highest.
        # 0 rpm = 0 mV and 3030 rpm = 7750 mV, tends to stop below 270-330 rpm.
        rpm = 3030 * mv // 7750
        if abs(rpm - old_rpm) < 10:
            return (old_rpm, "rpm")
        return (rpm > 270 and max(300, min(3030, rpm)) or 0, "rpm")

    def _update_output(self):
        if not self.pwm_output or not self.switch_on or not self.switch_own:
            self._output_timestamp = None
            return

        target_rpm = self.ctrl_rpm if self.target_rpm is None else self.target_rpm
        target_changed = abs(self._output_target_rpm - target_rpm) > self._rpm_stable_threshold
        self._output_target_rpm = target_rpm = target_rpm if target_changed else self._output_target_rpm
        output_wrong = abs(target_rpm - self.rpm) > self._rpm_stable_threshold

        self.output_stable = self._output_timestamp and not self._output_timestamp.between(0, 5_000 if self.rpm else 10_000)

        if self.rpm_stable and self.output_stable and self.rpm and not self._output_stored:
            self._output_stored = True
            # Update memory with current RPM/PWM data.
            # Remove old values which are too close or non-monotonic.
            rpm, pwm = self.rpm, self._output_pwm_value
            for i in reversed(range(len(self._output_memory))):
                p = self._output_memory[i]
                if (rpm < p[0]) != (pwm < p[1]) or abs(rpm - p[0]) < 64 or abs(pwm - p[1]) < 500:
                    self._output_memory.pop(i)
            if len(self._output_memory) < 20:
                self._output_memory.append((rpm, pwm))

        if target_changed or output_wrong:
            # Optimize PWM with linear interpolation (and extrapolation).
            pwm = self._get_pwm_estimate(target_rpm)
            if abs(self._output_pwm_value - pwm) > self._output_stable_threshold:
                self.pwm_output.duty_u16(pwm)
                self._output_pwm_value = pwm
                self._output_timestamp = Timestamp()
                self._output_stored = False
                self.output_stable = False

    def _get_pwm_estimate(self, rpm):
        x0, y0, x1, y1 = self._output_limits
        if not rpm:
            return 0
        if rpm < x0:
            return y0
        if rpm > x1:
            return y1
        for x, y in self._output_memory:
            if x0 < x <= rpm:
                x0, y0 = x, y
            if x1 > x >= rpm:
                x1, y1 = x, y
        return max(0, min(65535, y0 + (y1 - y0) * (rpm - x0) // (x1 - x0))) if x1 != x0 else y0
