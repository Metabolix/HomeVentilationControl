from machine import Pin, PWM
from Timestamp import Timestamp

class FanController:
    def __init__(
        self, *,
        pin_switch_on = None, pin_switch_own = None,
        pin_pwm_out = None,
    ):
        self.pin_switch_on = pin_switch_on is not None and Pin(pin_switch_on, Pin.IN, pull = Pin.PULL_UP)
        self.pin_switch_own = pin_switch_own is not None and Pin(pin_switch_own, Pin.IN, pull = Pin.PULL_UP)

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

    def update(self, target_rpm, measured_rpm, measured_stable, rpm_stable_threshold, stable_delay):
        self.switch_on = 1 - self.pin_switch_on() if self.pin_switch_on else 0
        self.switch_own = 1 - self.pin_switch_own() if self.pin_switch_own else 0
        self.target_rpm = target_rpm

        if not self.pwm_output or not self.switch_on or not self.switch_own or target_rpm is None:
            self._output_timestamp = None
            return

        target_changed = abs(self._output_target_rpm - target_rpm) > rpm_stable_threshold
        self._output_target_rpm = target_rpm = target_rpm if target_changed else self._output_target_rpm
        output_wrong = abs(target_rpm - measured_rpm) > rpm_stable_threshold

        self.output_stable = self._output_timestamp and not self._output_timestamp.between(0, stable_delay)

        if measured_stable and self.output_stable and measured_rpm and not self._output_stored:
            self._output_stored = True
            # Update memory with current RPM/PWM data.
            # Remove old values which are too close or non-monotonic.
            rpm, pwm = measured_rpm, self._output_pwm_value
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
