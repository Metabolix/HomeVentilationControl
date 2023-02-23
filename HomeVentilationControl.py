import json
import time
from machine import Pin, WDT, mem32, unique_id
from binascii import hexlify
from Timestamp import Timestamp
from DHT22 import DHT22
from Hob2Hood import Hob2Hood
from ControllerMonitor import *
from FanMonitor import *
from FanController import FanController
from LinearInterpolator import LinearInterpolator

def pin_make_vcc(num):
    """Set a pin high and set drive strength to 12 mA"""
    Pin(num, Pin.OUT, value = 1)
    PADS_BANK0 = 0x4001c000
    ATOMIC_OR = 0x2000
    mem32[ATOMIC_OR + PADS_BANK0 + 4 + num * 4] = 0x30

def unique_id_str():
    return hexlify(unique_id()).decode()

class ExternalLogic:
    def __init__(self):
        self.set_interpolator_points([(0, 0), (100, 100)])
        self.ttl = 0
        self.timestamp = Timestamp(None)

    def set_interpolator_points(self, points):
        self.interpolator = LinearInterpolator(points)

    def set_ttl(self, ttl):
        self.ttl = int(ttl)
        self.timestamp = Timestamp()
        self.timestamp.set_valid_between(0, self.ttl)

    def apply_to(self, value):
        if self.timestamp.valid():
            value = self.interpolator.value_at(value)
        return value

