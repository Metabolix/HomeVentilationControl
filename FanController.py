from machine import Pin, ADC
from Timestamp import Timestamp

class FanController:
    def __init__(
        self, *,
        pin_switch_on = None, pin_switch_own = None,
        pin_voltage_adc = None, ctrl_translate = None,
    ):
        self.pin_switch_on = pin_switch_on is not None and Pin(pin_switch_on, Pin.IN, pull = Pin.PULL_UP)
        self.pin_switch_own = pin_switch_own is not None and Pin(pin_switch_own, Pin.IN, pull = Pin.PULL_UP)

        self.voltage_adc = pin_voltage_adc is not None and ADC(pin_voltage_adc)
        self.ctrl_translate = ctrl_translate or self.VilpeECoFlow125P700
        self.ctrl_level = (0, "?")
        self.ctrl_timestamp = Timestamp(None)
        self.ctrl_rpm = 0

    def update(self):
        self.switch_on = 1 - self.pin_switch_on() if self.pin_switch_on else 0
        self.switch_own = 1 - self.pin_switch_own() if self.pin_switch_own else 0
        self._update_ctrl()

    def _update_ctrl(self):
        mv = 0
        if self.voltage_adc:
            # Take 16 samples to avoid ADC fluctuation. 12-bit ADC, max 0xfff0.
            adc_u16 = 0
            for i in range(16):
                adc_u16 += self.voltage_adc.read_u16()
            adc_u16 = adc_u16 >> 4

            # Voltage divider: GND, 324k, ADC, 324k, 536k, real_volts.
            # 12-bit ADC max = 3.3 V / 0xfff0.
            # Theoretical value:
            #mv = adc_u16 * (324 * 2 + 536) / 324 * 3300 / 0xfff0
            # Reality: Adjusted with multimeter measurements.
            #mv = (adc_u16 - 145) * 0.181941
            mv = max(0, (adc_u16 - 145) * 9831 // 54034)

        self.ctrl_millivolts = mv
        self.ctrl_rpm = self.VilpeECoFlow125P700(mv, self.ctrl_rpm)[0]

        # Update timestamp when the manual control level changes.
        l = self.ctrl_translate(self.ctrl_millivolts)
        if l != self.ctrl_level:
            self.ctrl_level = l
            self.ctrl_timestamp = Timestamp()
        else:
            self.ctrl_timestamp.update()

    @classmethod
    def LapetekVirgola5600XH(self, mv):
        # Lapetek Virgola 5600XH kitchen hood has 8 levels (above zero).
        # Internal DIP switches are used to select 4 of the modes for use.
        # Voltages (actually 12 V PWM) are between 1_100 mV and 12_000 mV.
        return (max(0, min(8, (mv + 500) // 1400)), "DIP")

    @classmethod
    def VilpeECoIdeal(self, mv):
        # Vilpe ECo Ideal is configured from 0 to 100 % in steps of 10 %.
        # 10 % = 1890 mV and 100 % = 9960 mV.
        return (max(0, min(100, round(10 * (mv - 940) // 897, -1))), "%")

    @classmethod
    def VilpeECoFlow125P700(self, mv, old_rpm = 0):
        # Vilpe ECo Flow rpm rises linearly with voltage between lowes and highest.
        # 0 rpm = 0 mV and 3030 rpm = 7750 mV, tends to stop below 270-330 rpm.
        rpm = 3030 * mv // 7750
        if abs(rpm - old_rpm) < 10:
            return (old_rpm, "rpm")
        return (rpm > 270 and max(300, min(3030, rpm)) or 0, "rpm")
