# Home Ventilation Control

This project is about controlling exhaust fans (whole-house ventilation and the kitchen hood) with a Raspberry Pi Pico W.

This project allows monitoring and intercepting the original fan controllers, receiving Hob2Hood IR codes (sent by the stove to automatically control the kitchen hood), monitoring the fan speeds and also customizing fan speeds over Wi-Fi. As a failsafe, if no other information is provided, the fans will follow the original controller settings or custom levels set in the configuration file.

The Wi-Fi interface allows any further smart features to be implemented with other hardware. (Such features could include ventilation based on time, indoor and outdoor temperatures, air quality and so on.)

## Features

- Monitor the original control voltage (x2).
    - Convert to the original controller setting.
    - Convert to a user-defined fan speed.
- Monitor the IR sensor (Hob2Hood).
    - Convert to a user-defined fan speed.
    - Only use this speed if it's higher than from the controller.
- Monitor fan speed.
    - Convert RPM to percentage based on fan model.
- Control a fan.
    - Monitor the effect, fine tune output.
    - Learn new data points and use interpolation to optimize output.
- Monitor temperature and relative humidity.
- Wi-Fi interface (HTTP and UDP) for monitoring and controlling.
    - Define a mapping from the calculated speed to a final value.
    - HTTP implemented with [MicroPython-WebMain](https://github.com/Metabolix/MicroPython-WebMain).
    - UDP implemented for [Home Assistant integration](https://github.com/Metabolix/HomeVentilationControl-HASS).

## Hob2Hood IR

Hob2Hood IR control codes are 25 bits long, simple on-off, 733 µs/bit, and apparently 38 kHz modulation. Codes are repeated 3 times. See [Hob2Hood.py](Hob2Hood.py) for the codes.

## Technical overview

The fans are controlled with 0–10 VDC or PWM. The fans provide +10 VDC which can be used to generate a PWM signal. Fan speed (RPM) is measured from a tachy wire which connects to ground once per rotation.

How to interface with a controller and a fan:

- Convert a PWM signal into a voltage with a RC filter.
- Drop the voltage under 3.3 V with a voltage divider.
- Read the voltage with an ADC input.
- Read the tachy wire through a simple input with a pull-up resistor.
- Read the IR codes and any other relevant input.
- Convert all this data into a suitable PWM value.
- Generate a PWM signal for output.
- Amplify to +10 VDC with a transistor (or opto-isolator).
- Connect +10 VDC PWM output to the fan.

See [DETAILS](DETAILS.md) for more technical information.

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE) for more details.
