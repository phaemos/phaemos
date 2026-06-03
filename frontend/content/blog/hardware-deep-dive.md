---
title: "Hardware Deep Dive: 4 Nodes, 11 Sensors, One Platform"
date: "2026-05-28"
slug: "hardware-deep-dive"
excerpt: "A tour of the four firmware nodes at the core of PHAEMOS - ESP32 telemetry hub, STM32 vibration processor, Pico W power monitor, and Arduino Nano legacy bridge."
---

# Hardware Deep Dive: 4 Nodes, 11 Sensors, One Platform

PHAEMOS is built around four microcontroller nodes, each chosen for a specific role. Here is what each one does and why.

## ESP32 - Wi-Fi telemetry hub

The ESP32 is the primary data reporter. It reads temperature, humidity and gas concentration, packages them as JSON, and POSTs to `/api/v1/telemetry` over Wi-Fi every 5 seconds. The authentication token is stored in non-volatile storage (NVS) so it survives power cycles.

**Sensors on this node:**
- DHT22 - temperature (-40 to 80 C, ±0.5 C) and humidity (0-100%, ±2%)
- MQ-135 - gas/air quality (ppm CO2 equivalent, needs 24-hour warmup)

The ESP32's dual-core Xtensa LX6 is more than needed for this workload - the second core handles the Wi-Fi stack while the first handles sensor reads. Battery-backed deployment is practical; deep sleep between reads brings average current below 1 mA.

## STM32 BlackPill - vibration FFT processor

The STM32F411CEU6 runs at 100 MHz with hardware FPU. This is the only node where compute matters - running a 128-point real FFT on 3-axis accelerometer data requires floating-point throughput.

**Sensors on this node:**
- MPU-6050 - 6-DOF IMU: 3-axis accelerometer (±16g) and gyroscope

The FFT is implemented using `arm_rfft_fast_f32` from CMSIS-DSP, ARM's optimised signal processing library. The algorithm:

1. Reads 128 samples from the accelerometer Z axis at a fixed sample rate
2. Applies `arm_rfft_fast_f32` to transform to the frequency domain
3. Skips bin 0 (DC component - dominated by gravity) and finds the peak magnitude bin
4. Returns `peak_bin * sample_rate / sample_count` as the peak frequency in Hz

The peak frequency is a compact, meaningful feature for bearing fault detection. A healthy bearing running at 1,500 RPM shows a clean peak at 25 Hz. A bearing with outer-race fault shows sidebands and sub-harmonics. The Isolation Forest learns these patterns.

The node communicates upstream via UART to the ESP32 which relays the FFT result alongside its own sensor data.

## Raspberry Pi Pico W - power monitor

The Pico W handles power quality monitoring and precise temperature measurement. The RP2040 dual-core Cortex-M0+ is well-suited to simultaneous ADC sampling and Wi-Fi.

**Sensors on this node:**
- INA219 - current and voltage (I2C, 26V max, 3.2A max, 1% accuracy)
- ACS712 - AC/DC current (30A model, analogue output, ±5% accuracy)
- BMP280 - barometric pressure (300-1100 hPa, ±1 hPa) and temperature (±1 C)

Power monitoring gives the ML model an additional input. Motors drawing more current than usual under a given load profile often indicate mechanical wear. The INA219 communicates via I2C; the ACS712 produces an analogue voltage proportional to current, read via the Pico's 12-bit ADC.

## Arduino Nano - legacy sensor bridge

The Nano bridges sensors with 5V-only interfaces that would damage a 3.3V MCU directly. It reads them via its 5V ADC, converts the readings, and sends JSON over UART at 115200 baud to the ESP32.

**Sensors on this node:**
- HC-SR04 - ultrasonic distance (2-400 cm, ±3 mm) for level or proximity monitoring
- LM35 - linear temperature (10 mV/C, 0-100 C, no calibration required)
- IR sensor - presence/motion detection (digital output)

The Nano uses no RTOS - a simple `loop()` with a 1-second blocking delay is sufficient for sensors that change slowly.

## Wiring it together

All four nodes plus the Raspberry Pi 4 backend server share a 12V/5A rail. The Pico W and ESP32 each have their own 5V regulators. The STM32 runs from a 3.3V LDO.

Full pinouts and wiring diagrams are in `hardware/wiring/`. The schematic for the custom ESP32 carrier board is in `hardware/schematics/`.

Hardware questions: [dev@phaemos.com](mailto:dev@phaemos.com)
