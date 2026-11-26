# ESP32 Primary Node - Pin Assignment and Wiring Guide

This document covers all wiring for the ESP32 DevKit V1 acting as the primary Phaemos node.

---

## Section 1: I2C Bus

All I2C sensors share a single bus: **SDA = GPIO21**, **SCL = GPIO22**.
Place 4.7k ohm pull-up resistors from SDA to 3.3V and SCL to 3.3V (one pair for the whole bus is sufficient).

| Sensor | VCC | GND | SDA | SCL | I2C Address | Notes |
|---|---|---|---|---|---|---|
| BME280 | 3.3V | GND | GPIO21 | GPIO22 | 0x76 | Address pin (SDO) tied to GND for 0x76; tie to 3.3V for 0x77 |
| MPU6050 | 3.3V | GND | GPIO21 | GPIO22 | 0x68 | AD0 pin tied to GND for 0x68; tie to 3.3V for 0x69 |
| INA219 | 3.3V | GND | GPIO21 | GPIO22 | 0x40 | A0 and A1 pins both to GND for default 0x40 |
| MLX90614 | 3.3V | GND | GPIO21 | GPIO22 | 0x5A | Fixed address; not configurable on standard breakouts |
| VL53L0X | 3.3V | GND | GPIO21 | GPIO22 | 0x29 | Fixed address; use XSHUT to reassign if running multiple |
| AS5600 | 3.3V | GND | GPIO21 | GPIO22 | 0x36 | Fixed address; only one AS5600 per I2C bus |
| SSD1306 OLED | 3.3V | GND | GPIO21 | GPIO22 | 0x3C | Some modules use 0x3D; check your specific breakout |
| MCP23017 port expander | 3.3V | GND | GPIO21 | GPIO22 | 0x20 | Revised board. The firmware probes this address once at boot to recognise the board and does nothing else with it. A driver comes in a later step |
| INA219 (second, relay and strip rail) | 3.3V | GND | GPIO21 | GPIO22 | 0x41 | Revised board. 0.1 ohm shunt at up to 1.5 A, so the driver must use the 320 mV shunt range. Driver comes in a later step |

The revised board also has a push button. The wiring notes do not name its pin and the firmware does not read it. The hub's stored credentials are cleared by holding the DevKit BOOT button (GPIO0) for 5 seconds during the first 30 seconds after power-up (`PROVISION_CLEAR_PIN` in `config.h`). GPIO0 low at reset starts the bootloader, so do not hold it while pressing reset.

---

## Section 2: Analog and Digital Sensors

