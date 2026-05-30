# ESP32 Primary Node - Pin Assignment and Wiring Guide

This document covers all wiring for the ESP32 DevKit V1 acting as the primary Phaemos node.

---

## Section 1: I2C Bus

All I2C sensors share a single bus: **SDA = GPIO21**, **SCL = GPIO22**.
Place 4.7k ohm pull-up resistors from SDA to 3.3V and SCL to 3.3V (one pair for the whole bus is sufficient).

| Sensor | VCC | GND | SDA | SCL | I2C Address | Notes |
|---|---|---|---|---|---|---|
| BME280 | 3.3V | GND | GPIO21 | GPIO22 | 0x76 | Address pin (SDO) tied to GND for 0x76; tie to 3.3V for 0x77 |
| MPU6050 | 3.3V | GND | GPIO21 | GPIO22 | 0x68 | AD0 pin tied to GND for 0x68; tie to 3.3V for 0x69 |
| INA219 | 3.3V | GND | GPIO21 | GPIO22 | 0x40 | A0 and A1 pins both to GND for default 0x40 |
| MLX90614 | 3.3V | GND | GPIO21 | GPIO22 | 0x5A | Fixed address; not configurable on standard breakouts |
| VL53L0X | 3.3V | GND | GPIO21 | GPIO22 | 0x29 | Fixed address; use XSHUT to reassign if running multiple |
| AS5600 | 3.3V | GND | GPIO21 | GPIO22 | 0x36 | Fixed address; only one AS5600 per I2C bus |
| SSD1306 OLED | 3.3V | GND | GPIO21 | GPIO22 | 0x3C | Some modules use 0x3D; check your specific breakout |

---

## Section 2: Analog and Digital Sensors

| Sensor | Signal Pin | Power | Notes |
|---|---|---|---|
| MQ-2 gas sensor | GPIO34 (AO analog), GPIO35 (DO digital) | 5V (heater), 3.3V (logic) | Allow 2-3 min warm-up time before readings are valid; AO gives continuous level, DO gives threshold alert |
| MAX4466 microphone | GPIO32 | 3.3V | Amplified analog output; trim pot on breakout sets gain |
| LDR | GPIO33 | 3.3V | Voltage divider: LDR from 3.3V to GPIO33, 10k resistor from GPIO33 to GND; higher resistance = lower voltage = darker |
| FC-28 moisture sensor | GPIO36 | 3.3V or 5V | AO pin to GPIO36; DO pin not connected; analog reading only |
| DS18B20 temperature probe | GPIO4 | 3.3V | OneWire protocol; place 4.7k ohm pull-up from GPIO4 to 3.3V; supports multiple probes on same pin |

---

## Section 3: Serial Connections to Other Nodes

| Connection | ESP32 RX | ESP32 TX | Other Node TX | Other Node RX | Baud |
|---|---|---|---|---|---|
| Nano -> ESP32 | GPIO16 (UART1 RX) | GPIO17 (UART1 TX) | Nano D1 (via level shifter) | Nano D0 | 9600 |
| STM32 -> ESP32 | GPIO18 (UART2 RX) | GPIO19 (UART2 TX) | STM32 PA9 (3.3V direct) | STM32 PA10 | 115200 |

**Important - Nano voltage level warning:** The Arduino Nano operates at 5V logic. Its TX pin (D1) outputs 5V signals. The ESP32 GPIO pins are rated for a maximum of 3.6V. Always use a 5V-to-3.3V level shifter (or a simple 10k/20k resistor voltage divider) on the wire from Nano D1 to ESP32 GPIO16. The STM32 Black Pill runs at 3.3V, so its UART output connects directly without a level shifter.

---

## Section 4: Output Components

| Component | GPIO | Notes |
|---|---|---|
| Passive buzzer | GPIO25 | PWM output; use ledcWrite in firmware for tone generation |
| WS2812B RGB LED strip | GPIO26 | Data line; use 300-500 ohm series resistor on data line to reduce ringing |
| Relay CH1 | GPIO13 | Active LOW on most relay modules; connect to IN1 |
| Relay CH2 | GPIO12 | Active LOW; connect to IN2; note GPIO12 must be LOW at boot |
| Relay CH3 | GPIO14 | Active LOW; connect to IN3 |
| Relay CH4 | GPIO27 | Active LOW; connect to IN4 |
| Panel LED - Red | GPIO15 | 220 ohm current-limiting resistor to GND |
| Panel LED - Green | GPIO2 | 220 ohm current-limiting resistor to GND; also onboard LED on DevKit |
| Panel LED - Amber | GPIO0 | 220 ohm current-limiting resistor to GND; must be HIGH at boot (do not hold LOW during power-on) |

---

## Section 5: Power Infrastructure

Power enters through a 2.1mm barrel jack rated for 12V DC. From there the path is:

12V barrel jack -> SPDT toggle switch -> 2A inline fuse -> LM2596 adjustable buck converter (set output to 5V) -> AMS1117-3.3 linear regulator (outputs 3.3V).

- The 4-channel relay module coils run on the **5V rail** from the LM2596 output.
- All sensor breakouts, the ESP32, STM32, and Pico 2W logic run on the **3.3V rail** from the AMS1117.
- The Nano itself runs on the **5V rail** but its I/O to the ESP32 must be level-shifted.
- Place a 10uF electrolytic capacitor on the 5V rail (close to the LM2596 output) and another on the 3.3V rail (close to the AMS1117 output) for bulk decoupling.
- Place 100nF ceramic decoupling capacitors between VCC and GND on each sensor breakout, as physically close to the IC as possible.
- Fit a **1N5819 Schottky diode** across each relay coil terminal (cathode to positive, anode to negative) to absorb the inductive kickback voltage when the relay de-energizes. Many relay modules include this on the PCB already - check your specific module.
