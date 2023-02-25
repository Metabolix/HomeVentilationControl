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
        "modify_cm0": ((0, 0), (100, 100)),
        "modify_cm1": ((0, 0), (100, 100)),
        "modify_ir": ((0, 0), (4, 100)),
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

        self._default_conf = dict(self._default_conf)
        self._default_conf.update({
            "modify_cm0": [(level, self.fm0.millivolts_to_percentage(millivolts)) for level, millivolts in self.cm0.levels_to_millivolts],
            "modify_cm1": [(level, self.fm1.millivolts_to_percentage(millivolts)) for level, millivolts in self.cm1.levels_to_millivolts],
        })

        self.c0 = FanController(
            pin_switch_on = 19,
            pin_switch_own = 22,
            pin_pwm_out = 17,
            max_effect = 100,
        )
        self.c1 = FanController(
            pin_switch_on = 21,
            pin_switch_own = 20,
            pin_pwm_out = 18,
            max_effect = 100,
        )
        self.wifi_0 = ExternalLogic()
        self.wifi_1 = ExternalLogic()
        self.conf = self._load_conf()
        self.modify_cm0 = LinearInterpolator(self.conf["modify_cm0"])
        self.modify_cm1 = LinearInterpolator(self.conf["modify_cm1"])
        self.modify_ir = LinearInterpolator(self.conf["modify_ir"])
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

        ir_value = self.modify_ir.value_at(self.ir.speed)
        c0_value = self.modify_cm0.value_at(self.cm0.level)
        c1_value = self.modify_cm1.value_at(self.cm1.level)

        self.cooking_logic.update(self.ir.speed > 0, ir_value)

        c0_value = self.fm0.millivolts_to_percentage(self.cm0.millivolts)
        c0_value = self.wifi_0.apply_to(c0_value)
        self.c0.update(c0_value, self.fm0.percentage, self.fm0.stable, self.fm0.percentage_stable_threshold, self.fm0.stable_delay)

        c1_value = max(c1_value, ir_value)
        c1_value = self.cooking_logic.apply_to(c1_value)
        c1_value = self.wifi_1.apply_to(c1_value)
        self.c1.update(c1_value, self.fm1.percentage, self.fm1.stable, self.fm1.percentage_stable_threshold, self.fm1.stable_delay)

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
            if what in ("modify_cm0", "modify_cm1", "modify_ir"):
                setattr(self, what, LinearInterpolator(params))
                self.conf[what] = params
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
                "percentage": self.fm0.percentage,
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
                "percentage": self.fm1.percentage,
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
        str_temp_rh = lambda x: x is None and "None" or f"{x // 10}.{x % 10}"
        str_fixed = lambda x: f"level fixed from {x.measured_level} {x.unit}, age {x.timestamp}" if x.level != x.measured_level else "level valid"
        str_wifi = lambda x: f"{len(x.interpolator.points)} data points, ttl {Timestamp.timestr(x.ttl)}, age {x.timestamp}"
        str_output = lambda c: f"{c.target:3} %, on {c.switch_on:1}, own {c.switch_own:1}, {'stable' if c.stable else 'adjusting'}"
        str_ctrl = lambda cm, fm: f"{fm.millivolts_to_percentage(cm.millivolts):3} %, from {cm.millivolts:5} mV = {cm.level} {cm.unit}, {str_fixed(cm)}"
        clock = "{0:04}-{1:02}-{2:02}T{3:02}:{4:02}:{5:02}Z".format(*time.gmtime())
        return f"""{self.__class__.__name__}
uptime: {self.uptime}
clock: {clock}
air: {str_temp_rh(self.air.temperature)} °C, RH {str_temp_rh(self.air.humidity)} %

FAN 0 (main):
    Fan Monitor:  {self.fm0.percentage:3} % = {self.fm0.rpm:4} rpm
    Output:       {str_output(self.c0)}
    Ctrl Monitor: {str_ctrl(self.cm0, self.fm0)}
    WiFi: {str_wifi(self.wifi_0)}

FAN 1 (kitchen hood):
    Fan Monitor:  {self.fm1.percentage:3} % = {self.fm1.rpm:4} rpm
    Output:       {str_output(self.c1)}
    Ctrl Monitor: {str_ctrl(self.cm1, self.fm1)}
    Hob2Hood:     {self.cooking_logic.value:3} %, level {self.ir.speed}, age {self.ir.speed_timestamp}
    WiFi: {str_wifi(self.wifi_1)}

"""

def run():
    import time
    s = HomeVentilationControl()
    while True:
        time.sleep_ms(1000)
        s.update()
        print(str(s))
