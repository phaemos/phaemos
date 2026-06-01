# Wiring Guides

Pin assignments and wiring tables for each of the 4 Phaemos nodes.

| File | Node | Board |
|---|---|---|
| [esp32_pinout.md](esp32_pinout.md) | Primary gateway | ESP32 DevKit V1 |
| [stm32_pinout.md](stm32_pinout.md) | Vibration/FFT | STM32F411 Black Pill |
| [nano_pinout.md](nano_pinout.md) | Auxiliary sensor | Arduino Nano |
| [pico_pinout.md](pico_pinout.md) | Ambient environment | Raspberry Pi Pico 2W |

Each file covers: I2C bus wiring, analog/digital sensor connections, UART connections to other nodes, power requirements and pull-up resistor values.

Refer to `../inventory/needed.md` to check which sensors have arrived before starting to wire up.
