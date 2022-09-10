import json
from machine import WDT

class HomeVentilationControl:
    def __init__(self):
        self._load_conf()
        self.watchdog = None
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
        try:
            if self.conf["watchdog"] and not self.watchdog:
                self.watchdog = WDT(timeout = 8388) # Max timeout in RP2040.
            self.watchdog.feed()
        except:
            pass

    def __str__(self):
        return f"""{self.__class__.__name__} running."""

def run():
    import time
    s = HomeVentilationControl()
    while True:
        time.sleep_ms(1000)
        s.update()
        print(str(s))
