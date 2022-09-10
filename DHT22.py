from machine import Pin, time_pulse_us
from time import sleep_ms
from Timestamp import Timestamp

class DHT22:
    def __init__(self, pin):
        self.pin = Pin(pin, Pin.IN, pull = Pin.PULL_UP)
        self.humidity = self.temperature = None
        self.timestamp = Timestamp(None)
        self._init_time = Timestamp(2_000)

    def _read(self):
        data = bytearray(5)

        # Host pulls low for 1 ms, then high for 20-40 us, and sensor takes over.
        # Using the internal pull-down/pull-up resistors seems to be enough.
        self.pin.init(Pin.IN, pull = Pin.PULL_DOWN)
        sleep_ms(1)
        self.pin.init(Pin.IN, pull = Pin.PULL_UP)

        # Sensor start: low for 80 us, high for 80 us.
        us_0 = time_pulse_us(self.pin, 0, 200)
        us_1 = time_pulse_us(self.pin, 1, 100)
        if us_0 > 99 or us_1 > 99:
            return None, None

        # Sensor data: 40 bits: low for 50 us, then high for 28 us (0) or 70 us (1).
        # Sensor end: low for 50 us.
        for i in range(40):
            us = time_pulse_us(self.pin, 1, 50 + 70 + 10)
            if us > 50:
                data[i >> 3] |= 1 << (7 - (i & 7))

        check_ok = (data[0] + data[1] + data[2] + data[3]) & 0xff == data[4]
        humidity = (data[0] << 8) + data[1]
        temperature = (((data[2] << 8) + data[3]) & 0x7fff) * (-1 if data[2] & 0x80 else 1)

        # Temperature is in 1/10 degrees Celsius.
        # Humidity is in 1/10 percents RH.
        if check_ok and 0 <= humidity <= 1000 and -500 <= temperature <= 1000:
            return humidity, temperature
        return None, None

    def update(self):
        if self._init_time and not self._init_time.passed():
            return
        self._init_time = None

        new_rh, new_temp = self._read()
        # None, None == error.
        # Also handle 0, 0 as error, the sensor says that in the beginning and it's not likely to actually happen.
        if new_rh or new_temp:
            self.humidity, self.temperature = new_rh, new_temp
            self.timestamp = Timestamp()
        elif not self.timestamp.between(0, 120_000):
            self.humidity = self.temperature = None
