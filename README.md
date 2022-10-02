# Home Ventilation Control

This project is about controlling exhaust fans (whole-house ventilation and the kitchen hood) with a Raspberry Pi Pico W.

For the whole-house ventilation, the aim is to implement remote control with WiFi, so that any further smart features can be implemented with other hardware. (Such features could include ventilation based on time, indoor and outdoor temperatures, air quality and so on.)

For the kitchen hood, the aim is to customize fan speed settings and to receive Hob2Hood IR codes sent by the stove to automatically control ventilation.

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

## Web interface

Web interface is implemented using [MicroPython-WebMain](https://github.com/Metabolix/MicroPython-WebMain).

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE) for more details.
