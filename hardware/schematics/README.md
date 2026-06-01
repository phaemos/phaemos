# Schematics

Proteus Design Suite project files for all 4 Phaemos nodes.

| File | Node | MCU | Status |
|---|---|---|---|
| esp32_node.pdsprj | Primary gateway | ESP32 DevKit V1 | Placeholder - draw in Proteus |
| stm32_node.pdsprj | Vibration/FFT | STM32F411 Black Pill | Placeholder - draw in Proteus |
| nano_node.pdsprj | Auxiliary sensor | Arduino Nano | Placeholder - draw in Proteus |
| pico_w_node.pdsprj | Ambient environment | Raspberry Pi Pico 2W | Placeholder - draw in Proteus |

For pin assignments and wiring details for each node, see `../wiring/`.

## Notes

- These are Proteus 8 project files (.pdsprj)
- All four files are currently empty placeholders - schematic drawing is a Phase 2 task
- Proteus may not have a native RP2040 component for the Pico 2W - use a generic MCU symbol or import a community library
- Schematic work should begin after breadboard prototyping is validated and the sensor layout is finalised
