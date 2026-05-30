# Arduino Nano Secondary Node - Pin Assignment and Wiring Guide

This document covers all wiring for the Arduino Nano acting as a secondary environmental sensor node in Phaemos. The Nano runs at 5V logic and 16 MHz.

---

## Section 1: BME280 - I2C Connection

The Nano uses A4 for SDA and A5 for SCL on the hardware I2C bus (Wire library). Most BME280 breakouts include an onboard AMS1117-3.3 regulator so you can power them from the Nano's 3.3V pin or from 5V if the breakout has its own regulator.

| BME280 Pin | Nano Pin | Notes |
|---|---|---|
| VCC | 3.3V (pin 17) | Use the Nano's regulated 3.3V output; do not exceed 3.6V |
| GND | GND | Common ground |
| SDA | A4 | Hardware I2C SDA; place 4.7k pull-up to 3.3V |
| SCL | A5 | Hardware I2C SCL; place 4.7k pull-up to 3.3V |
| SDO (addr) | GND | Sets I2C address to 0x76; tie to 3.3V for 0x77 |
| CSB | 3.3V | Forces I2C mode (active HIGH) |

---

## Section 2: LDR - Analog Light Sensor (A0)

A simple voltage divider using the LDR and a 10k fixed resistor.

| Connection | Details |
|---|---|
| Top of divider | 5V (Nano Vcc) |
| LDR | From 5V to A0 |
| 10k resistor | From A0 to GND |
| Signal pin | A0 |

Higher ambient light = lower LDR resistance = higher voltage at A0 = higher ADC reading (out of 1023 at 5V reference).
Darker conditions = higher LDR resistance = lower voltage = lower ADC reading.

The Nano ADC is referenced to 5V by default. analogRead(A0) returns 0-1023 mapping to 0-5V.

---

## Section 3: FC-28 Soil Moisture Sensor (A1)

| FC-28 Pin | Nano Pin | Notes |
|---|---|---|
| VCC | 5V or 3.3V | 5V gives better signal range; 3.3V reduces corrosion on probes |
| GND | GND | Common ground |
| AO (analog out) | A1 | Reads as 0-1023; lower reading = more moisture |
| DO (digital out) | Not connected | Threshold comparator output; not needed for analog mode |

Calibrate by taking a reading in dry air (maximum value, around 1023) and submerged in water (minimum value, around 300-400). Map the range in firmware.

---

## Section 4: Serial Connection to ESP32

The Nano uses its hardware UART (TX=D1, RX=D0) to send data to the ESP32 UART1 (RX=GPIO16, TX=GPIO17) at 9600 baud.

| Nano Pin | Level Shifter | ESP32 Pin | Direction | Notes |
|---|---|---|---|---|
| D1 (TX) | 5V side IN -> 3.3V side OUT | GPIO16 (UART1 RX) | Nano -> ESP32 | See voltage divider details below |
| D0 (RX) | 3.3V side IN -> 5V side OUT | GPIO17 (UART1 TX) | ESP32 -> Nano | ESP32 outputs 3.3V which Nano reads as HIGH correctly |
| GND | GND | GND | - | Common ground required |

**Voltage divider warning:** The Arduino Nano TX pin (D1) outputs 5V logic. The ESP32 GPIO16 input is 3.3V tolerant with a maximum of 3.6V. Connecting 5V directly will damage the ESP32 over time.

Use a simple resistor voltage divider on the Nano TX line:
- 10k ohm resistor from Nano D1 to the junction point
- 20k ohm resistor from the junction point to GND
- Junction point connects to ESP32 GPIO16

This divides 5V to: 5V x 20k / (10k + 20k) = 3.33V, which is within the ESP32 safe input range.

The return path (ESP32 TX to Nano RX) does not need a level shifter because the Nano recognises 3.3V as a valid HIGH on a 5V TTL input.
