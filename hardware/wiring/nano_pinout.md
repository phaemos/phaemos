# Arduino Nano Secondary Node - Pin Assignment and Wiring Guide

This guide covers the wiring of the Arduino Nano that acts as a secondary environmental node. The Nano runs at 5 V
logic and 16 MHz. What the firmware does with each pin is in `firmware/arduino_nano/README.md` and that file is the
authority where the two differ.

The numbers below describe the carrier board. A build with jumper wires and no carrier board needs the same circuits
(the level shifting, the pull-ups and the dividers) built by hand.

## Pin summary

| Nano pin | Used for | Notes |
|---|---|---|
| A0 | LDR divider | 5 V, LDR, A0, 10 kohm, GND |
| A1 | FC-28 analogue output | Read only while the probe is powered |
| A4 | I2C data (SDA) | Through the board's level shifter to the air sensor |
| A5 | I2C clock (SCL) | Through the board's level shifter to the air sensor |
| D7 | Probe power | Drives the FC-28 supply when jumper JP1 is set to 2-3 |
| D0 (RX) | Serial in from the hub | Through the board's transistor level shifter |
| D1 (TX) | Serial out to the hub | Through the board's resistor divider |

## Section 1: BME280 or BMP280 - I2C connection

The air sensor sits on the 3.3 V side of the board. A4 and A5 run at 5 V on the Nano side and go through the board's
own level shifters and the pull-ups on the sensor side are on the board. Do not add pull-ups of your own on a carrier
board. The Wire library also switches on the Nano's internal pull-ups to 5 V on A4 and A5, so the breakout must not be
wired straight to the Nano pins.

| Breakout pin | Connection | Notes |
|---|---|---|
| VCC | 3.3 V | The breakout is a 3.3 V part. Do not power it from 5 V |
| GND | GND | Common ground |
| SDA | A4 through the level shifter | Pull-up to 3.3 V on the sensor side |
| SCL | A5 through the level shifter | Pull-up to 3.3 V on the sensor side |
| SDO | GND | Address 0x76. Tie to 3.3 V for 0x77 |
| CSB | 3.3 V | Selects I2C mode |

The firmware tries 0x76 first and then 0x77. The chip ID tells the parts apart (0x60 for a BME280 and 0x58 for a
BMP280). A bare jumper-wire build without the carrier board needs the same two level shifters and 3.3 V pull-ups.

## Section 2: LDR - analogue light sensor (A0)

A voltage divider of the LDR and a 10 kohm fixed resistor.

| Connection | Details |
|---|---|
| Top of divider | 5 V |
| LDR | From 5 V to A0 |
| 10 kohm resistor | From A0 to GND |

Brighter light means lower LDR resistance, a higher voltage at A0 and a higher reading (0 to 1023 against the 5 V
supply).

## Section 3: FC-28 soil moisture sensor (A1)

| FC-28 pin | Connection | Notes |
|---|---|---|
| VCC | 5 V or D7 | Chosen by solder jumper JP1: 1-2 is 5 V all the time (as made) and 2-3 is D7 |
| GND | GND | Common ground |
| AO | A1 | A lower reading means wetter soil. The firmware reports `WATER:1` below 500 |
| DO | Not connected | The comparator output is not used |

With JP1 on 2-3 the firmware drives D7 high for 50 ms before each read and low afterwards. A Nano pin is limited to
20 mA, so measure the module's current before moving the jumper. A 100 kohm pull-up on the board means an unplugged
probe reads high, which is the same as dry soil, so an unplugged probe cannot be told from a dry one and never
reports water. Calibrate on the finished board with the probe in dry air and in a glass of water.

## Section 4: Serial connection to the hub

The Nano uses its hardware UART (D1 to send and D0 to receive) at 9600 baud. It sends one checksummed line every 2
seconds and answers the hub's `PING:<n>` with `PONG:<n>`, so both directions are used.

| Nano pin | Direction | Circuit on the carrier board | Level at the far end |
|---|---|---|---|
| D1 (TX) | Nano to hub | Resistor divider: 10 kohm from D1 to the hub's receive pin and 20 kohm from there to GND | 3.33 V for a high. Source resistance about 6.7 kohm |
| D0 (RX) | Hub to Nano | Transistor level shifter: a BSS138 with 100 ohm in series and 10 kohm to 5 V. It does not invert | D0 sees 5.0 V for a high and about 0.5 V for a low |
| GND | Both | Common ground | Required |

The divider keeps the Nano's 5 V output below the 3.6 V the hub's input tolerates. The low level on D0 is about 0.5 V and
not 0 V, which is well under the 1.5 V the Nano needs to read a low. A bare jumper-wire build without the carrier board
needs the same two circuits. D0 is also driven by the Nano's USB-to-serial chip through 1 kohm and D1 feeds its input, so a ping arriving
during an upload could corrupt the upload. Whether the link can stay attached while uploading over USB is a bench check and
not a known fact: unplug it to upload.