| Sensor | Signal Pin | Power | Notes |
|---|---|---|---|
| MQ-2 gas sensor | GPIO34 (AO analog), GPIO35 (DO digital) | 5V (heater) | AO reaches GPIO34 through a 2/3 divider (5 V becomes 3.33 V) with 20 kohm to ground, so an unplugged module reads 0 V. DO reaches GPIO35 through a level shifter pulled up to 3.3 V and is active LOW, so an unplugged module reads high (no alarm). The firmware treats an analogue reading under `MQ2_FAULT_ADC_MAX` after the warm-up as a sensor fault whatever DO says. It also ignores the gas alarm (panel: `FAULT: WARM`) for the first 180 s after a power-on (`MQ2_WARMUP_MS`). Clean air on a heated module is expected at about 200 to 530 counts and is unmeasured |
| MAX4466 microphone | GPIO32 | 3.3V | Amplified analog output; trim pot on breakout sets gain. On the revised board it reads 0 V when unplugged. A working module idles near 1.65 V |
| LDR | GPIO33 | 3.3V | Voltage divider: LDR from 3.3V to GPIO33, 10k resistor from GPIO33 to GND; higher resistance = lower voltage = darker |
| FC-28 moisture sensor | GPIO36 | 3.3V | AO pin to GPIO36 (input only, ADC1); DO pin not used; analog reading only. The water alert is raised under `WATER_THRESHOLD` (2000 counts, worked out from the Nano's wiring note and UNPROVEN until measured). The present board has no pull-down and no series resistor, so an unplugged input floats and its reading is not defined. The firmware never reports it as unplugged there. The revised board has a pull-down and carries a 2.2 kohm resistor in the probe lead: an unplugged probe then reads about 0 V, a flooded or shorted one about 0.6 V and a dry one about 3.0 V, so only a real flood raises the alert |
| 12 V input monitor | GPIO39 | 12V input | 100 kohm over 10 kohm divider, so input = pin voltage x 11. Input only, ADC1. 12 V at the connector reads about 1.05 V at the pin after the input diode |
| Sensor supply switch | GPIO14 | 3.3V sensor feed | Drive HIGH to switch the 3.3 V feed to the cable sensors off. Leave as an input (high impedance) at all other times because the board holds the switch on itself. The I2C lines must be held low while it is off. Otherwise the pull-ups feed the rail. On the present board GPIO14 is relay 3, so the firmware checks for the revised board's MCP23017 at 0x20 before it ever drives this pin. The ESP32 Series Datasheet version 5.3 (table IO_MUX) says the pin is output-disabled and input-disabled at reset and then an input with a weak pull-up (about 75 uA): it is never driven through a reset |
| DS18B20 temperature probe | GPIO4 | 3.3V | OneWire protocol; 4.7k ohm pull-up from GPIO4 to 3.3V on the board; the firmware reads the first probe on the bus only |

---

## Section 3: Serial Connections to Other Nodes

| Connection | ESP32 RX | ESP32 TX | Other Node TX | Other Node RX | Baud |
|---|---|---|---|---|---|
| Nano -> ESP32 | GPIO16 (UART1 RX) | GPIO17 (UART1 TX) | Nano D1 (through a 10 k / 20 k divider) | Nano D0 (through a BSS138 level shifter, see below) | 9600 |
| STM32 -> ESP32 | GPIO18 (UART2 RX) | GPIO19 (UART2 TX) | STM32 PA9 (USART1 TX, 3.3V direct) | STM32 PA10 (USART1 RX) | 115200 |

The ESP32 transmit pins (GPIO17 and GPIO19) also carry a `PING:<n>` request every 30 s, which the satellite answers with a checksummed `PONG:<n>`. On the revised board both receive pins (GPIO16 and GPIO18) have 100 kohm pull-downs, so an unplugged cable reads as a steady low. The present board has none. The ESP32 serial driver switches the internal pull-up on for a receive pin, so the revised image calls `gpio_pullup_dis()` on each after the port starts. The present image leaves the pull-up on, so a pulled cable reads high there and shows as `silent`.

**Nano link levels on the carrier board.** The carrier board does the level shifting in both directions, from its netlist:

- Hub to Nano (GPIO17 to Nano D0): a transistor level shifter. A BSS138 with 100 ohm in series and 10 kohm to 5 V, not inverting. The Nano's D0 sees 5.0 V for a high and about 0.5 V for a low. The hub sinks about 5 mA during a low.
- Nano to hub (Nano D1 to GPIO16): a resistor divider, 10 kohm over 20 kohm. It gives 3.33 V for a high with a source resistance of 6.7 kohm.

A bare jumper-wire build with no carrier board is marginal on the Nano's receive side. The ATmega328P reads a high at 0.6 x VCC, which is 3.0 V at 5.0 V and 3.15 V at 5.25 V. The ESP32 drives 3.3 V, so a direct connection sits only 0.3 V (or less) above the threshold. Such a build needs the same two circuits. If the level is marginal the hub reports `one_way` on a healthy Nano, because the pong never comes. On a typical Nano the receive pin D0 is also driven by the USB serial chip through 1 kohm, so a ping sent during an upload could corrupt the upload. We have not checked that on our boards, so it is a bench check and not a known fact.

**Important - Nano voltage level warning:** The Arduino Nano operates at 5V logic. Its TX pin (D1) outputs 5V signals. The ESP32 GPIO pins are rated for a maximum of 3.6V. The Nano's D1 must never go straight to GPIO16. The two circuits above are the ones to use: a 10 kohm over 20 kohm divider from Nano D1 to GPIO16 and a BSS138 shifter with 100 ohm in series and 10 kohm to 5 V from GPIO17 to Nano D0. The STM32 Black Pill runs at 3.3V, so its UART output connects directly without a level shifter.

---

## Section 4: Output Components

| Component | GPIO | Notes |
|---|---|---|
| Passive buzzer | GPIO25 | Through an NPN stage, HIGH energises; driven by tone() at 2000 Hz |
| WS2812B RGB LED strip | GPIO26 | Data line through a 5 V buffer on the carrier board. The firmware addresses 30 LEDs and caps the current at 1.2 A (`STRIP_CURRENT_LIMIT_MA`) |
| Relay CH1 | GPIO13 | Active HIGH through an NPN stage to IN1 on the separate relay module; CH1 is the cooling output |
| Relay CH2 | GPIO12 | Active HIGH; connect to IN2; note GPIO12 must be LOW at boot |
| Relay CH3 | GPIO23 (revised board) or GPIO14 (present board) | Active HIGH; connect to IN3. On the revised board it moved to GPIO23 and GPIO14 became the sensor supply switch. The `esp32dev` build drives GPIO14 and the `esp32dev_revb` build drives GPIO23. On the present board GPIO14 floats through a reset and then has a weak pull-up (ESP32 Series Datasheet version 5.3, table IO_MUX). Into an NPN base with no pull-down of its own that pull-up could bias the driver. A relay coil needs far more current than that, so it is unlikely to pull in, but one scope shot of the relay 3 driver through a reset is the bench check |
| Relay CH4 | GPIO27 | Active HIGH; connect to IN4 |
| Panel LED - Red | GPIO15 | 3.3 V through a resistor to the pin, LOW lights it |
| Panel LED - Green | GPIO2 | Through an NPN stage, HIGH lights it |
| Panel LED - Amber | GPIO5 | 3.3 V through a resistor to the pin, LOW lights it. Needs solder jumper JP4 bridged |

---

## Section 5: Power Infrastructure

Power enters at the 12 V DC input, through an input diode and a resettable fuse. The board has two switching regulators:

- A 1 A module makes the +5V rail for the dev board, the MQ-2 heater and the buzzer.
- A 2 A module makes a separate 5 V rail for the relay module and the LED strip. The split keeps strip and relay current off the rail that feeds the processor and the gas sensor.
- The ESP32 and the sensors run on 3.3 V. The cable sensors are fed through the switch on GPIO14 (see Section 2).
- The board has six resettable fuses: the input, the three feeds to the other boards, the strip and the cable sensors.
- The relays are not on this board. A 6-pin connector goes to a separate 4-channel relay module through four NPN drivers, active HIGH. Whether a floating pin leaves a relay off depends on the base network of each driver, which these notes do not give. No coil is on this board.
- The 12 V input is read on GPIO39 (Section 2). It reads about 1.05 V at the pin at 12 V, after the input diode.
- The Nano runs on its own 5 V feed but its serial output to the ESP32 must be level-shifted (Section 3).
- Keep 100nF ceramic decoupling capacitors between VCC and GND on each sensor breakout, as physically close to the IC as possible.
- Each relay coil needs a flyback diode (cathode to positive, anode to negative). Many relay modules include this on the PCB already, so check your specific module.
