# Firmware

Firmware for all 4 Phaemos nodes. Each node has its own subfolder.

| Folder | Node | Board | Language |
|---|---|---|---|
| [esp32/](esp32/) | Primary gateway | ESP32 DevKit V1 | Arduino C++ |
| [stm32_blackpill/](stm32_blackpill/) | Vibration/FFT | STM32F411 Black Pill | C (STM32CubeIDE) |
| [arduino_nano/](arduino_nano/) | Auxiliary sensor | Arduino Nano | Arduino C++ |
| [pico_w/](pico_w/) | Ambient environment | Raspberry Pi Pico 2W | MicroPython |

---

## How the nodes connect

```
[STM32 Black Pill] --UART--> |
[Arduino Nano]     --UART--> |---> [ESP32 DevKit V1] --Wi-Fi--> [Backend API]
                             |
[Pico 2W] ----------------Wi-Fi--> [Backend API]
```

- The ESP32 is the central hub - it reads its own sensors and receives UART data from the STM32 and Nano
- The Pico 2W runs independently and posts directly to the backend over Wi-Fi
- All nodes post to `POST /api/v1/telemetry` with their device API key in `X-API-Key` header

---

## Legacy / v1 code

- `arduino/` - original v1 Arduino sketch (pre-modular refactor). Kept for reference.
- `stm32/` - original v1 STM32 sketch. Kept for reference. Use `stm32_blackpill/` for active development.

---

## Flashing

| Board | Tool | Notes |
|---|---|---|
| ESP32 | Arduino IDE or PlatformIO | Select ESP32 Dev Module, 115200 baud |
| STM32 Black Pill | STM32CubeIDE + ST-Link V2 | SWD interface, 4-wire connection |
| Arduino Nano | Arduino IDE | Select Arduino Nano, Old Bootloader if using clone |
| Pico 2W | Thonny or rshell | Hold BOOTSEL on power-up, copy .uf2 or use MicroPython REPL |
