# Technical details

This file contains details which may be useful to understand the code better and to implement the physical interface.

## Exhaust fans

The exhaust fans (Vilpe ECo 125P/700 Flow) have a 4-wire interface:

- blue = ground,
- red = +10 V source, max. 1.1 mA,
- yellow = control, 0–10 VDC or PWM (tolerated up to 12 V in the wiring diagram),
- white = tachy, which is normally open but connects to ground once per rotation.

The data sheet shows values between 360 RPM @ 1 V and 3069 RPM @ 10 V.

Real-world testing shows that 270 RPM is the absolute minimum for reliable operation and the maximum is around 3030–3065 RPM @ 8 V. Stable RPM changes in steps of 10–20, so most values will be seen only in passing.

## Controller 0: Whole-house ventilation

Whole-house ventilation (Vilpe ECo Ideal Wireless) is configured to 0–100 % in steps of 10 % and gives a stable 0–10 V output, where 0 % = 0 V but then 10 % = 1.89 V and 100 % = 9.96 V, increasing by 0.9 V with each 10 % step after the first.

## Controller 1: Kitchen hood

The kitchen hood (Lapetek Virgola-XH 60 / 5600XH) has 8 possible levels (excluding zero), of which exactly 4 must be chosen with the internal DIP switches. It produces +12 V PWM. Duty cycles: 0.113, 0.237, 0.362, 0.485, 0.610, 0.734, 0.858, 1.00. Voltages after an RC filter: 1.33, 2.80, 4.32, 5.76, 7.31, 8.78, 10.29, 11.95. Measured voltages drop a little when the load is connected and range from 1.1 to 11.33 volts.

## Wires

Wires from fans and controllers are connected to a spring clamp terminal block, which then fits nicely into a ribbon cable connector. Wiring is as follows:

```
[A GND]    = ground (both controller and fan)
[A in]     = 0–10 V or PWM from controller
[A out]    = 0–10 V or PWM to fan
[A tachy]  = fan tachy, normally open, connects to ground once per rotation
[A 10V]    = 10 V from the fan, used for generating PWM output
[B 10V]    | Mirrored for the second fan and controller;
[B tachy]  | reversing the connector only swaps places.
[B out]    | Possible fail-safe:
[B in]     | Connect [in] and [out].
[B GND]    |
```

## Circuit

Disclaimer: The following components have been selected based on what was on hand at the moment. In many cases, a better option might exist.

The circuit needs 1 PWM output, 1 ADC input and 3 digital inputs, and coincidentally, the Raspberry Pi Pico (W) has just enough pins to fit two of these on the same side.

### Input voltage measurement

Connect input to ADC through a voltage divider with an integrated RC filter.

12 V * 324k / (324k + 324k + 536k) = 3.28 V, acceptable ADC voltage.

324 kOhm * 2.2 uF * 5 = 3.6 s, acceptable settle time.

```
┌───[R = 324k]──┬──[R = 324k]──[R = 536k]──[in / controller]
├─[C = 2.2 uF]──┴──[ADC pin]
└─[GND]
```

### Output PWM generation

Use +10 V from the fan to provide the PWM output voltage and switch it with an opto-isolator.

TLP521 is not optimal for this use case but provides acceptable results with a 6.8 kOhm resistor on the input side and 16.2 kOhm on the output side. (Testing shows that 12 kOhm would be even better on the input side.)

```
[PWM pin]──[R = 6.8k]──[TLP521]──[R = 16.2k]──[10V]
                [GND]──┘      └──[PWM 10V out]
```

### Switches to choose output

Connect the original controller and the PWM output to the fan through switches (on/off and own/original).

```
[PWM 10V out]──────[switch_own]──[switch_on]──[fan]
[in / controller]──┘      [GND]──┘
```

Use 2-pole switches, and use the second pole to monitor switch state.

```
[nothing]──[switch]──[switch state pin with pull-up]
    [GND]──┘
```

### Tachy / RPM

Monitor RPM through the tachy wire. Use an RC filter to get rid of some noise. (Warning: This particular filter is almost too effective!)

```
[tachy pin with pull-up]──[R = 693 Ω]──┬──[tachy / fan]──[GND]
                 [GND]──[C = 0.33 uF]──┘              └──[open]
```

### Circuit diagram

Open [circuit.txt](circuit.txt) with [CircuitJS1](https://github.com/pfalstad/circuitjs1) for a better schematic.

### Other components

Wiring the IR sensor and DHT22 sensor is trivial and is not covered in this documentation.
