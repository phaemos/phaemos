# Schematics

Proteus Design Suite simulation projects for all 4 Phaemos nodes. Proteus is used to simulate each circuit before a board is made. The schematics and PCB layouts that get manufactured are drawn in KiCad, see [`../pcb/`](../pcb/).

| File | Node | MCU | Status |
|---|---|---|---|
| esp32_node.pdsprj | Primary gateway | ESP32 DevKit V1 | Placeholder - simulate in Proteus |
| stm32_node.pdsprj | Vibration/FFT | STM32F411 Black Pill | Placeholder - simulate in Proteus |
| nano_node.pdsprj | Auxiliary sensor | Arduino Nano | Placeholder - simulate in Proteus |
| pico_w_node.pdsprj | Ambient environment | Raspberry Pi Pico 2W | Placeholder - simulate in Proteus |

For pin assignments and wiring details for each node, see `../wiring/`.

## Notes

- These are Proteus 8 project files (.pdsprj)
- All four files are currently empty placeholders - simulation is a Phase 2 task
- The KiCad schematic for each node will sit alongside its Proteus project once Phase 2 starts
- Proteus may not have a native RP2350 component for the Pico 2W - use a generic MCU symbol or import a community library
- Schematic work should begin after breadboard prototyping is validated and the sensor layout is finalised
