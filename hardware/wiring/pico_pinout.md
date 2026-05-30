# Raspberry Pi Pico 2W Ambient Node - Pin Assignment and Wiring Guide

This document covers all wiring for the Raspberry Pi Pico 2W acting as the ambient environmental sensor node in Phaemos. The Pico 2W runs at 3.3V logic and is programmed in MicroPython.

---

## Section 1: BME280 - I2C Connection

The Pico 2W uses GP4 (SDA) and GP5 (SCL) on I2C bus 0. Place 4.7k ohm pull-ups from SDA and SCL to 3.3V.

| BME280 Pin | Pico 2W Pin | Physical Pin | Notes |
|---|---|---|---|
| VCC | 3.3V | Pin 36 (3V3 OUT) | Regulated 3.3V from Pico onboard regulator |
| GND | GND | Pin 38 (GND) | Common ground |
| SDA | GP4 | Pin 6 | I2C0 SDA; 4.7k pull-up to 3.3V |
| SCL | GP5 | Pin 7 | I2C0 SCL; 4.7k pull-up to 3.3V |
| SDO | GND | GND | Sets I2C address to 0x76 |
| CSB | 3.3V | Pin 36 | Forces I2C mode |

MicroPython example:
```python
from machine import I2C, Pin
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
```

---

## Section 2: SSD1306 OLED Display - I2C (Shared Bus)

The SSD1306 shares the same I2C0 bus as the BME280. No additional pull-ups are needed as they are already fitted for the BME280.

| SSD1306 Pin | Pico 2W Pin | Physical Pin | Notes |
|---|---|---|---|
| VCC | 3.3V | Pin 36 | 3.3V from Pico |
| GND | GND | Pin 38 | Common ground |
| SDA | GP4 | Pin 6 | Shared with BME280 on I2C0 |
| SCL | GP5 | Pin 7 | Shared with BME280 on I2C0 |

I2C address is 0x3C (different from BME280 at 0x76), so both devices coexist on the same bus without conflict.

---

## Section 3: LDR - Analog Light Sensor (GP26 / ADC0)

The Pico 2W's ADC reference is 3.3V. Use GP26 which is ADC channel 0.

| Connection | Details |
|---|---|
| Top of divider | 3.3V (Pin 36) |
| LDR | From 3.3V to GP26 |
| 10k resistor | From GP26 to GND |
| Signal pin | GP26 (ADC0, physical pin 31) |

The Pico 2W ADC returns 0-65535 for 0-3.3V. Higher ambient light = lower LDR resistance = higher voltage at GP26 = higher reading.

MicroPython example:
```python
from machine import ADC, Pin
ldr = ADC(Pin(26))
raw = ldr.read_u16()  # 0-65535
voltage = raw * 3.3 / 65535
```

---

## Section 4: Power Supply

| Method | Connection | Notes |
|---|---|---|
| Micro-USB | On-board Micro-USB port | Most convenient for development; 5V from USB regulated to 3.3V onboard |
| External 5V | VSYS pin (Pin 39) | Supply 5V here when USB is not connected; do not exceed 5.5V |
| External 3.3V | 3V3 pin (Pin 36) | Only if you have a stable external 3.3V source; bypasses Pico regulator |

For the Phaemos deployment, power the Pico 2W from the main 5V rail on the VSYS pin (Pin 39). Ensure you have a common GND connection to the ESP32 board.

The onboard SMPS on the Pico 2W can supply up to 300mA on the 3.3V rail for external peripherals. The BME280 and SSD1306 combined draw well under 10mA, so headroom is ample.

---

## Section 5: Wi-Fi Antenna Clearance

The Pico 2W integrates a CYW43439 Wi-Fi and Bluetooth chip with an onboard PCB trace antenna located at the end of the board opposite the USB connector.

Key rules for the antenna area:
- Keep a clear zone of at least 15mm around the antenna end of the board free of metal objects, wire runs, and other PCB ground planes.
- Do not route copper traces or pour ground fill on your PCB directly beneath the antenna area if the Pico 2W is soldered to a carrier board.
- Avoid placing metal enclosures or mounting brackets directly above or touching the antenna end.
- For IP-rated enclosures, use a plastic (ABS or polycarbonate) enclosure. Metal enclosures significantly attenuate 2.4 GHz signals and may prevent Wi-Fi connectivity entirely.
- If signal strength is poor, orient the Pico 2W so the antenna faces toward the router with line-of-sight through the enclosure wall.
