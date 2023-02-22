from machine import Pin, PWM
from rp2 import PIO, StateMachine, asm_pio
from Timestamp import Timestamp

class TachyInputPIO:
    """PIO for counting tachy input.
    TX FIFO: None.
    RX FIFO: microseconds between falling edges.
    PIO instructions: 6
    """

    def __init__(self, sm, pin, timeout):
        self._timeout = timeout
        self._diff = -1
        self._timestamp = Timestamp(None)
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        pio_freq = 2_000_000 # 2 cycles per usec.
        self.sm = StateMachine(sm, self.pio_program, freq = pio_freq, jmp_pin = self.pin)
        self.sm.restart()
        self.sm.active(1)

    @asm_pio(fifo_join = PIO.JOIN_RX, autopush = True, push_thresh = 30)
    def pio_program():
        # Count until 0
        label("loop_1")
        jmp(x_dec, "x_nop1")
        label("x_nop1")
        jmp(pin, "loop_1")
        in_(x, 30)
        set(x, 0)
        # Count until 1
        wrap_target()
        label("loop_0")
        jmp(x_dec, "x_nop0")
        label("x_nop0")
        jmp(pin, "loop_1")

    def diff_us(self):
        # If the FIFO is full and the PIO stalls, the second value will be bad,
        # because it includes the stalling time. (The first value is just late.)
        # => Always read two values and use only the first one.
        # If the RPM drops to zero, the counter will overflow.
        # => Don't use the first value after timeout (RPM zero).
        last_valid = self._timestamp.between(0, self._timeout)
        while self.sm.rx_fifo() > 1:
            diff = 0x3fffffff - self.sm.get()
            self.sm.get()
            self._timestamp = Timestamp()
            if last_valid:
                self._diff = diff
        if not last_valid or self._diff > self._timeout * 1000:
            self._diff = -1
        return self._diff

class FanController:
    def __init__(
        self, *,
        pin_switch_on = None, pin_switch_own = None,
        sm_tachy = None, pin_tachy = None,
        pin_pwm_out = None,
    ):
        self.millivolts_to_rpm = lambda mv: self.VilpeECoFlow125P700(mv)[0]
        self.pin_switch_on = pin_switch_on is not None and Pin(pin_switch_on, Pin.IN, pull = Pin.PULL_UP)
        self.pin_switch_own = pin_switch_own is not None and Pin(pin_switch_own, Pin.IN, pull = Pin.PULL_UP)

        tachy_off_time = 2_000 # Over 2 seconds = less than 30 rpm will be considered "off".
        self.tachy_input = sm_tachy is not None and pin_tachy is not None and TachyInputPIO(sm_tachy, pin_tachy, tachy_off_time)
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
        self._update_tachy()
        self._update_output()

    def _update_tachy(self):
        dt = self.tachy_input and self.tachy_input.diff_us() or -1
        self.rpm = 60_000_000 // dt if dt > 0 else 0
        if abs(self.rpm - self._old_rpm) > self._rpm_stable_threshold:
            self._rpm_change_timestamp = Timestamp()
        self._old_rpm = ((7 * self._old_rpm) + self.rpm) // 8
        self.rpm_stable = not self._rpm_change_timestamp.between(0, 5_000)

    @classmethod
    def VilpeECoFlow125P700(self, mv, old_rpm = 0):
        # Vilpe ECo Flow rpm rises linearly with voltage between lowes and highest.
        # 0 rpm = 0 mV and 3030 rpm = 7750 mV, tends to stop below 270-330 rpm.
        rpm = 3030 * mv // 7750
        if abs(rpm - old_rpm) < 10:
            return (old_rpm, "rpm")
        return (rpm > 270 and max(300, min(3030, rpm)) or 0, "rpm")

    def _update_output(self):
        if not self.pwm_output or not self.switch_on or not self.switch_own or self.target_rpm is None:
            self._output_timestamp = None
            return

        target_rpm = self.target_rpm
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
