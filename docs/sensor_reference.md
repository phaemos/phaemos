# Sensor Reference

This document lists every sensor used across all four Phaemos nodes, with interface details, libraries, measurement ranges, and datasheet links.

---

## ESP32 Primary Node Sensors

| Sensor | Model | Interface | I2C Address | Library (Arduino IDE) | Measures | Units | Typical Range | Datasheet |
|---|---|---|---|---|---|---|---|---|
| Barometric pressure / humidity / temperature | BME280 | I2C | 0x76 | Adafruit BME280 | Temperature, humidity, pressure | degC, %, hPa | -40 to 85 degC / 0-100% RH / 300-1100 hPa | [link to datasheet] |
| Accelerometer / gyroscope | MPU6050 | I2C | 0x68 | Adafruit MPU6050 or I2Cdev | Acceleration (3-axis), angular rate (3-axis), temperature | m/s^2, deg/s | +/-2g to +/-16g (accel) / +/-250 to +/-2000 deg/s (gyro) | [link to datasheet] |
| Current / power monitor | INA219 | I2C | 0x40 | Adafruit INA219 | Bus voltage, shunt current, power | V, mA, mW | 0-26V bus / 0-3.2A (with 0.1 ohm shunt) | [link to datasheet] |
| Microphone (sound level) | MAX4466 | Analog | n/a | n/a (analogRead) | Sound pressure level (amplified) | ADC counts (0-4095) | Dependent on gain pot setting | [link to datasheet] |
| Infrared thermometer | MLX90614 | I2C | 0x5A | Adafruit MLX90614 | Object temperature, ambient temperature | degC | -70 to 380 degC (object) | [link to datasheet] |
| Time-of-flight distance | VL53L0X | I2C | 0x29 | Adafruit VL53L0X | Distance to object | mm | 30-1200 mm (up to 2000 mm in long range mode) | [link to datasheet] |
| Gas / smoke sensor | MQ-2 | Analog + Digital | n/a | n/a (analogRead + digitalRead) | LPG, propane, methane, smoke concentration | ppm (calibrated) / raw ADC | 300-10000 ppm (varies by gas) | [link to datasheet] |
| Magnetic rotary encoder | AS5600 | I2C | 0x36 | AS5600 library (RobTillaart) | Shaft angle, calculated RPM | degrees (0-360), RPM | 0-360 degrees continuous | [link to datasheet] |
| Light-dependent resistor | LDR (GL5528 or similar) | Analog | n/a | n/a (analogRead) | Ambient light level | ADC counts (0-4095) | ~10 lux to ~100 klux (resistance 1M to 10k ohm) | [link to datasheet] |
| Contact temperature probe | DS18B20 | OneWire (GPIO4) | n/a | DallasTemperature + OneWire | Temperature | degC | -55 to 125 degC | [link to datasheet] |
| Soil / water moisture | FC-28 | Analog | n/a | n/a (analogRead) | Moisture level, water presence | ADC counts (0-4095), boolean | Dry ~1023 / Wet ~300 (at 3.3V) | [link to datasheet] |

---

## STM32 Black Pill Vibration Node Sensors

| Sensor | Model | Interface | I2C Address | Library (STM32CubeIDE HAL) | Measures | Units | Typical Range | Datasheet |
|---|---|---|---|---|---|---|---|---|
| Accelerometer / gyroscope | MPU6050 | I2C1 (PB6/PB7) | 0x68 | Custom HAL_I2C driver or I2Cdev port | Acceleration (3-axis), angular rate (3-axis); FFT processed to vib_magnitude and fft_peak_hz | m/s^2, deg/s, Hz | +/-2g to +/-16g / +/-250 to +/-2000 deg/s | [link to datasheet] |

---

## Arduino Nano Secondary Node Sensors

| Sensor | Model | Interface | I2C Address | Library (Arduino IDE) | Measures | Units | Typical Range | Datasheet |
|---|---|---|---|---|---|---|---|---|
| Barometric pressure / humidity / temperature | BME280 | I2C (A4/A5) | 0x76 | Adafruit BME280 | Temperature, humidity, pressure | degC, %, hPa | -40 to 85 degC / 0-100% RH / 300-1100 hPa | [link to datasheet] |
| Light-dependent resistor | LDR (GL5528 or similar) | Analog (A0) | n/a | n/a (analogRead) | Ambient light level | ADC counts (0-1023 at 10-bit) | ~10 lux to ~100 klux | [link to datasheet] |
| Soil / water moisture | FC-28 | Analog (A1) | n/a | n/a (analogRead) | Moisture level | ADC counts (0-1023 at 10-bit) | Dry ~1023 / Wet ~300 | [link to datasheet] |

---

## Raspberry Pi Pico 2W Ambient Node Sensors

| Sensor | Model | Interface | I2C Address | Library (MicroPython) | Measures | Units | Typical Range | Datasheet |
|---|---|---|---|---|---|---|---|---|
| Barometric pressure / humidity / temperature | BME280 | I2C0 (GP4/GP5) | 0x76 | micropython-bme280 (unofficial) | Temperature, humidity, pressure | degC, %, hPa | -40 to 85 degC / 0-100% RH / 300-1100 hPa | [link to datasheet] |
| Light-dependent resistor | LDR (GL5528 or similar) | ADC (GP26/ADC0) | n/a | machine.ADC | Ambient light level | ADC counts (0-65535 at 16-bit) | ~10 lux to ~100 klux | [link to datasheet] |
| OLED display | SSD1306 | I2C0 (GP4/GP5) | 0x3C | ssd1306 MicroPython driver | n/a (output device, not a sensor) | n/a | 128x64 pixel display | [link to datasheet] |

---

## I2C Bus Address Reference and Conflict Resolution

The following I2C addresses are used across the Phaemos nodes:

| Address | Device | Node |
|---|---|---|
| 0x29 | VL53L0X | ESP32 |
| 0x36 | AS5600 | ESP32 |
| 0x3C | SSD1306 OLED | ESP32, Pico 2W |
| 0x40 | INA219 | ESP32 |
| 0x5A | MLX90614 | ESP32 |
| 0x68 | MPU6050 | ESP32, STM32 |
| 0x76 | BME280 | ESP32, Nano, Pico 2W |

**Handling address conflicts on the same bus:**

Each node has its own I2C bus, so there is no conflict between nodes. However, within the ESP32 node, if a second BME280 were ever needed (for example to measure temperature at two different points), the address can be changed:

- BME280: pull the SDO pin HIGH (to 3.3V) to change address from 0x76 to 0x77. You can run one BME280 at 0x76 and one at 0x77 on the same bus.
- MPU6050: pull the AD0 pin HIGH to change address from 0x68 to 0x69.
- INA219: the A0 and A1 address pins can be tied to GND or VCC to select one of four addresses (0x40, 0x41, 0x44, 0x45), allowing up to four INA219s on one bus.
- VL53L0X: the address is fixed at 0x29 in hardware but can be reassigned in firmware at boot time using the XSHUT pin. Bring each VL53L0X online one at a time via XSHUT and assign a unique address before releasing the next one.
- AS5600 and MLX90614 have fixed addresses and only one of each can be used per I2C bus.
