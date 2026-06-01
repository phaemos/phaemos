# Hardware

All hardware documentation for the 4-node Phaemos system.

| Folder | What it contains |
|---|---|
| [wiring/](wiring/) | Pin assignment and wiring guides for each node |
| [schematics/](schematics/) | Proteus schematic project files (.pdsprj) for each node |
| [pcb/](pcb/) | PCB layout notes and Gerber export guidance per node |
| [inventory/](inventory/) | Component tracking - what we own vs what still needs buying |

---

## The 4 nodes

| Node | Board | Role | Firmware |
|---|---|---|---|
| Primary gateway | ESP32 DevKit V1 | Reads all local sensors, coordinates UART nodes, posts to backend over Wi-Fi | `firmware/esp32/` |
| Vibration/FFT | STM32F411 Black Pill | Runs FFT on ADXL345 accelerometer, sends peak frequency over UART to ESP32 | `firmware/stm32/` |
| Auxiliary sensor | Arduino Nano | Reads secondary sensors, sends readings over UART to ESP32 | `firmware/nano_node/` |
| Ambient environment | Raspberry Pi Pico 2W | Reads BME280, posts directly to backend over Wi-Fi using MicroPython | `firmware/pico_w/` |

---

## Phase plan

- **Phase 1 (now):** Breadboard prototyping - get all 4 nodes posting data, verify sensors
- **Phase 2:** Schematic capture in Proteus ISIS for all 4 nodes
- **Phase 3:** PCB layout in Proteus ARES, order boards from JLCPCB or PCBWay
- **Phase 4:** Custom enclosure design - 3D print, laser cut or CNC depending on form factor
