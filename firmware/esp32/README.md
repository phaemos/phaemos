# PHAEMOS ESP32 Hub - Wiring Reference

This document covers every sensor and output on the ESP32 hub node introduced in the v2 hardware spec (May 2026). Pin numbers refer to ESP32 GPIO unless otherwise stated.

---

## Power Infrastructure

```
12 V DC supply
  |
  +-- LM2596 buck converter --> 5 V rail
        |
        +-- AMS1117-3.3 LDO --> 3.3 V rail
        |
        +-- 5 V peripherals (NeoPixel strip, relay module VCC, OLED VCC)

3.3 V rail feeds:
  - ESP32 VCC
  - All I2C sensors (BME280, MPU6050, INA219, MLX90614, VL53L0X, AS5600)
  - MQ2 logic pin (VCC = 5 V for heater, but digital output is 3.3 V compatible)
```

The LM2596 handles the bulk step-down from the 12 V supply so the AMS1117 dissipates minimal heat. The AMS1117 is used for the 3.3 V rail because its 800 mA output current comfortably covers all I2C sensors and the ESP32.

---

## I2C Bus (shared across all I2C sensors)

| Signal | ESP32 GPIO |
|--------|-----------|
| SDA    | GPIO 21   |
| SCL    | GPIO 22   |

All I2C sensors share one bus. Each has a unique hardware address (see `config.h`). A 4.7 kohm pull-up to 3.3 V on both SDA and SCL is required.

---

## Sensor Wiring Tables

### 1. BME280 - Temperature / Humidity / Pressure

| Sensor Pin | ESP32 GPIO | Notes                                      |
|------------|------------|--------------------------------------------|
| VCC        | 3.3 V      | Do not use 5 V - maximum rated is 3.6 V    |
| GND        | GND        |                                            |
| SDA        | GPIO 21    | Shared I2C bus                             |
| SCL        | GPIO 22    | Shared I2C bus                             |
| SDO        | GND        | Sets I2C address to 0x76                   |

### 2. MPU6050 - 6-Axis IMU (Accelerometer + Gyroscope)

| Sensor Pin | ESP32 GPIO | Notes                                      |
|------------|------------|--------------------------------------------|
| VCC        | 3.3 V      |                                            |
| GND        | GND        |                                            |
| SDA        | GPIO 21    | Shared I2C bus                             |
| SCL        | GPIO 22    | Shared I2C bus                             |
| AD0        | GND        | Sets I2C address to 0x68                   |
| INT        | Not connected | Interrupt not used in v2 polling mode   |

### 3. INA219 - Current / Voltage Monitor

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      |                                                    |
| GND        | GND        |                                                    |
| SDA        | GPIO 21    | Shared I2C bus                                     |
| SCL        | GPIO 22    | Shared I2C bus                                     |
| VIN+       | Load +     | Connect between supply and load positive terminal  |
| VIN-       | Load -     | Connect to load positive terminal (after shunt)    |

A0, A1 tied to GND for address 0x40.

### 4. MLX90614 - Infrared Non-Contact Thermometer

| Sensor Pin | ESP32 GPIO | Notes                                          |
|------------|------------|------------------------------------------------|
| VCC        | 3.3 V      |                                                |
| GND        | GND        |                                                |
| SDA        | GPIO 21    | Shared I2C bus - requires 4.7 kohm pull-up     |
| SCL        | GPIO 22    | Shared I2C bus - requires 4.7 kohm pull-up     |

Address 0x5A (factory default, not configurable without reprogramming).

### 5. VL53L0X - Time-of-Flight Distance Sensor

| Sensor Pin | ESP32 GPIO | Notes                                          |
|------------|------------|------------------------------------------------|
| VCC        | 3.3 V      |                                                |
| GND        | GND        |                                                |
| SDA        | GPIO 21    | Shared I2C bus                                 |
| SCL        | GPIO 22    | Shared I2C bus                                 |
| XSHUT      | Not connected | Pulled high internally - sensor always on   |
| GPIO1      | Not connected | Data-ready interrupt not used in v2         |

Address 0x29 (default).

### 6. AS5600 - Magnetic Rotary Position Encoder

| Sensor Pin | ESP32 GPIO | Notes                                          |
|------------|------------|------------------------------------------------|
| VCC        | 3.3 V      |                                                |
| GND        | GND        |                                                |
| SDA        | GPIO 21    | Shared I2C bus                                 |
| SCL        | GPIO 22    | Shared I2C bus                                 |
| DIR        | GND        | CW positive rotation                           |

Address 0x36 (fixed, cannot be changed).

### 7. MQ2 - Gas / Smoke Sensor

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 5 V        | Heater requires 5 V - do not use 3.3 V              |
| GND        | GND        |                                                    |
| AO         | GPIO 34    | Analog output - GPIO34 is input-only, ADC1 ch6     |
| DO         | GPIO 35    | Digital threshold output - GPIO35 is input-only    |

