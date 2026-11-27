# Parts inventory

The parts we hold for the four sensor nodes and the parts we still need. Check here before ordering anything.

- [In stock](#in-stock)
- [Still to source](#still-to-source)
- [Enclosures](#enclosures)
- [Notes](#notes)

## In stock

### Microcontroller boards

| Part | Qty | Notes |
| --- | --- | --- |
| ESP32 development board (Wi-Fi and Bluetooth) | 3 | Primary gateway node |
| STM32F411CEU6 Black Pill (USB-C, pre-soldered) | 1 | Vibration and FFT node |
| STM32F103C8T6 Blue Pill with ST-Link V2 | 2 | Spares. The F411 is preferred |
| STM32F407VET6 development board | 1 | Not in the current four-node design |
| Arduino Nano (pre-soldered headers) | 2 | Auxiliary sensor node |
| Arduino Mega R3 (ATmega2560) | 1 | Spare |
| Raspberry Pi Pico 2W (RP2350) | 1 | Ambient environment node, MicroPython |
| ATmega644P (DIP) | 2 | Not in use. Needs its own circuit |

### Sensors

| Part | Qty | Interface | Notes |
| --- | --- | --- | --- |
| MPU6050 (GY-521) accelerometer and gyroscope | 3 | I2C 0x68 | Vibration |
| BMP280 temperature and pressure | 5 | I2C | No humidity output. See [Notes](#notes) |
| MAX4466 microphone amplifier (GY-MAX4466) | 2 | Analogue | Sound level |
| DS18B20 waterproof temperature probe | 2 | OneWire | Needs a 4.7 kohm pull-up |
| VL53L0X time-of-flight distance | 2 | I2C 0x29 | |
| MLX90614 (GY-906) infrared thermometer | 1 | I2C 0x5A | Non-contact surface temperature |
| AS5600 magnetic rotary encoder | 2 | I2C 0x36 | Shaft speed and angle. Needs a diametric magnet |
| MQ-2 gas sensor | 1 | Analogue | 5 V heater, two to three minutes to warm up |
| INA219 current and voltage | 2 | I2C 0x40 | Power monitoring |
| FC-28 soil moisture | 2 | Analogue | |

### Displays and outputs

| Part | Qty | Notes |
| --- | --- | --- |
| SSD1306 0.96 inch OLED, 128 by 64, I2C | 3 or more | Node status |
| WS2812B addressable LED strip, 1 m, 60 LEDs, 5 V | 1 | Status indicator |
| Passive buzzer, 12 by 8.5 mm | 10 | Alarm output |
| Speaker, 3 W, 8 ohm | 1 | Audible alerts |
| Four-channel relay module, 5 V, optocoupled | 1 | Switched outputs |

### Power and wiring

| Part | Qty | Notes |
| --- | --- | --- |
| 12 V 2 A adapter, 5.5 by 2.1 mm barrel | 1 | |
| 9 V adapter, barrel | 1 | |
| DC jacks, 5.5 by 2.1 mm, male and female | 6 pairs | |
| LM2596 adjustable buck converter | 5 | |
| AMS1117 3.3 V regulator module | 1 | |
| 22 AWG stranded wire, red and black | 20 m | Tinned copper |
| Inline fuse holders with 5 by 20 mm fuses | 5 holders | Assorted ratings |
| 1N4001 to 1N4007 rectifier diodes | Assortment | |
| Heat shrink tubing, 12 sizes | Kit | |
| Insulating tape | 1 roll | |

### Prototyping and connectors

| Part | Qty | Notes |
| --- | --- | --- |
| Solderless breadboard, 3220 points | 1 | |
| Breadboard kit with jumper wires | 1 kit | Male and female leads |
| Component kit, 37 values, 480 pieces | 1 kit | Check it before ordering passives |
| Quartz crystal kit, 12 values | 1 kit | |
| Arduino Mega starter kit | 1 kit | Check it for sensors and passives before ordering |
| Tactile button assortment | 250 | Momentary |
| Latching toggle switch, SPST, 15 A | 1 | |
| Screw terminal blocks, 5.08 mm, 2 to 4 pin | 25 | Pluggable |
| JST-XH connectors, 2.54 mm, 2 to 6 pin | Kit | |

### Mechanical

| Part | Qty | Notes |
| --- | --- | --- |
| IP65 junction box, clear lid | 1 | Temporary housing while prototyping |
| Ventilation mesh panels, 10 by 10 cm | Pack | |
| M3 nylon standoff kit | 1 kit | |

### Tools

| Part | Qty | Notes |
| --- | --- | --- |
| ST-Link V2 SWD programmer | 1 | For the STM32 boards |
| AVR ISP mkII compatible programmer | 1 | For bare AVR chips |
| Digital multimeter | 1 | Voltage, current, resistance, continuity |

## Still to source

Check the component kits above first. Most of these may already be there.

| Part | Qty | Notes |
| --- | --- | --- |
| BSS138 logic level shifter, 3.3 V to 5 V | 1 | Into the Nano's D0 from the ESP32. Out of the Nano's D1 a 10 kohm over 20 kohm divider is enough (3.33 V at the ESP32) |
| AS5600 magnet, diametrically magnetised | 1 | An axial magnet will not work with the encoder |
| LDR (GL5528 or equivalent) | 5 | Light level, with a 10 kohm divider |
| 10 kohm resistor, 1/4 W | 20 | LDR dividers and general use |
| 4.7 kohm resistor, 1/4 W | 10 | I2C and DS18B20 pull-ups |
| NPN transistor, BC547 or 2N2222 (TO-92) | 10 | |
| N-channel MOSFET, 2N7000 or BS170 (TO-92) | 5 | Logic-level gate |
| LEDs, 5 mm, red, green and amber | 10 each | |

## Enclosures

Printed cases for the Nano, Pico and Black Pill nodes are designed. The ESP32 board's housing waits until the carrier boards are made and tested, so it fits the board rather than the breadboard layout.

| Option | Notes |
| --- | --- |
| PLA or PETG, 3D printed | Cheapest. Used for the designed cases |
| Acrylic sheet, laser cut | A sandwich design that suits demonstrations |
| Aluminium, CNC milled | The most durable finish and the most expensive |

## Notes

- The firmware accepts a BME280 or a BMP280. Only the BME280 reports humidity, so a node that needs humidity needs a BME280 in place of the BMP280s above.
- The AS5600 magnet must be diametrically magnetised, not axial.
- Label each part with its name.
