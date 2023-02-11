import json
import time
from machine import Pin, WDT, mem32
from Timestamp import Timestamp
from DHT22 import DHT22
from Hob2Hood import Hob2Hood
from FanController import FanController

def pin_make_vcc(num):
    """Set a pin high and set drive strength to 12 mA"""
    Pin(num, Pin.OUT, value = 1)
    PADS_BANK0 = 0x4001c000
    ATOMIC_OR = 0x2000
    mem32[ATOMIC_OR + PADS_BANK0 + 4 + num * 4] = 0x30

class HomeVentilationControl:
    def __init__(self):
        pin_make_vcc(9)
        self.air = DHT22(10)
        self.ir = Hob2Hood(sm = 0, pin = 11)

        self.c0 = FanController(
            pin_switch_on = 19, pin_switch_own = 22,
            pin_voltage_adc = 28, ctrl_translate = FanController.VilpeECoIdeal,
            sm_tachy = 1, pin_tachy = 16,
            pin_pwm_out = 17,
        )
        self.c1 = FanController(
            pin_switch_on = 21, pin_switch_own = 20,
            pin_voltage_adc = 27, ctrl_translate = FanController.LapetekVirgola5600XH,
            sm_tachy = 2, pin_tachy = 26,
            pin_pwm_out = 18,
        )

        self.wifi_rpm_0_min = self.wifi_rpm_1_min = 0
        self.wifi_rpm_0_max = self.wifi_rpm_1_max = 9999
        self.wifi_rpm_0_ttl = self.wifi_rpm_1_ttl = 0
        self.wifi_rpm_0_timestamp = self.wifi_rpm_1_timestamp = Timestamp(None)
        self.ir_rpm_target = self.ir_rpm = 0
        self.c1_fixed_ctrl_rpm = self.c1_fixed_ctrl_level = -1
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

        if "ir_speeds" not in self.conf:
            self.conf["ir_speeds"] = (0, 1300, 2000, 2300, 2600)

        if "hood_speeds" not in self.conf:
            self.conf["hood_speeds"] = (0, 330, 1000, 1600, 2600, 2600, 2600, 2600, 2600)

    def _save_conf(self):
        if self.conf != self.conf_saved:
            with open("HomeVentilationControl.conf", "w") as f:
                json.dump(self.conf, f)
            self.conf_saved = dict(self.conf)

    def update(self):
        self.updated = Timestamp()
        self.uptime.update()
        self.air.update()
        self.ir.update()
        self.c0.update()
        self.c1.update()

        self.ir.speed_timestamp.set_valid_between(0, 5_400_000)
        ir_valid = self.ir.speed_timestamp.valid()
        try:
            self.ir_rpm_target = self.conf["ir_speeds"][self.ir.speed if ir_valid else 0]
        except:
            self.ir_rpm_target = 0

        if self.ir_rpm_target:
            # Remember latest non-zero IR RPM.
            if not self.ir_rpm:
                self.ir_high_start = Timestamp()
            self.ir_high_end = Timestamp()
            self.ir_rpm = self.ir_rpm_high = self.ir_rpm_target
        elif self.ir_rpm > 0:
            # Lower RPM smoothly to zero, depending on previous cooking time.
            self.ir_duration = self.ir_high_start.ms() - self.ir_high_end.ms()
            self.ir_rpm = 0
            ir_slope_time = 120_000
            if self.ir_duration > 300_000:
                ir_slope_time = 180_000
            if self.ir_duration > 600_000:
                ir_slope_time = 240_000
            ir_slope_pos = self.ir_high_end.ms()
            if ir_slope_pos < ir_slope_time:
                self.ir_rpm = self.ir_rpm_high * (ir_slope_time - ir_slope_pos) // ir_slope_time

        # Custom output levels for the kitchen hood.
        # It's supposed to return to base speed after a fixed timeout, but
        # sometimes it fails to do that. Use the timestamp to fix this.
        # Also, use setting 0 only if the control says so, otherwise use 1,
        # because in some configurations the fan is not supposed to stop ever.
        self.c1.ctrl_timestamp.set_valid_between(0, 5_400_000)
        i = self.c1.ctrl_level[0]
        i = i if i == 0 or self.c1.ctrl_timestamp.valid() else 1
        try:
            self.c1_fixed_ctrl_rpm = self.conf["hood_speeds"][i]
            self.c1_fixed_ctrl_level = i
        except:
            self.c1_fixed_ctrl_rpm = self.c1_fixed_ctrl_level = -1

        r = self.c0.ctrl_rpm
        if self.wifi_rpm_0_timestamp.valid():
            r = min(max(r, self.wifi_rpm_0_min), self.wifi_rpm_0_max)
        self.c0.set_rpm(r)

        r = self.c1.ctrl_rpm if self.c1_fixed_ctrl_level < 0 else self.c1_fixed_ctrl_rpm
        if ir_valid:
            r = max(r, self.ir_rpm)
        if self.wifi_rpm_1_timestamp.valid():
            r = min(max(r, self.wifi_rpm_1_min), self.wifi_rpm_1_max)
        self.c1.set_rpm(r)

        try:
            if self.conf["watchdog"] and not self.watchdog:
                self.watchdog = WDT(timeout = 8388) # Max timeout in RP2040.
            self.watchdog.feed()
        except:
            pass

    # Web interface is implemented as a module for WebMain.
    # See https://github.com/Metabolix/MicroPython-WebMain
    def __call__(self, request):
        if not request:
            if not self.updated.between(0, 200):
                self.update()
            return
        method = request.method
        query = request.path_info

        if method == "GET" and query == "":
            return request.reply_static("HomeVentilationControl.html")

        if method == "GET" and query == "?txt":
            return request.reply(content = str(self))

        if method == "GET" and query == "?json":
            return request.reply(mime = "application/json", content = json.dumps(self.state()))

        if method == "POST":
            try:
                what, params = query.split("=")
                params = [int(x) for x in params.split(",")]
                if what == "?ir_speeds":
                    self.conf["ir_speeds"] = [params[i] for i in range(5)]
                    self._save_conf()
                elif what == "?hood_speeds":
                    self.conf["hood_speeds"] = [params[i] for i in range(9)]
                    self._save_conf()
                elif what == "?wifi_rpm_0":
                    self.wifi_rpm_0_min, self.wifi_rpm_0_max, self.wifi_rpm_0_ttl = params
                    self.wifi_rpm_0_timestamp = Timestamp()
                    self.wifi_rpm_0_timestamp.set_valid_between(0, self.wifi_rpm_0_ttl * 1000)
                elif what == "?wifi_rpm_1":
                    self.wifi_rpm_1_min, self.wifi_rpm_1_max, self.wifi_rpm_1_ttl = params
                    self.wifi_rpm_1_timestamp = Timestamp()
                    self.wifi_rpm_1_timestamp.set_valid_between(0, self.wifi_rpm_1_ttl * 1000)
                else:
                    params = None
            except:
                return request.reply(status = 401)
            return request.reply(status = 200 if params else 404)

    def state(self):
        c0, c1 = self.c0, self.c1
        clock = "{0:04}-{1:02}-{2:02}T{3:02}:{4:02}:{5:02}Z".format(*time.gmtime())
        return {
            "clock": clock,
            "uptime": self.uptime.ms(),
            "conf": self.conf,
            "air": {
                "temperature": self.air.temperature,
                "rh": self.air.humidity,
            },
            "0": {
                "rpm": c0.rpm,
                "target_rpm": c0.target_rpm,
                "on": c0.switch_on,
                "own": c0.switch_own,
                "wifi": {
                    "min": self.wifi_rpm_0_min,
                    "max": self.wifi_rpm_0_max,
                    "timestamp": self.wifi_rpm_0_timestamp.ms(),
                    "ttl": self.wifi_rpm_0_ttl,
                },
                "control": {
                    "rpm": c0.ctrl_rpm,
                    "level": c0.ctrl_level[0],
                    "level_unit": c0.ctrl_level[1],
                    "millivolts": c0.ctrl_millivolts,
                    "timestamp": c0.ctrl_timestamp.ms(),
                },
            },
            "1": {
                "rpm": c1.rpm,
                "target_rpm": c1.target_rpm,
                "on": c1.switch_on,
                "own": c1.switch_own,
                "wifi": {
                    "min": self.wifi_rpm_1_min,
                    "max": self.wifi_rpm_1_max,
                    "timestamp": self.wifi_rpm_1_timestamp.ms(),
                    "ttl": self.wifi_rpm_1_ttl,
                },
                "control": {
                    "rpm": c1.ctrl_rpm,
                    "level": c1.ctrl_level[0],
                    "level_unit": c1.ctrl_level[1],
                    "millivolts": c1.ctrl_millivolts,
                    "timestamp": c1.ctrl_timestamp.ms(),
                    "rpm_fixed": self.c1_fixed_ctrl_rpm,
                    "level_fixed": self.c1_fixed_ctrl_level,
                },
                "ir": {
                    "rpm": self.ir_rpm,
                    "speed": self.ir.speed,
                    "speed_timestamp": self.ir.speed_timestamp.ms(),
                    "light": self.ir.light,
                    "light_timestamp": self.ir.light_timestamp.ms(),
                },
            },
        }

    def __str__(self):
        c0, c1 = self.c0, self.c1
        str_none = lambda x: x is None and "None" or x
        str_temp_rh = lambda x: x is None and "None" or f"{x // 10}.{x % 10}"
        clock = "{0:04}-{1:02}-{2:02}T{3:02}:{4:02}:{5:02}Z".format(*time.gmtime())
        return f"""{self.__class__.__name__}
uptime: {self.uptime}
clock: {clock}
air: {str_temp_rh(self.air.temperature)} °C, RH {str_temp_rh(self.air.humidity)} %

FAN 0 (main):
    RPM:  {c0.rpm:4} rpm, target {str_none(c0.target_rpm):4} rpm (on {c0.switch_on}, own {c0.switch_own})
    WiFi: {self.wifi_rpm_0_min:4} - {self.wifi_rpm_0_max:4} rpm, age {self.wifi_rpm_0_timestamp}, ttl {self.wifi_rpm_0_ttl}
    CTRL: {c0.ctrl_rpm:4} rpm ({c0.ctrl_level[0]} {c0.ctrl_level[1]}, {c0.ctrl_millivolts} mV), age {c0.ctrl_timestamp}

FAN 1 (kitchen hood):
    RPM:  {c1.rpm:4} rpm, target {str_none(c1.target_rpm):4} rpm (on {c1.switch_on}, own {c1.switch_own})
    WiFi: {self.wifi_rpm_1_min:4} - {self.wifi_rpm_1_max:4} rpm, age {self.wifi_rpm_1_timestamp}, ttl {self.wifi_rpm_1_ttl}
    CTRL: {c1.ctrl_rpm:4} rpm ({c1.ctrl_level[0]} {c1.ctrl_level[1]}, {c1.ctrl_millivolts} mV), age {c1.ctrl_timestamp}
    Fix:  {self.c1_fixed_ctrl_rpm:4} rpm ({self.c1_fixed_ctrl_level} {c1.ctrl_level[1]})
    IR:   {self.ir_rpm:4} rpm, speed {self.ir.speed}, age {self.ir.speed_timestamp}

"""

def run():
    import time
    s = HomeVentilationControl()
    while True:
        time.sleep_ms(1000)
        s.update()
        print(str(s))