Allow 30 s warm-up time after power-on before readings are stable.

### 8. FC-28 - Soil Moisture / Water Detection

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      |                                                    |
| GND        | GND        |                                                    |
| AO         | GPIO 36    | Analog output (GPIO36 = VP, input-only, ADC1 ch0)  |
| DO         | Not used   | Threshold set by onboard potentiometer             |

### 9. DS18B20 - 1-Wire Temperature Sensor

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      | Parasitic power mode not used                      |
| GND        | GND        |                                                    |
| DATA       | GPIO 4     | Requires 4.7 kohm pull-up to 3.3 V on DATA line   |

### 10. LDR - Light Dependent Resistor (v2)

| Component  | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| LDR top    | 3.3 V      | One leg of LDR connected to 3.3 V                  |
| LDR bottom | GPIO 33    | Other leg of LDR to GPIO33 and 10 kohm to GND     |

GPIO33 is ADC1 ch5. A 10 kohm resistor to GND forms a voltage divider with the LDR.

### 11. MAX4466 - Microphone / Sound Level

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      |                                                    |
| GND        | GND        |                                                    |
| OUT        | GPIO 32    | Analog audio output - GPIO32 ADC1 ch4              |

Gain is set by the onboard potentiometer. Centre output at 1.65 V (VCC/2).

---

## Output Wiring Tables

### Buzzer (passive)

| Component   | ESP32 GPIO | Notes                                              |
|-------------|------------|----------------------------------------------------|
| Buzzer +    | GPIO 25    | Driven by tone() at 2000 Hz                        |
| Buzzer -    | GND        |                                                    |

Use a 100 ohm series resistor to limit drive current.

### NeoPixel RGB LED Strip (WS2812B)

| Strip Pin | ESP32 GPIO | Notes                                               |
|-----------|------------|-----------------------------------------------------|
| VCC       | 5 V        | WS2812B requires 5 V - do not use 3.3 V             |
| GND       | GND        |                                                     |
| DIN       | GPIO 26    | Add a 330 ohm series resistor on the data line      |

RGB_LED_COUNT = 30 (config.h). At full white each pixel draws ~60 mA; total strip max is 1.8 A at 5 V - size your LM2596 output accordingly.

### 4-Channel Relay Module (active-low)

| Relay     | ESP32 GPIO | Notes                                               |
|-----------|------------|-----------------------------------------------------|
| IN1 (CH1) | GPIO 13    | LOW = relay on (coil energised), HIGH = relay off   |
| IN2 (CH2) | GPIO 12    |                                                     |
| IN3 (CH3) | GPIO 14    |                                                     |
| IN4 (CH4) | GPIO 27    |                                                     |
| VCC       | 5 V        | Relay coil supply                                   |
| GND       | GND        |                                                     |
| JD-VCC    | 5 V        | Optocoupler supply - separate from VCC for isolation|

CH1 is wired to the cooling fan/valve output. CH2-CH4 are reserved for future actuators.

### SSD1306 OLED Display (128x64, I2C)

| Display Pin | ESP32 GPIO | Notes                                           |
|-------------|------------|-------------------------------------------------|
| VCC         | 3.3 V      | Some breakouts accept 5 V - check your module   |
| GND         | GND        |                                                 |
| SDA         | GPIO 21    | Shared I2C bus                                  |
| SCL         | GPIO 22    | Shared I2C bus                                  |

Address 0x3C (A0 pad unsoldered). Solder A0 to change to 0x3D if there is an address conflict.

---

## Arduino Nano Serial Link (UART1)

| ESP32 Pin   | Nano Pin | Notes                                               |
|-------------|----------|-----------------------------------------------------|
| GPIO 16 (RX1) | TX     | Nano TX -> ESP32 RX via 10 kohm / 20 kohm divider (5 V -> 3.3 V level shift) |
| GPIO 17 (TX1) | RX     | ESP32 TX -> Nano RX direct (3.3 V logic high is recognised by Nano) |
| GND         | GND      | Common ground is mandatory for UART                 |

Baud rate: 9600. The Nano sends one telemetry line per second in the format `TEMP:x,HUM:x,PRES:x,LIGHT:x,MOIST:x,WATER:x`.

---

## STM32 Serial Link (UART2)

| ESP32 Pin    | STM32 Pin | Notes                                              |
|--------------|-----------|----------------------------------------------------|
| GPIO 18 (RX2)| TX        | STM32 TX -> ESP32 RX (both 3.3 V logic - direct)  |
| GPIO 19 (TX2)| RX        | ESP32 TX -> STM32 RX (both 3.3 V logic - direct)  |
| GND          | GND       | Common ground is mandatory                         |

Baud rate: 115200. The STM32 sends vibration/FFT results in the format `VIB:x,y,z,MAG:m,FFT_PEAK:hHz`.
