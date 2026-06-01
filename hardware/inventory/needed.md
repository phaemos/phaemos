# What We Still Need

Everything in this file is either on order (not yet arrived), at the Aston lab (collect from Richard), or not yet purchased.

---

## Amazon Order Arriving (May/June 2026) - £133.09

Ordered. Just waiting for delivery.

| Component | Qty | Delivery | Notes |
|---|---|---|---|
| On-Off Latching Toggle Switch SPST 15A 250V | 1 | Tomorrow | 6.3mm quick connect terminals |
| Micro Switch Tactile Button Kit 250-pc (assorted) | 1 | Tomorrow | Momentary, various sizes |
| MPU6050 GY-521 accel/gyro (3-pack) | 3 | Tomorrow | I2C 0x68 - vibration sensing |
| BMP280 temp/pressure sensor (5-pack) | 5 | Tomorrow | **No humidity output** - check if acceptable vs BME280 |
| GY-MAX4466 microphone amplifier (2-pack) | 2 | Tomorrow | Analog out, sound level monitoring |
| DS18B20 waterproof temperature probe (2-pack) | 2 | Tomorrow | OneWire, needs 4.7k pull-up resistor |
| VL53L0X ToF distance sensor (2-pack) | 2 | Sat 30 May | I2C 0x29 |
| MLX90614 GY-906 IR thermometer (pre-soldered) | 1 | Tomorrow | I2C 0x5A - non-contact surface temperature |
| AS5600 magnetic rotary encoder (2-pack) | 2 | Tomorrow | I2C 0x36 - shaft RPM and angle |
| Passive Buzzer 12x8.5mm (10-pack) | 10 | Sat 30 May | DC 1.5-5V alarm output |
| MQ-2 gas sensor module | 1 | 2-3 June | 5V heater, needs 2-3 min warm-up |
| WS2812B RGB LED strip 1m 60 LED/m 5V | 1 | Tomorrow | Addressable status indicator |
| Rectifier Diode Kit 1N4001-1N4007 300-pc | 1 | Tomorrow | Assortment |
| AMS1117 3.3V regulator module | 1 | 4-6 June | Step-down voltage regulator |
| LM2596 buck converter (5-pack) | 5 | Tomorrow | Adjustable step-down DC-DC |
| 4-channel relay module 5V (with optocoupler) | 1 | Tomorrow | Switching outputs |
| PCB screw terminal blocks 5.08mm 25-set | 25 | Tomorrow | 2/3/4 pin pluggable |
| JST-XH connector kit 2.54mm 460-pc | 1 | Tomorrow | 2-6 pin housing |
| INA219 current/voltage sensor (2-pack) | 2 | 3 June | I2C 0x40 - power monitoring |
| FC-28 soil/moisture sensor (2-pack) | 2 | 22-27 June | **Long delivery** - find Prime alternative if needed sooner |

---

## Collect from Aston Lab (Richard)

Check the BOJACK 37-values kit and ELEGOO Mega Starter Kit first - they likely contain some of these. Only collect what is genuinely missing.

| Component | Qty | Notes |
|---|---|---|
| LDR (GL5528 or equivalent) | 5 | Light dependent resistor |
| 10k resistor 1/4W through hole | 20 | LDR voltage divider + general use |
| 4.7k resistor 1/4W through hole | 10 | I2C pull-ups + DS18B20 pull-up |
| NPN transistor BC547 or 2N2222 | 10 | TO-92 package |
| MOSFET N-channel 2N7000 or BS170 | 5 | TO-92, logic level gate |
| Tactile push button 6x6mm 4-pin | 20 | Momentary, through hole |
| LED red 5mm through hole | 10 | |
| LED green 5mm through hole | 10 | |
| LED amber 5mm through hole | 10 | |

---

## Still to Buy (Not Yet Ordered)

| Component | Qty | Approx cost | Notes |
|---|---|---|---|
| Logic level shifter 3.3V to 5V | 2 | ~£3 | Nano UART (5V) to ESP32 UART (3.3V) - required for inter-board comms |
| AS5600 diametrically magnetised magnet | 1 | ~£2-5 | **Must be diametric, not axial** - shaft angle sensing will not work without the correct magnet type |

---

## Enclosure Materials (Phase 2 Only)

Do not buy anything here until all 4 nodes are tested and working on breadboard. The sensor layout must be locked before designing housing.

| Option | Notes |
|---|---|
| PLA/PETG filament | 3D print in Aston lab - cheapest |
| Acrylic sheet | Laser cut sandwich design - good for demos |
| Aluminium stock | CNC milled - professional finish, expensive |

Decision depends on whether the project moves to a custom PCB. If yes, design the PCB first - the enclosure should fit the PCB, not the breadboard layout.
