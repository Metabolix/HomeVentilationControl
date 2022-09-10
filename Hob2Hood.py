from machine import Pin
from rp2 import PIO, StateMachine, asm_pio
from Timestamp import Timestamp

# Hob2Hood IR codes. 25 bits, simple on-off, 733 us/bit.
Hob2Hood_IR_codes = {
    0b_1_00101101_00101100_00101011: "L1", # 01 2d 2c 2b, light on
    0b_1_00101010_00101001_00101000: "L0", # 01 2a 29 28, light off
    0b_1_00100111_00100110_00100101: 0,    # 01 27 26 25, speed 0
    0b_1_10010011_10010010_10010001: 1,    # 01 93 92 91, speed 1
    0b_1_10010000_10001111_10001110: 2,    # 01 90 8f 8e, speed 2
    0b_1_00011110_00011101_00011100: 3,    # 01 1e 1d 1c, speed 3
    0b_1_10001101_10001100_10001011: 4,    # 01 8d 8c 8b, speed 4
}

class Hob2HoodReceiverPIO:
    """PIO for receiving Hob2Hood IR codes: 25 bits, simple on-off, 733 us/bit.
    TX FIFO: None.
    RX FIFO: 25-bit messages, with bits inverted.
    PIO instructions: 5
    """

    def __init__(self, sm, pin):
        if sm is None or pin is None:
            self.get = lambda: None
            return
        pio_freq = 64_000_000 // 733 # 64 cycles to one bit.
        self.pin = Pin(pin, Pin.IN, pull = None)
        self.sm = StateMachine(sm, self.pio_program, freq = pio_freq, in_base = self.pin)
        self.sm.restart()
        self.sm.active(1)

    def get(self):
        # Invert bits and apply 25-bit mask.
        return ~self.sm.get() & 0x1ffffff if self.sm.rx_fifo() else None

    @asm_pio(fifo_join = PIO.JOIN_RX, autopush = True, push_thresh = 25)
    def pio_program():
        # wait for 1 to make sure that IR receiver is present.
        wait(1, pin, 0)
        # wait for first bit (0 = IR active), delay until middle of bit.
        wait(0, pin, 0) .delay(30)
        # read 25 bits.
        set(x, 24)
        label("next_bit")
        in_(pins, 1) .delay(31)
        jmp(x_dec, "next_bit") .delay(31)

class Hob2Hood:
    def __init__(self, *, receiver = None, sm = None, pin = None):
        self.receiver = receiver if sm is None or pin is None else Hob2HoodReceiverPIO(sm, pin)
        self.speed = 0
        self.light = 0
        self.speed_timestamp = Timestamp(None)
        self.light_timestamp = Timestamp(None)

    def update(self):
        new_ir = self.receiver and self.receiver.get()
        if new_ir in Hob2Hood_IR_codes:
            ir_code = Hob2Hood_IR_codes[new_ir]
            if ir_code == "L0" or ir_code == "L1":
                self.light_timestamp = Timestamp()
                self.light = ir_code == "L1" and 1 or 0
                if not self.light:
                    # Light is off, fan should be too. Play it safe.
                    self.speed = 0
                    self.speed_timestamp = Timestamp()
            else:
                self.speed = ir_code
                self.speed_timestamp = Timestamp()
