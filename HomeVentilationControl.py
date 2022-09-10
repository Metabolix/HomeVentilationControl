import json
import time
from machine import Pin, WDT, mem32
from Timestamp import Timestamp

def pin_make_vcc(num):
    """Set a pin high and set drive strength to 12 mA"""
    Pin(num, Pin.OUT, value = 1)
    PADS_BANK0 = 0x4001c000
    ATOMIC_OR = 0x2000
    mem32[ATOMIC_OR + PADS_BANK0 + 4 + num * 4] = 0x30

class HomeVentilationControl:
    def __init__(self):
        pin_make_vcc(9)

        self._load_conf()
        self.watchdog = None
        self.uptime = Timestamp()
        self.update()

    def _load_conf(self):
        try:
            with open("HomeVentilationControl.conf", "r") as f:
                self.conf = json.load(f)
            self.conf_saved = dict(self.conf)
        except:
            self.conf = self.conf_saved = None

        if type(self.conf) != dict:
            self.conf = dict()

        if "watchdog" not in self.conf:
            self.conf["watchdog"] = 1

    def update(self):
        self.uptime.update()
        try:
            if self.conf["watchdog"] and not self.watchdog:
                self.watchdog = WDT(timeout = 8388) # Max timeout in RP2040.
            self.watchdog.feed()
        except:
            pass

    def __str__(self):
        clock = "{0:04}-{1:02}-{2:02}T{3:02}:{4:02}:{5:02}Z".format(*time.gmtime())
        return f"""{self.__class__.__name__}
uptime: {self.uptime}
clock: {clock}

"""

def run():
    import time
    s = HomeVentilationControl()
    while True:
        time.sleep_ms(1000)
        s.update()
        print(str(s))
