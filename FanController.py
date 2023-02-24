from machine import Pin, PWM
from Timestamp import Timestamp
from LinearInterpolator import LinearInterpolator

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
        self._output_memory = LinearInterpolator(
            [(0, 0), (270, 3200), (666, 5630), (1875, 14250), (1885, 14700), (2428, 19300), (2545, 19650), (3000, 24600), (3200, 65535)],
            min_dx = 64,
            min_dy = 500,
            max_points = 20,
        )
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
            self._output_memory.add_point(measured_rpm, self._output_pwm_value, monotonic = True)

        if target_changed or output_wrong:
            # Optimize PWM with linear interpolation (and extrapolation).
            pwm = self._output_memory.value_at(target_rpm)
            if abs(self._output_pwm_value - pwm) > self._output_stable_threshold:
                self.pwm_output.duty_u16(pwm)
                self._output_pwm_value = pwm
                self._output_timestamp = Timestamp()
                self._output_stored = False
                self.output_stable = False
