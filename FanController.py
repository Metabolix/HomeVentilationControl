from machine import Pin, PWM
from Timestamp import Timestamp
from LinearInterpolator import LinearInterpolator

class FanController:
    def __init__(
        self, *,
        pin_switch_on,
        pin_switch_own,
        pin_pwm_out,
        max_effect,
    ):
        self.pin_switch_on = pin_switch_on is not None and Pin(pin_switch_on, Pin.IN, pull = Pin.PULL_UP)
        self.pin_switch_own = pin_switch_own is not None and Pin(pin_switch_own, Pin.IN, pull = Pin.PULL_UP)

        self.pwm_output = pin_pwm_out is not None and PWM(Pin(pin_pwm_out, Pin.OUT, value = 0))
        if self.pwm_output:
            self.pwm_output.freq(10_000)
            self.pwm_output.duty_u16(0)
        self.pwm = 0
        self.changed_timestamp = Timestamp(None)
        self.stable = False
        self.pwm_stable_threshold = 100
        self.target = 0
        self.memory = LinearInterpolator(
            [(-1, -1), (max_effect + 1, 65536)],
            min_dx = max_effect // 50,
            min_dy = 500,
            max_points = 20,
        )
        self.memory_updated = False

    def update(self, target, effect, effect_stable, effect_stable_threshold, stable_delay):
        self.switch_on = 1 - self.pin_switch_on() if self.pin_switch_on else 0
        self.switch_own = 1 - self.pin_switch_own() if self.pin_switch_own else 0
        self.target = target

        if not self.pwm_output or not self.switch_on or not self.switch_own:
            self.changed_timestamp = Timestamp(None)
            return

        effect_wrong = abs(target - effect) > effect_stable_threshold
        self.stable = effect_stable and self.changed_timestamp.between(stable_delay, None)

        if self.stable and not self.memory_updated:
            self.memory_updated = True
            self.memory.add_point(effect, self.pwm, monotonic = True)

        if effect_wrong:
            # Optimize PWM with linear interpolation.
            new_pwm = max(0, min(65535, self.memory.value_at(target)))
            # Put some extra effort into starting the fan.
            if target and not effect:
                new_pwm = max(new_pwm, self.pwm)
                if self.stable:
                    new_pwm = min(65535, max(new_pwm, self.pwm + self.pwm_stable_threshold, self.pwm * 2))
            # Avoid doing minimal changes to the PWM.
            if abs(self.pwm - new_pwm) >= self.pwm_stable_threshold:
                self.pwm_output.duty_u16(new_pwm)
                self.pwm = new_pwm
                self.stable = False
                self.changed_timestamp = Timestamp()
                self.memory_updated = False
