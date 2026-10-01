# Hardware

The hardware behind PHAEMOS: wiring, schematics, PCB layouts and the parts inventory for the four sensor nodes.

> [!NOTE]
> This folder is published to [phaemos/hardware](https://github.com/phaemos/hardware) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

| Folder | What it contains |
| --- | --- |
| [`wiring/`](wiring/) | Pin assignments and wiring guides for each node |
| [`schematics/`](schematics/) | Proteus schematic projects for each node |
| [`pcb/`](pcb/) | PCB layout notes and Gerber export guidance per node |
| [`inventory/`](inventory/) | Parts owned and parts still to buy |

## The four nodes

| Node | Board | Role | Firmware |
| --- | --- | --- | --- |
| Primary gateway | ESP32 DevKit V1 | Reads 11 local sensors, collects the STM32 and Nano readings over UART and posts everything to the API over Wi-Fi | [`firmware/esp32/`](https://github.com/phaemos/phaemos/tree/main/firmware/esp32) |
| Vibration and FFT | STM32F411 Black Pill | Samples an MPU6050 at 100 Hz, runs an FFT and sends the peak frequency to the ESP32 over UART | [`firmware/stm32_blackpill/`](https://github.com/phaemos/phaemos/tree/main/firmware/stm32_blackpill) |
| Auxiliary sensor | Arduino Nano | Reads a BME280, an LDR and an FC-28 and sends them to the ESP32 over serial | [`firmware/arduino_nano/`](https://github.com/phaemos/phaemos/tree/main/firmware/arduino_nano) |
| Ambient environment | Raspberry Pi Pico 2W | Reads a BME280 and an LDR, shows them on an OLED and posts straight to the API over Wi-Fi | [`firmware/pico_w/`](https://github.com/phaemos/phaemos/tree/main/firmware/pico_w) |

Every sensor with its interface, address and expected range is in the [sensor reference](https://github.com/phaemos/phaemos/blob/main/docs/sensor_reference.md).

> [!WARNING]
> The Arduino Nano uses 5 V logic and the ESP32 uses 3.3 V. The Nano's TX line must reach the ESP32 through a level shifter or a resistor divider, as shown in the [Nano firmware guide](https://github.com/phaemos/phaemos/tree/main/firmware/arduino_nano). Wiring it straight across can damage the ESP32's RX pin.

## Phase plan

- **Phase 1 (current):** breadboard prototyping, getting all four nodes posting data and verifying every sensor
- **Phase 2:** schematic capture in Proteus for all four nodes
- **Phase 3:** PCB layout in Proteus, with boards ordered from JLCPCB or PCBWay
- **Phase 4:** enclosures, 3D printed, laser cut or CNC machined depending on the node

The tasks for each phase are in the [Hardware milestone](https://github.com/phaemos/phaemos/milestone/4).

## Licence

The hardware designs are licensed under the CERN Open Hardware Licence v2, Strongly Reciprocal (CERN-OHL-S-2.0), see [LICENSE](LICENSE). Anyone can build, modify, manufacture and sell boards made from these designs. Anyone who distributes a product based on a modified design must share the modified design files under the same licence.
