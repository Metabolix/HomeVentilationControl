from machine import ADC
from Timestamp import Timestamp

class ControllerMonitor:
    levels_to_millivolts = ((0, 0), (100, 10000))
    unit = "%"
    def _calculate_level(self, mv):
        return mv // 100

    def __init__(self, pin):
        self.voltage_adc = ADC(pin)
        self.millivolts = None
        self.measured_level = None
        self.level = None
        self.timestamp = Timestamp(None)

    def update(self):
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

        self.millivolts = mv

        # Update timestamp when the manual control level changes.
        tmp = self._calculate_level(mv)
        if tmp != self.measured_level:
            self.measured_level = tmp
            self._level_changed()
        else:
            self.timestamp.update()
            self._level_not_changed()

    def _level_changed(self):
        self.timestamp = Timestamp()
        self.level = self.measured_level

    def _level_not_changed(self):
        pass

class LapetekVirgola5600XH(ControllerMonitor):
    # Lapetek Virgola 5600XH kitchen hood has 8 levels (above zero).
    # Internal DIP switches are used to select 4 of the modes for use.
    # Voltages (actually 12 V PWM) are between 1_100 mV and 12_000 mV.
    levels_to_millivolts = ((0, 0), (2, 2450), (5, 6720))
    unit = "/8"
    def _calculate_level(self, mv):
        return max(0, min(8, (mv + 500) // 1400))

    def _level_not_changed(self):
        # It's supposed to return to base speed after a fixed timeout, but
        # sometimes it fails to do that. Use the timestamp to fix this.
        if self.level > 1 and not self.timestamp.between(0, 5_400_000):
            self.level = 1

class VilpeECoIdeal(ControllerMonitor):
    # Vilpe ECo Ideal is configured from 0 to 100 % in steps of 10 %.
    # 10 % = 1890 mV and 100 % = 9960 mV.
    levels_to_millivolts = ((0, 0), (10, 1890), (100, 9960))
    unit = "%"
    def _calculate_level(self, mv):
        return max(0, min(100, round(10 * (mv - 940) // 897, -1)))