class CookingLogic:
    def __init__(self):
        self.value = 0
        self.cooking_started = False

    def update(self, cooking_assumed, value):
        if cooking_assumed:
            # Record cooking time and most recent fan value.
            if not self.cooking_started:
                self.cooking_started = Timestamp()
            self.cooking_ended = Timestamp()
            self.cooking_duration = self.cooking_started.ms() - self.cooking_ended.ms()
            self.value = self.value_when_cooking = value
        else:
            self.cooking_started = False
            if self.value:
                # Non-zero value = timestamps are also initialized above.
                # Lower speed smoothly to zero, depending on previous cooking time.
                slope_duration = max(30_000, min(180_000, self.cooking_duration // 5))
                slope_now = self.cooking_ended.ms()
                self.value = max(0, self.value_when_cooking * (slope_duration - slope_now) // slope_duration)

    def apply_to(self, value):
        return max(value, self.value)

class HomeVentilationControl:

    _default_conf = {
        "watchdog": True,
        "ir_speeds": (0, 1300, 2000, 2300, 2600),
        "hood_speeds": (0, 330, 1000, 1600, 2600, 2600, 2600, 2600, 2600),
    }

    def __init__(self):
        pin_make_vcc(9)
        self.air = DHT22(10)
        self.ir = Hob2Hood(sm = 0, pin = 11)
        self.cooking_logic = CookingLogic()

        self.cm0 = VilpeECoIdeal(28)
        self.cm1 = LapetekVirgola5600XH(27)

        self.fm0 = VilpeECoFlow125P700(sm = 1, pin = 16)
        self.fm1 = VilpeECoFlow125P700(sm = 2, pin = 26)

        self.c0 = FanController(
            pin_switch_on = 19,
            pin_switch_own = 22,
            pin_pwm_out = 17,
            max_effect = self.fm0.max_rpm,
        )
        self.c1 = FanController(
            pin_switch_on = 21,
            pin_switch_own = 20,
            pin_pwm_out = 18,
            max_effect = self.fm1.max_rpm,
        )
        self.wifi_0 = ExternalLogic()
        self.wifi_1 = ExternalLogic()
        self.conf = self._load_conf()
        self.watchdog = None
        self.uptime = Timestamp()
        self.update()

    def _load_conf(self):
        conf = dict(self._default_conf)
        try:
            with open("HomeVentilationControl.conf", "r") as f:
                conf.update(json.load(f))
        except:
            pass
        return conf

    def _save_conf(self):
        old_conf = self._load_conf()
        if self.conf != old_conf:
            with open("HomeVentilationControl.conf", "w") as f:
                json.dump(self.conf, f)

    def update(self):
        self.updated = Timestamp()
        self.uptime.update()
        self.air.update()
        self.ir.update()
        self.cm0.update()
        self.cm1.update()
        self.fm0.update()
        self.fm1.update()

        try:
            ir_value = self.conf["ir_speeds"][self.ir.speed]
        except:
            ir_value = 0

        # Custom output levels for the kitchen hood.
        try:
            c1_rpm = self.conf["hood_speeds"][self.cm1.level]
        except:
            c1_rpm = self.fm1.millivolts_to_rpm(self.cm1.millivolts)

        self.cooking_logic.update(self.ir.speed > 0, ir_value)

        c0_rpm = self.fm0.millivolts_to_rpm(self.cm0.millivolts)
        r = c0_rpm
        r = self.wifi_0.apply_to(r)
        self.c0.update(r, self.fm0.rpm, self.fm0.stable, self.fm0.rpm_stable_threshold, self.fm0.stable_delay)

        r = c1_rpm
        r = max(r, ir_value)
        r = self.cooking_logic.apply_to(r)
        r = self.wifi_1.apply_to(r)
        self.c1.update(r, self.fm1.rpm, self.fm1.stable, self.fm1.rpm_stable_threshold, self.fm1.stable_delay)

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

        if method == "POST" and query == "?json-post":
            try:
                self._handle_post(json.loads(request.read_body(4096)))
            except:
                return request.reply(status = 401)
            return request.reply(status = 200)

    def _handle_post(self, obj):
        for what, params in obj.items():
            if what == "ir_speeds":
                self.conf["ir_speeds"] = [params[i] for i in range(5)]
            elif what == "hood_speeds":
                self.conf["hood_speeds"] = [params[i] for i in range(9)]
            elif what in ("wifi_0", "wifi_1"):
                w = getattr(self, what)
                # Reset TTL first, in case of bad data.
                w.set_ttl(0)
                w.set_interpolator_points(params)
                w.set_ttl(obj[what + "_ttl"])
            elif what == "save_conf" and params == [1]:
                self._save_conf()

    def state(self):
        c0, c1 = self.c0, self.c1
        cm0, cm1 = self.cm0, self.cm1
        clock = "{0:04}-{1:02}-{2:02}T{3:02}:{4:02}:{5:02}Z".format(*time.gmtime())
        return {
            "unique_id": unique_id_str(),
            "clock": clock,
            "uptime": self.uptime.ms(),
            "conf": self.conf,
            "air": {
                "temperature": self.air.temperature,
                "rh": self.air.humidity,
            },
            "0": {
                "rpm": self.fm0.rpm,
                "target": c0.target,
                "on": c0.switch_on,
                "own": c0.switch_own,
                "wifi": {
                    "points": self.wifi_0.interpolator.points,
                    "valid": self.wifi_0.timestamp.valid(),
                    "age": self.wifi_0.timestamp.ms(),
                    "ttl": self.wifi_0.ttl,
                },
                "controller": {
                    "level": cm0.level,
                    "unit": cm0.unit,
                    "millivolts": cm0.millivolts,
                    "age": cm0.timestamp.ms(),
                    "measured_level": cm0.measured_level,
                },
            },
            "1": {
                "rpm": self.fm1.rpm,
                "target": c1.target,
                "on": c1.switch_on,
                "own": c1.switch_own,
                "wifi": {
                    "points": self.wifi_1.interpolator.points,
                    "valid": self.wifi_1.timestamp.valid(),
                    "age": self.wifi_1.timestamp.ms(),
                    "ttl": self.wifi_1.ttl,
                },
                "controller": {
                    "level": cm1.level,
                    "unit": cm1.unit,
                    "millivolts": cm1.millivolts,
                    "age": cm1.timestamp.ms(),
                    "measured_level": cm1.measured_level,
                },
                "ir": {
                    "speed": self.ir.speed,
                    "expired_speed": self.ir.expired_speed,
                    "speed_age": self.ir.speed_timestamp.ms(),
                    "light": self.ir.light,
                    "light_age": self.ir.light_timestamp.ms(),
                },
            },
        }

    def __str__(self):
        c0, c1 = self.c0, self.c1
        cm0, cm1 = self.cm0, self.cm1
        ctrl_rpm_0 = self.fm0.millivolts_to_rpm(self.cm0.millivolts)
        ctrl_rpm_1 = self.fm1.millivolts_to_rpm(self.cm1.millivolts)
        str_none = lambda x: x is None and "None" or x
        str_temp_rh = lambda x: x is None and "None" or f"{x // 10}.{x % 10}"
        str_fixed = lambda x: f"level fixed from {x.measured_level} {x.unit}, age {x.timestamp}" if x.level != x.measured_level else "level valid"
        str_wifi = lambda x: f"{len(x.interpolator.points)} data points, ttl {Timestamp.timestr(x.ttl)}, age {x.timestamp}"
        clock = "{0:04}-{1:02}-{2:02}T{3:02}:{4:02}:{5:02}Z".format(*time.gmtime())
        return f"""{self.__class__.__name__}
uptime: {self.uptime}
clock: {clock}
air: {str_temp_rh(self.air.temperature)} °C, RH {str_temp_rh(self.air.humidity)} %

FAN 0 (main):
    RPM:  {self.fm0.rpm:4} rpm, target {str_none(c0.target):4} rpm (on {c0.switch_on}, own {c0.switch_own})
    WiFi: {str_wifi(self.wifi_0)}
    CTRL: {ctrl_rpm_0:4} rpm ({cm0.level} {cm0.unit}, {cm0.millivolts} mV), age {cm0.timestamp}
          {"":4}     ({str_fixed(cm0)})

FAN 1 (kitchen hood):
    RPM:  {self.fm1.rpm:4} rpm, target {str_none(c1.target):4} rpm (on {c1.switch_on}, own {c1.switch_own})
    WiFi: {str_wifi(self.wifi_1)}
    CTRL: {ctrl_rpm_1:4} rpm ({cm1.level} {cm1.unit}, {cm1.millivolts} mV), age {cm1.timestamp}
          {"":4}     ({str_fixed(cm1)})
    IR:   {self.cooking_logic.value:4} rpm, level {self.ir.speed}, age {self.ir.speed_timestamp}

"""

def run():
    import time
    s = HomeVentilationControl()
    while True:
        time.sleep_ms(1000)
        s.update()
        print(str(s))
