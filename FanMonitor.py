from machine import Pin
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

class FanMonitor:
    # Theoretical model, where RPM and millivolts match exactly.
    stop_rpm = 0
    max_rpm = 10_000
    millivolts_for_max_rpm = 10_000
    stable_delay = 1_000
    rpm_stable_threshold = 50

    def __init__(self, sm, pin):
        tachy_off_time = 2_000 # Over 2 seconds = less than 30 rpm will be considered "off".
        self.tachy_input = TachyInputPIO(sm, pin, tachy_off_time)
        self.rpm = 0
        self.stable = False
        self._rpm_change_timestamp = Timestamp()
        self._rpm_stable_low = 0
        self._rpm_stable_high = self.rpm_stable_threshold * 2

    def update(self):
        dt = self.tachy_input and self.tachy_input.diff_us() or -1
        self.rpm = 60_000_000 // dt if dt > 0 else 0
        lo = min(self.rpm - self._rpm_stable_low, 0)
        hi = max(self.rpm - self._rpm_stable_high, 0)
        if lo < 0 or hi > 0:
            self._rpm_stable_low += lo + hi
            self._rpm_stable_high += lo + hi
            self._rpm_change_timestamp = Timestamp()
        self.stable = not self._rpm_change_timestamp.between(0, self.stable_delay)

    @classmethod
    def millivolts_to_rpm(cls, mv):
        rpm = cls.max_rpm * mv // cls.millivolts_for_max_rpm
        if rpm < cls.stop_rpm:
            return 0
        return max(cls.stop_rpm, min(cls.max_rpm, rpm))

class VilpeECoFlow125P700(FanMonitor):
    # Vilpe ECo Flow rpm rises linearly with voltage between lowest and highest.
    # 0 rpm = 0 mV and 3030 rpm = 7750 mV, tends to stop below 270-330 rpm.
    stop_rpm = 270
    max_rpm = 3_030
    millivolts_for_max_rpm = 7_750
    stable_delay = 10_000
    rpm_stable_threshold = 30
    percentage_stable_threshold = 1
