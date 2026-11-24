---
title: "The four sensor nodes as they stand"
date: "2026-05-28"
slug: "hardware-deep-dive"
excerpt: "What each of the four sensor nodes reads, how they connect and how far the hardware has got."
---

Rewritten in November 2026 to match the product as it is now.

PHAEMOS has four node types: an ESP32 hub, an STM32 Black Pill, an Arduino Nano and a Raspberry Pi Pico 2W. All four are designed and not yet built. The plan is to prototype on development boards and breakouts. Carrier boards are still being designed. Nothing has been tested on a real machine. Readings so far come from the simulator.

## How they connect

The STM32 and the Nano send their readings to the ESP32 over serial lines. The ESP32 adds them to its own readings and posts everything to the API over Wi-Fi. The Pico 2W works alone and posts straight to the API. Every node sends its machine's key in the `X-API-Key` header.

## ESP32 hub

The hub is an ESP32 DevKit V1 programmed in Arduino C++. It reads 11 sensors:

- BME280 for temperature, humidity and pressure
- MPU6050 for acceleration and rotation
- INA219 for voltage and current
- MLX90614 for surface temperature
- VL53L0X for distance
- AS5600 for shaft angle and speed
- MQ-2 for gas
- FC-28 for moisture
- DS18B20 for contact temperature
- an LDR for light
- a MAX4466 microphone for sound

It also drives a buzzer, a 30-pixel LED strip, a four-channel relay, three status LEDs and an OLED. It posts a reading every 5 seconds. The Nano link runs at 9600 baud and the STM32 link at 115200.

A lost temperature sensor shows as a fault on the display and keeps the cooling relay off. The relay switches on after three critical readings in a row. A post to an unreachable API can hold the loop for about 4 seconds.

## STM32 Black Pill

The Black Pill samples an MPU6050 at 100 Hz and runs a 128-point FFT over each 1.28-second window. It sends one line per window:

```text
VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz
```

The build uses a plain built-in FFT by default. The firmware compiles and the FFT passes a host test on a computer. We have not yet run it on a board, so the clock set-up, the I2C recovery and the sensor timing are unproven on hardware.

## Arduino Nano

The Nano reads a BME280 or a BMP280, an LDR and an FC-28 moisture sensor. A BMP280 has no humidity element and always sends `HUM:-1`. Every 2 seconds it sends one line:

```text
TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0
```

A value of -1 means the reading is absent. The Nano uses 5 V logic and the ESP32 uses 3.3 V. The Nano's transmit line must go through a level shifter or a resistor divider, because wiring it straight across can damage the ESP32's receive pin.

## Raspberry Pi Pico 2W

The Pico 2W runs MicroPython. It reads a BME280 or BMP280 and an LDR and shows the values on an OLED. It posts every 5 seconds. It needs the Pico 2W build of MicroPython, because its RP2350 chip does not run the original Pico W image.

## Where the hardware stands

The plan has four phases. Phase 1 is breadboard prototyping and checking every sensor. We are in it. Phase 2 simulates each circuit in Proteus and draws the schematics in KiCad. Phase 3 is PCB layout and ordering boards. Phase 4 is enclosures. The PCB notes are placeholders until phase 1 is done. The wiring tables for each node are in `hardware/wiring`.
