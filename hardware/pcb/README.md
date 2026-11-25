# PCB design

One carrier board for each of the four PHAEMOS nodes. The development board plugs into it and the sensors, power and connectors sit around it.

> [!IMPORTANT]
> All four boards are fully designed and waiting to be manufactured. None has been built or tested. We publish the KiCad files and Gerbers once the boards have been made and tested.

| Page | Node | Board | Status |
| --- | --- | --- | --- |
| [esp32_node.md](esp32_node.md) | Primary gateway (ESP32 DevKit V1) | 100 mm by 180 mm, four layers | Designed, awaits manufacture |
| [stm32_node.md](stm32_node.md) | Vibration and FFT (STM32F411 Black Pill) | 99.06 mm by 58.42 mm, two layers | Designed, awaits manufacture |
| [nano_node.md](nano_node.md) | Auxiliary sensor (Arduino Nano) | 81.28 mm by 63.5 mm, two layers | Designed, awaits manufacture |
| [pico_w_node.md](pico_w_node.md) | Ambient environment (Raspberry Pi Pico 2 W) | 99.06 mm by 58.42 mm, two layers | Designed, awaits manufacture |

## How each board was checked

1. The schematic is drawn in KiCad 10 and passes the electrical rules check.
2. The board is laid out and passes the design rules check with nothing left unconnected.
3. Every pin on the board is compared with the node's firmware and wiring guide.
4. The power input, reverse protection, level shifters, drivers and sensor supplies are simulated in LTspice with the real parts' figures.

## Layout rules we kept

- I2C traces (SDA and SCL) run away from relay switching and the MQ-2 heater.
- Analogue sensor signals (LDR, FC-28, MQ-2 output, MAX4466) are kept apart from digital and PWM traces.
- Each IC has a 100 nF decoupling capacitor at its power pin.
- Each relay coil has a flyback diode.
- Ground pours on both outer layers are stitched together with vias.
