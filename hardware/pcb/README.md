# PCB Design

Layout notes and Gerber export guidance for each of the 4 Phaemos nodes.
PCB work is Phase 3 - do not start until breadboard validation is complete and schematics are drawn.

| File | Node | Status |
|---|---|---|
| [esp32_node.md](esp32_node.md) | Primary gateway (ESP32 DevKit V1) | Placeholder |
| [stm32_node.md](stm32_node.md) | Vibration/FFT (STM32F411 Black Pill) | Placeholder |
| [nano_node.md](nano_node.md) | Auxiliary sensor (Arduino Nano) | Placeholder |
| [pico_w_node.md](pico_w_node.md) | Ambient environment (Raspberry Pi Pico 2W) | Placeholder |

---

## General workflow

1. Complete schematic in Proteus ISIS (see `../schematics/`) - all 4 nodes must pass ERC
2. Transfer netlist to Proteus ARES for PCB layout per node
3. Set board outline to match chosen enclosure dimensions
4. Route power planes first, then signal traces, then pour GND on bottom layer
5. Run DRC and resolve all violations
6. Export Gerbers: F.Cu, B.Cu, silkscreen, mask, edge cuts, drill file
7. Order from JLCPCB or PCBWay - typically 5 boards for ~£15-20 including UK shipping

## Recommended spec

- 2-layer FR4, 1.6mm
- ENIG (gold) finish for I2C connector pads
- Green solder mask, white silkscreen
- Min trace 0.2mm, clearance 0.2mm
- Board size: confirm against chosen enclosure before ordering

## Key layout rules

- Keep I2C traces (SDA/SCL) away from relay switching and MQ-2 heater traces
- Keep analog sensor signals (LDR, FC-28, MQ-2 AO, MAX4466) physically separated from digital/PWM traces
- Route 5V and 3.3V power traces at minimum 1mm width
- Add 100nF decoupling cap near each IC power pin
- Add flyback diode across each relay coil (1N5819, cathode to positive rail)
- Stitch GND pours on top and bottom layers with vias every 10-15mm

## Cost estimate (JLCPCB)

| Item | Cost |
|---|---|
| 5x 2-layer boards (standard spec) | ~£2-5 |
| DHL shipping to UK | ~£8-12 |
| Total per node order | ~£10-17 |
