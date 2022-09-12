# This script prints RPM and PWM values which can be used to manually
# determine optimal data points for FanController._get_pwm_estimate.
# Run interactively, copy data to a text file and plot with gnuplot:
# gnuplot> plot 'data.txt' using 1:2, 'line.txt' using 1:2 with lines
# Hand-pick points to line.txt (for gluplot) and to _output_memory.

from FanController import FanController
from Timestamp import Timestamp
from time import sleep_ms as s

# Init controller with only PWM and tachy.
# Without switches it won't mess up PWM in .update().
c = FanController(
    sm_tachy = 1, pin_tachy = 16,
    pin_pwm_out = 17,
)

# PWM setter.
def p(value = None, _cache = [0]):
    if value is None:
        return _cache[0]
    _cache[0] = value
    c.pwm_output.duty_u16(value)

# RPM getter with delay (to let the fan settle).
def r(delay_ms = 1000):
    c.update()
    t = Timestamp()
    while t.between(0, delay_ms):
        c.update()
    return c.rpm

print(f"Finding end points...")
max_rpm = 0
p(65535)
while True:
    rpm = r()
    if rpm < max_rpm:
        rpm = r(5000)
        if rpm < max_rpm:
            break
    max_rpm = rpm
max_rpm = r()
print(f"max_rpm = {max_rpm:5} RPM")

p(65500)
while r() > 98 * max_rpm // 100:
    p(p() - 2000)
while r() < 99 * max_rpm // 100:
    p(p() + 100)
max_pwm = p()
print(f"max_pwm = {max_pwm:5}")

while r(10):
    p(max(0, p() - 200))
for ms in [500, 2000]:
    while not r(ms):
        p(p() + 100)
    on_pwm = p()
    while r(ms):
        p() and p(p() - 100)
off_pwm = p()
print(f"off_pwm = {off_pwm:5}")
print(f"on_pwm  = {on_pwm:5}")
p(on_pwm)
while not r():
    continue
on_rpm = r(10000)
print(f"on_rpm = {on_rpm:5} RPM")

print("\nTest data:\nRPM PWM\n")
points = 1000
for i in range(0, points + 1):
    p(on_pwm + (max_pwm - on_pwm) * i // points)
    rpm = r(100)
    print(f"{rpm} {p()}")
