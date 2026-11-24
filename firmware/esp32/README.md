# PHAEMOS ESP32 Hub - Wiring Reference

This document covers every sensor and output on the ESP32 hub node introduced in the v2 hardware spec (May 2026). Pin numbers refer to ESP32 GPIO unless otherwise stated.

> [!IMPORTANT]
> The revised carrier board is not built yet. Nothing here has run on hardware. Everything below that describes the revised board, the fault reporting, the post task and the serial link parser is proven only by the build and the host tests in `test_host/`. `platformio.ini` has two environments. `esp32dev` is the first board design and is the default. `esp32dev_revb` is the revised board. See Two environments, two boards below. The hub posts over TLS to an `https://` address. The two trust roots it checks that against are placeholders that the owner pastes in (see Posting over TLS), so until then a default build refuses every post.

---

## Power Infrastructure

```
12 V DC supply (input diode, then a resettable fuse)
  |
  +-- 1 A switching regulator --> 5 V rail for the dev board, the MQ-2 heater and the buzzer
  |
  +-- 2 A switching regulator --> separate 5 V rail for the relay module and the LED strip

3.3 V rail feeds:
  - ESP32 VCC
  - The cable sensors, through the switch on GPIO14 (see sensor 12 below)
  - SSD1306 OLED display (the board feeds its socket from 3.3 V)
  - MQ2 digital output (through a level shifter that is pulled up to 3.3 V, see sensor 7)
```

The two 5 V rails are separate so that strip and relay current stays off the rail that feeds the processor and the gas sensor. The board has six resettable fuses: the input, the three feeds to the other boards, the strip and the cable sensors. The relays are not on this board. A 6-pin connector goes to a separate 4-channel relay module through four NPN drivers. Whether a floating pin leaves a relay off depends on the base network of each driver, which the wiring notes do not give. We drive the relay pins low as early as we can. GPIO14 is the open case (see Board check). The 12 V input is read on GPIO39 (see sensor 13 below).

---

## I2C Bus (shared across all I2C sensors)

| Signal | ESP32 GPIO |
|--------|-----------|
| SDA    | GPIO 21   |
| SCL    | GPIO 22   |

All I2C sensors share one bus. Each has a unique hardware address (see `config.h`). A 4.7 kohm pull-up to 3.3 V on both SDA and SCL is required.

The revised board also carries an MCP23017 port expander at 0x20 and a second INA219 at 0x41 (it measures the relay and strip rail through a 0.1 ohm shunt at up to 1.5 A, so its driver must use the 320 mV shunt range), plus a push button. The expander has a driver on the revised image: it probes 0x20 at boot to recognise the board (see Board check) and then reads the rail inputs and the button (see Port expander on the revised board). The second INA219 has no driver yet. The firmware only probes the addresses it knows, so extra devices on the bus do no harm.

---

## Sensor Wiring Tables

### 1. BME280 - Temperature / Humidity / Pressure

| Sensor Pin | ESP32 GPIO | Notes                                      |
|------------|------------|--------------------------------------------|
| VCC        | 3.3 V      | Do not use 5 V - maximum rated is 3.6 V    |
| GND        | GND        |                                            |
| SDA        | GPIO 21    | Shared I2C bus                             |
| SCL        | GPIO 22    | Shared I2C bus                             |
| SDO        | GND        | Sets I2C address to 0x76                   |

### 2. MPU6050 - 6-Axis IMU (Accelerometer + Gyroscope)

| Sensor Pin | ESP32 GPIO | Notes                                      |
|------------|------------|--------------------------------------------|
| VCC        | 3.3 V      |                                            |
| GND        | GND        |                                            |
| SDA        | GPIO 21    | Shared I2C bus                             |
| SCL        | GPIO 22    | Shared I2C bus                             |
| AD0        | GND        | Sets I2C address to 0x68                   |
| INT        | Not connected | Interrupt not used in v2 polling mode   |

### 3. INA219 - Current / Voltage Monitor

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      |                                                    |
| GND        | GND        |                                                    |
| SDA        | GPIO 21    | Shared I2C bus                                     |
| SCL        | GPIO 22    | Shared I2C bus                                     |
| VIN+       | Load +     | Connect between supply and load positive terminal  |
| VIN-       | Load -     | Connect to load positive terminal (after shunt)    |

A0, A1 tied to GND for address 0x40.

### 4. MLX90614 - Infrared Non-Contact Thermometer

| Sensor Pin | ESP32 GPIO | Notes                                          |
|------------|------------|------------------------------------------------|
| VCC        | 3.3 V      |                                                |
| GND        | GND        |                                                |
| SDA        | GPIO 21    | Shared I2C bus - requires 4.7 kohm pull-up     |
| SCL        | GPIO 22    | Shared I2C bus - requires 4.7 kohm pull-up     |

Address 0x5A (factory default, not configurable without reprogramming).

### 5. VL53L0X - Time-of-Flight Distance Sensor

| Sensor Pin | ESP32 GPIO | Notes                                          |
|------------|------------|------------------------------------------------|
| VCC        | 3.3 V      |                                                |
| GND        | GND        |                                                |
| SDA        | GPIO 21    | Shared I2C bus                                 |
| SCL        | GPIO 22    | Shared I2C bus                                 |
| XSHUT      | Not connected | Pulled high internally - sensor always on   |
| GPIO1      | Not connected | Data-ready interrupt not used in v2         |

Address 0x29 (default).

### 6. AS5600 - Magnetic Rotary Position Encoder

| Sensor Pin | ESP32 GPIO | Notes                                          |
|------------|------------|------------------------------------------------|
| VCC        | 3.3 V      |                                                |
| GND        | GND        |                                                |
| SDA        | GPIO 21    | Shared I2C bus                                 |
| SCL        | GPIO 22    | Shared I2C bus                                 |
| DIR        | GND        | CW positive rotation                           |

Address 0x36 (fixed, cannot be changed).

### 7. MQ2 - Gas / Smoke Sensor

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 5 V        | Heater requires 5 V - do not use 3.3 V              |
| GND        | GND        |                                                    |
| AO         | GPIO 34    | Analog output - GPIO34 is input-only, ADC1 ch6     |
| DO         | GPIO 35    | Digital threshold output, active LOW - GPIO35 is input-only |

On the carrier board the analogue output reaches GPIO34 through a 2/3 divider (5 V becomes 3.33 V) and the digital output reaches GPIO35 through a level shifter that is pulled up to 3.3 V. A LOW digital output means gas.

The heater needs time to settle after power-on. We ignore the gas alarm for the first 180 s (`MQ2_WARMUP_MS` in `config.h`) and the panel and the display show `FAULT: WARM` for the whole of it, because the gas alarm is not available then. A warm reset skips what is left of the warm-up only when the saved state says the warm-up had finished before the reset. A reset inside the first 180 s starts the count again, because a cold heater would raise a false alarm.

The board pulls the digital line up to 3.3 V through its level shifter, so an unplugged module or a dead comparator reads high, which is no alarm. The analogue output reaches GPIO34 through a 2/3 divider with 20 kohm to ground, so an unplugged module reads 0 V (about 0 counts). A heated MQ-2 in clean air is a few tenths of a volt after the divider, about 200 to 530 counts. That figure is unmeasured and the bench has to confirm it. After the warm-up an analogue reading under `MQ2_FAULT_ADC_MAX` (100 counts) is therefore a sensor fault whatever the digital line says. The panel shows `FAULT: MQ-2` and the gas alarm is not available. The ESP32 ADC at 11 dB reads zero up to roughly 0.1 V, so 100 counts may be nearer 0.2 V at the pin than the 0.08 V that `config.h` works from. A healthy module in clean air could sit under it and show `FAULT: MQ-2` for ever. That is suspected and not measured, so the bench has to confirm the clean-air reading.

There are two alarm paths and either one alarms. The digital output is the module's comparator, set by its potentiometer. The analogue path alarms at `GAS_ANALOGUE_ALARM_COUNTS` (1,600 counts). That level is worked out and not measured and `GAS_ALARM_PROVEN` stays 0 until the bench has measured it. The hub says so on the serial monitor at boot. When the digital output alarms and the analogue level sits inside the clean-air band (`MQ2_CLEAN_AIR_MAX_COUNTS`, 530 counts) the two paths disagree. We report that as a fault (`FAULT: MQ-2`) and the alarm stays raised. A module whose digital output is dead is caught only when the gas is strong enough for the analogue path. The analogue fault and alarm levels are the unproven part.

### 8. FC-28 - Soil Moisture / Water Detection

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      |                                                    |
| GND        | GND        |                                                    |
| AO         | GPIO 36    | Analog output (GPIO36 = VP, input-only, ADC1 ch0)  |
| DO         | Not used   | Threshold set by onboard potentiometer             |

THE WATER ALARM IS UNPROVEN until `WATER_THRESHOLD` has been measured on a real probe. It is 2,000 counts, worked out from the Nano's wiring note (see Failed sensors and fault reporting and the arithmetic in `config.h`). The hub says so at boot.

A dry probe reads about 3.0 V, which is near the top of the ADC range, so a high reading is normal. What an unplugged input reads depends on the image.

- Present board (`esp32dev`): the input has no pull-down and no series resistor, so an unplugged input floats and its reading is not defined. The firmware never reports `unplugged` for it. A floating input can read low and raise the water alarm. That is not measured either way.
- Revised board (`esp32dev_revb`): the board has the pull-down and the 2.2 kohm series resistor (see below). An unplugged probe reads about 0 V, which is never an alarm and `fc28` is `unplugged` with `FAULT: PRB` on the panel.
- A pull-down without the series resistor is a build neither image uses. There a probe flooded with a conductive liquid reads nearly as low as an unplugged one and the two cannot be told apart, so the leak alarm wins: a reading under `WATER_THRESHOLD` always raises it. The alarm and `FAULT: PRB` would then alternate on the panel.

`MOISTURE_UNPLUGGED_MAX_COUNTS` and `MOISTURE_UNPLUGGED_PASSES` give the unplugged test where there is a pull-down. In every case `water_detected` is posted and the backend alarms on it.

The revised board will carry a 2.2 kohm resistor in the probe lead (`HAS_PROBE_SERIES_R`, on for `esp32dev_revb`). With it an unplugged probe reads about 0 V, a flooded or shorted probe about 0.6 V (about 790 counts) and a dry probe about 3.0 V. A reading at or under `PROBE_UNPLUGGED_MAX_COUNTS` (200 counts, about 0.15 V) is unplugged and never an alarm. Only a real flood raises it. A hub with no probe sets `HAS_FC28` to 0.

### 9. DS18B20 - 1-Wire Temperature Sensor

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      | Parasitic power mode not used                      |
| GND        | GND        |                                                    |
| DATA       | GPIO 4     | Requires 4.7 kohm pull-up to 3.3 V on DATA line   |

### 10. LDR - Light Dependent Resistor (v2)

| Component  | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| LDR top    | 3.3 V      | One leg of LDR connected to 3.3 V                  |
| LDR bottom | GPIO 33    | Other leg of LDR to GPIO33 and 10 kohm to GND     |

GPIO33 is ADC1 ch5. A 10 kohm resistor to GND forms a voltage divider with the LDR. The ADC reaches full scale at about 3.1 V at 11 dB. A bright LDR of 500 ohm already puts 3.1 V on the pin. A short to 3.3 V therefore cannot be told from bright light. Zero cannot be told from darkness, so the `ldr` key never reports a fault.

### 11. MAX4466 - Microphone / Sound Level

| Sensor Pin | ESP32 GPIO | Notes                                              |
|------------|------------|----------------------------------------------------|
| VCC        | 3.3 V      |                                                    |
| GND        | GND        |                                                    |
| OUT        | GPIO 32    | Analog audio output - GPIO32 ADC1 ch4              |

Gain is set by the onboard potentiometer. Centre output at 1.65 V (VCC/2).

On the revised board this input reads 0 V when the module is unplugged. A working module idles near half the supply, so a mean at or under `MIC_UNPLUGGED_MAX_COUNTS` is reported as unplugged. A mean at the top of the scale (`MIC_RAIL_MIN_COUNTS`) is reported as out of range.

### 12. Sensor supply switch

| Signal | ESP32 GPIO | Notes |
|--------|------------|-------|
| Sensor rail switch | GPIO 14 | Driving it HIGH switches the 3.3 V feed to the cable sensors off |

The board holds the switch on by itself, so we leave GPIO14 as an input (high impedance) at every other time. `setup()` makes it an input on both images before the board check and waits the sensor start-up time before the check uses the bus (see Board check). The ESP32 floats the pin through a reset and then gives it a weak pull-up, which is the direction that switches the feed off, so the cable sensors can lose their supply for a moment on every reset until `sensorRailInit()`. The 150 ms wait after it covers the restart. The switch alone does not remove power, because the I2C pull-ups would feed the rail through the sensors' data pins. `sensorRailPowerCycle()` therefore ends the bus and holds GPIO21 and GPIO22 low for the whole off period. It then returns GPIO14 to an input (that is what switches the rail back on, so we never drive it low) and waits `SENSOR_RAIL_SETTLE_MS` for the gate capacitor. It then releases the bus lines and waits `SENSOR_RAIL_STARTUP_MS` for the sensors. The DS18B20's data line is held low too, because the probe can power itself from it. Only then does it start the bus again. `recoverSensorRail()` then sets every sensor up again and sets the display up again, in case it sits on the switched rail. It refuses to run unless the board is the revised board. Nothing calls it yet, because the hub has no I2C bus recovery to hang it on.

### 13. 12 V input monitor

| Signal | ESP32 GPIO | Notes |
|--------|------------|-------|
| 12 V input | GPIO 39 | Through 100 kohm over 10 kohm, so the input is the pin voltage times 11. Input only, ADC1 |

`readInputVoltage()` averages `INPUT_VOLTAGE_SAMPLES` calibrated millivolt reads at 11 dB (about 0 to 3 V). 12 V at the connector reads about 1.05 V at the pin after the input diode. The supply is reported as out of range under `SUPPLY_MIN_V` (9 V) or over `SUPPLY_MAX_V` (15 V).

---

## Output Wiring Tables

### Buzzer (passive)

| Component   | ESP32 GPIO | Notes                                              |
|-------------|------------|----------------------------------------------------|
| Buzzer      | GPIO 25    | Through an NPN stage, HIGH energises. Driven by tone() at 2000 Hz |

Alert sounds are non-blocking and repeat slowly (every 30 s for a warning or fault and every 10 s when critical). A critical request cuts in on a lesser pattern that is still playing.

### NeoPixel RGB LED Strip (WS2812B)

| Strip Pin | ESP32 GPIO | Notes                                               |
|-----------|------------|-----------------------------------------------------|
| VCC       | 5 V        | WS2812B requires 5 V - do not use 3.3 V             |
| GND       | GND        |                                                     |
| DIN       | GPIO 26    | Through a 5 V buffer on the carrier board           |

> [!IMPORTANT]
> With `RGB_LED_COUNT = 30` in `config.h`, each pixel draws about 60 mA at full white, so the strip alone could pull 1.8 A at 5 V. The strip rail only supplies about 1.2 A, so the firmware scales any colour down to stay under `STRIP_CURRENT_LIMIT_MA` (1200). That cap is what the fuse carries in a warm enclosure, so do not raise it without changing the fuse. The bench strip is reported to have 60 LEDs. We have not counted them. We address 30 and keep the same cap.

### 4-Channel Relay Module (active-high)

| Relay     | ESP32 GPIO | Notes                                               |
|-----------|------------|-----------------------------------------------------|
| IN1 (CH1) | GPIO 13    | HIGH = relay on (coil energised), LOW = relay off   |
| IN2 (CH2) | GPIO 12    |                                                     |
| IN3 (CH3) | GPIO 23    | Revised board. On the present board relay 3 is still GPIO14 |
| IN4 (CH4) | GPIO 27    |                                                     |
| VCC       | 5 V        | Relay coil supply                                   |
| GND       | GND        |                                                     |
| JD-VCC    | 5 V        | Coil supply                                         |

Each pin drives an NPN stage on the carrier board, so HIGH turns a relay on. `setup()` drives the relay pins LOW before anything else. GPIO12 is a boot strap that must be low at reset and this wiring satisfies that. GPIO14 is relay 3 only in the present-board image and only when the board check agrees (see Board check). In the revised-board image it is the sensor supply switch (see above) and nothing drives it as a relay. The cooling relay (CH1) is the only one the firmware switches.

CH1 is wired to the cooling fan/valve output. CH2-CH4 are reserved for future actuators.

### Panel LEDs (status)

| LED   | ESP32 GPIO | Drive                                                     |
|-------|------------|-----------------------------------------------------------|
| Red   | GPIO 15    | 3.3 V through a resistor to the pin, LOW lights it        |
| Amber | GPIO 5     | 3.3 V through a resistor to the pin, LOW lights it        |
| Green | GPIO 2     | Through an NPN stage, HIGH lights it                      |

Green means normal, amber means warning and red means critical. The amber LED needs solder jumper JP4 bridged. The status is also shown in words on the display and in the serial log, never by colour alone.

### SSD1306 OLED Display (128x64, I2C)

| Display Pin | ESP32 GPIO | Notes                                           |
|-------------|------------|-------------------------------------------------|
| VCC         | 3.3 V      | Some breakouts accept 5 V - check your module   |
| GND         | GND        |                                                 |
| SDA         | GPIO 21    | Shared I2C bus                                  |
| SCL         | GPIO 22    | Shared I2C bus                                  |

Address 0x3C (A0 pad unsoldered). Solder A0 to change to 0x3D if there is an address conflict.

---

## Arduino Nano Serial Link (UART1)

| ESP32 Pin   | Nano Pin | Notes                                               |
|-------------|----------|-----------------------------------------------------|
| GPIO 16 (RX1) | TX     | Nano TX -> ESP32 RX via a 10 kohm over 20 kohm divider (5 V to 3.3 V). 100 kohm pull-down on the revised board only. The present board has none |
| GPIO 17 (TX1) | RX     | ESP32 TX -> Nano RX through a BSS138 level shifter on the Nano carrier board, with 100 ohm in series and 10 kohm to 5 V on the Nano side, not inverting. See Nano link levels on the carrier board in `hardware/wiring/esp32_pinout.md` |
| GND         | GND      | Common ground is mandatory for UART                 |

On the revised board the pull-down means an unplugged cable reads as a steady low. On the present board the internal pull-up stays on, so a pulled cable reads high and shows as `silent` and never as `line_low`. The serial driver would switch the internal pull-up on for a receive pin, so the revised image calls `gpio_pullup_dis()` on GPIO16 after the port starts. We use `gpio_pullup_dis()` and not `pinMode()` because `pinMode()` can detach the pin from the port. A line that rests low can leave one framing error byte at start-up, so `setup()` drops whatever is waiting and the parser ignores zero bytes and blank lines.

Baud rate: 9600. The Nano sends one telemetry line every 2 seconds. The line format, the checksum, the status bits, the pings sent on GPIO17 and the link states are described under Serial link protocol below. On a checksummed line the status bits say whether a value is usable. A humidity under zero means the Nano may carry a BMP280 with no humidity, so we leave only that out.

---

## STM32 Serial Link (UART2)

| ESP32 Pin    | STM32 Pin | Notes                                              |
|--------------|-----------|----------------------------------------------------|
| GPIO 18 (RX2)| TX        | STM32 TX -> ESP32 RX (both 3.3 V logic - direct). 100 kohm pull-down on the revised board only |
| GPIO 19 (TX2)| RX        | ESP32 TX -> STM32 RX (both 3.3 V logic - direct)  |
| GND          | GND       | Common ground is mandatory                         |

On the revised board GPIO18 is handled the same way as GPIO16 above. It reports as `stm32_link`. Pings go out on GPIO19.

Baud rate: 115200. The STM32 sends vibration and FFT results once per window. See Serial link protocol below for the line format.

---

## Building

We build with PlatformIO. Install it, then run this from the `firmware/esp32/` folder:

```
pio run                      # the present board (esp32dev, the default)
pio run -e esp32dev_revb     # the revised board, which is not built yet
```

`platformio.ini` sets `src_dir = pio_src`, selects the `espressif32` platform with the ESP32 DevKit board and pins every library version in `lib_deps`. Libraries download into the project's own `.pio` folder, which is not committed. A clean build of the libraries prints two warnings from the pinned OneWire library (`extra tokens at end of #undef directive`). They are not in our code.

`esp32.ino` is the program. `pio_src/main.cpp` includes `ota.ino` and `esp32.ino` from the folder above. `build_src_filter` adds the `sensors/`, `outputs/` and `comms/` modules. A build writes its output into the project's own `.pio` folder, which is not committed.

`pio run -e esp32dev_release` and `pio run -e esp32dev_revb_release` build the image for a real hub. They fail to compile until the two trust roots are pasted into `comms/trust_roots.h` and they refuse `ALLOW_PLAIN_HTTP`. `make firmware-check` builds the two ordinary environments, which need no certificate. The kept fuzz is `test_host/fuzz.cpp` (the link parser) and `test_host/corpus_replay.cpp` with its `corpus/` folder, which replays every input that once broke something through the parser and the body builder. The first one is the satellite line that made the body builder cast a double to `long long` out of range (`TEMP:1e30` with a valid checksum). Every float is now bounded before any integer cast and that was the only unbounded one in the firmware.

To upload over USB run `pio run -t upload`. The Nano and STM32 links use their own UART pins, so USB uploads and the serial monitor are not affected by them.

### Two environments, two boards

`platformio.ini` has two environments, one per carrier board.

| Environment | Board | Notes |
|---|---|---|
| `esp32dev` | The first board design | The default. `pio run` builds this |
| `esp32dev_revb` | The revised board | Not built yet. Build it with `pio run -e esp32dev_revb`. Do not flash it to a present board |

The revised board is not built and none of this firmware has run on it. The difference between the two images is the board switches below. On the present board the image keeps the serial receive pull-ups the core switches on and relay 3 stays on GPIO14. The revised image turns the pull-ups off (the board has pull-downs), drives relay 3 from GPIO23 and treats GPIO14 as the sensor supply switch. The firmware checks at boot that the image and the board agree before it ever drives GPIO14 (see Board check).

### Board switches

`config.h` has eighteen switches that say what hardware the hub has. The first ten are the sensors. A sensor that is switched off is never probed, never reported and never a fault and it is never learned at boot, so a hub that lacks one reads as normal and not as a fault. The hub posts the list of what is not fitted once per boot as `not_fitted`. Each can be set from the build (`-DHAS_NANO=0` and so on) because `config.h` only gives it a default when the build has not. `platformio.ini` sets all of them for the two boards. A part that is switched off is never watched and never appears in `faults`. Its forwarded fields are left out of the post.

| Switch | `esp32dev` (present) | `esp32dev_revb` | What it means |
|---|---|---|---|
| `HAS_BME280`, `HAS_MPU6050`, `HAS_INA219`, `HAS_MLX90614`, `HAS_VL53L0X`, `HAS_AS5600` | 1 | 1 | The I2C sensor is fitted. At 0 it is not set up, probed or reported |
| `HAS_DS18B20`, `HAS_MQ2`, `HAS_LDR`, `HAS_MAX4466` | 1 | 1 | The 1-wire probe, the gas sensor, the light sensor or the microphone is fitted. At 0 it is not read or reported. With no temperature source fitted at all the panel does not show `NOTMP` |
| `HAS_NANO` | 1 | 1 | A Nano board is on the UART1 link |
| `HAS_STM32` | 1 | 1 | A Black Pill board is on the UART2 link |
| `HAS_FC28` | 1 | 1 | A moisture probe is on GPIO36. At 0 nothing is read or reported for it, so a hub without one has no standing water warning |
| `HAS_INPUT_MONITOR` | 0 | 1 | The 12 V divider on GPIO39. The present board has none |
| `HAS_SENSOR_RAIL_SWITCH` | 0 | 1 | The sensor supply switch on GPIO14 and relay 3 on GPIO23. At 0 the pin is relay 3 again |
| `HAS_INPUT_PULLDOWNS` | 0 | 1 | 100 kohm pull-downs on both serial receive pins and 0 V on an unplugged microphone or moisture input. At 0 the receive pull-up change and both unplugged checks are skipped |
| `HAS_EXPANDER` | 0 | 1 | The MCP23017 driver is compiled in. At 0 the image carries none of it and its driver never starts. The boot check still probes 0x20 on both images |
| `HAS_PROBE_SERIES_R` | 0 | 1 | A 2.2 kohm resistor in the moisture probe's lead (a board change decided for the revised board). It lets an unplugged probe be told apart from a flooded one |

We built the hub in scratch copies with each of the ten sensor switches off on its own and every pair of them off, plus 200 random combinations of the seventeen switches that existed then. All 255 builds succeeded with no warning from our code. A build with several switches off leaves the code for them out of the image. A switch set on the command line over the one in `platformio.ini` prints a harmless `redefined` notice.

### Board check

On the present board GPIO14 is relay 3 and the firmware drives it. On the revised board it is the sensor supply switch and must never be driven low. `pio run -t upload` builds the present-board image, so nothing else would stop that image going on to a revised board. The revised board is recognised by its MCP23017 at 0x20, which the present board does not have. The check proves the board before GPIO14 is ever driven, in this order.

1. The relay pins other than GPIO14 are driven low and the watchdog is armed.
2. After a warm reset, relays 1, 2 and 4 are restored at once from the saved state. They need no board check. Relay 3 waits for it on the present board, where it is GPIO14. On the revised image relay 3 is GPIO23 and is restored with the others.
3. GPIO14 is made a plain input on both images. Nothing drives it yet.
4. We wait `SENSOR_RAIL_STARTUP_MS` (150 ms) for the sensor rail to start.
5. The bus is started and its two lines are checked for resting high. A line held low means a part is holding the bus.
6. 0x20 is probed up to `BOARD_PROBE_TRIES` (5) times, `BOARD_PROBE_GAP_MS` apart. An answer is proof in itself. If it never answers, the other known addresses are probed to show that the bus works at all.

The verdict has three values. An answer from the expander means the revised board, so the revised image agrees and the present image does not. No answer is believed only when both lines rest high and another device answered. Anything else is UNKNOWN.

| Image | Verdict | GPIO14 |
|---|---|---|
| Present board | OK (no expander on a bus that works) | Driven low as relay 3. Relay 3 is restored then if it was on |
| Present board | MISMATCH (the expander answers) | Never driven |
| Revised board | OK (the expander answers) | Never driven. The sensor supply may be switched |
| Revised board | MISMATCH (no expander on a bus that works) | Never driven. The sensor supply is never switched |
| Either | UNKNOWN (the bus is held low or nothing answers) | Never driven. The main loop probes again on every reading until the verdict is known |

Any doubt means GPIO14 is not driven. On a mismatch or an unknown verdict the hub carries on with everything else. It shows `FAULT: BRD` on the display and the light, prints the reason on the serial monitor and posts `board_check` (`mismatch` or `unknown`) and, for a mismatch, `board_mismatch: true`. The check is only as good as the expander: a revised board whose MCP23017 has failed on a bus that otherwise works looks like a present board to the present-board image, which would then drive GPIO14. Confirm the board verdict on each board before anything else (see the bring-up plan in `firmware/README.md`).

GPIO14 through a reset, from Espressif's ESP32 Series Datasheet version 5.3 (table IO_MUX): the pin (MTMS, pin 17) is output-disabled and input-disabled at reset. After reset it is an input with a weak pull-up (about 75 uA). The datasheet notes say all pins are output-disabled during reset. So the pin is never driven through a reset. It floats during the reset and then has a weak pull-up. We previously said it emits a signal at boot. That claim came from community pinout notes and the datasheet does not support it. Whether a weak pull-up alone can switch relay 3 on the present board depends on the base network of its NPN stage, which our wiring notes do not give. A pull-up of about 75 uA into a transistor with no base pull-down could feed a base current of a few tens of microamps, which a high-gain transistor turns into a few milliamps of collector current. That is under the roughly 70 mA a relay coil needs, so a relay is unlikely to pull in, but a small indicator or a high-gain driver could light. One scope shot of GPIO14 and the relay 3 driver through a reset settles it. Until then relay 3 is not used by any alarm.

### Timing: two tasks

The main loop never waits on the network. Two tasks run.

- The main loop (the Arduino loop on core 1) reads the sensors, judges them, drives the display, the relays and the buzzer. It also builds the telemetry body. It runs on a fixed timer of `TELEMETRY_INTERVAL_MS` (5 s). The timer moves on by whole intervals and nothing that happens in a pass can push the next one back. Handing the body over takes microseconds.
- The post task (core 0, beside the Wi-Fi and TCP/IP tasks) connects Wi-Fi, checks for updates, reconnects when Wi-Fi has been down for a minute and posts. It takes the newest body from a one-slot mailbox. A newer body replaces an older unsent one. We count each replacement. `seq` is taken for every body built, so the backend sees the loss as a gap. After a failed post the task waits 5 s, then 10 s and so on up to 60 s. Starts again after a success. The wait gates the schedule only while it is pending. The gate stores when the failure happened and how long to wait and compares an unsigned elapsed time. The post task asks the gate on every pass, even while Wi-Fi is down, so a pending back-off clears as soon as its wait has passed and is never left to age through an outage. An earlier version kept a stored time of the next attempt and compared it with a signed difference. That comparison turned false once `millis()` was 24.9 days past the stored value, so a hub with no failed post for 24.9 days stopped posting for the next 24.9 days. `test_host/test_post.cpp` runs the schedule across 60 simulated days, with no failure and with one on day 10 and across the 49.7 day wrap. It also runs Wi-Fi outages of 1, 26 and 50 days with a back-off pending when the radio drops. It runs the old schedule too, to show the tests fail on it.

The post has its own wall-clock limit (`POST_WALL_CLOCK_MS`, 20 s). `comms/http_client.cpp` is our own small HTTP client and not the library's. The library's timeouts are gaps between events, so a server that sent a header line every 1.9 s could keep a library post busy for ever and the main loop would stop feeding the watchdog. We resolve the host (a resolved address is kept for `DNS_CACHE_MS` and dropped when a connect fails), connect, send the request in short pieces and read only the final status line. A blank line before the status line is ignored and a 1xx response and its headers are skipped. The request carries a `User-Agent` of `PHAEMOS-hub/` and the firmware version. An address with a control character, a space or a DEL in its host or path is refused, so a request can never be split. The client follows no redirects. A 3xx is a failed post and the serial monitor says so with the status, because a redirect to HTTPS is the likely cause on a misconfigured hub. An `https://` address is posted over TLS (see Posting over TLS below). A plain `http://` address is refused unless the build sets the bench flag `ALLOW_PLAIN_HTTP`. Each step checks the same budget. The one step we cannot interrupt is the pinned core's DNS wait (`WiFiGenericClass::hostByName`), which counts against the budget. With one caller it is at most 15 s. The core can also wait 16 s for a lookup that an earlier caller started.

What the two tasks share and how:

| Shared | How |
|---|---|
| The body | One mutex held only for a copy of the body. The post task posts from its own copy |
| Wi-Fi state | The post task writes the signal strength and then the connected flag into atomics. The main loop reads them and never calls the Wi-Fi API |
| Post counters | Atomics written by the post task. The main loop posts them in `diag` |
| The watch on the post task | Atomics (see Watchdog) |

The post task's stack is `POST_TASK_STACK_BYTES` (12,288 bytes). We sized it from the pinned core's own guidance: its HTTPS examples run the mbedTLS handshake on the Arduino loop task, whose stack is `CONFIG_ARDUINO_LOOP_STACK_SIZE` = 8192 in the core's `tools/sdk/esp32/sdkconfig`. Our client adds a request header buffer and the `String` copies on top of that, so we gave the post task 4 KB more. The loop task has the core's default of 8,192 bytes. We cannot measure either without a board. Both lowest-free-stack figures are posted in `diag` (`stack_post` and `stack_loop`) beside the lowest free heap and the largest free block (`heap_min` and `heap_block`) and the post counters (`post_ok`, `post_failed`, `replaced`, `too_big`), so the first bench session can read them from the serial monitor, which prints them once a minute. The backend does not keep `diag` today.

A slow or dead backend therefore no longer delays a reading, the display, the alarm sounds or the relay. The serial links keep being read. The shaft keeps being sampled. The main loop's own longest pass is about 3 s.

The serial receive buffers are `UART_RX_BUFFER_BYTES` (2,048 bytes each) and not the core's default of 256 bytes (`_rxBufferSize(256)` in the pinned core's `HardwareSerial.cpp`). The Nano sends about 100 bytes every 2 s and the Black Pill 113 to 157 bytes every 1.28 s, so the old default held about two Black Pill lines. A loop pass blocked for more than about 2 s (Black Pill) or 5 s (Nano) therefore dropped bytes, which raised `gaps` and `crc` on a healthy link. That was the old slow post. With the main loop no longer blocking this is an extra margin and not the cure.

The shaft rpm divides by the time its samples actually cover and not by the wall time of the window. A gap between samples longer than `AS5600_MAX_GAP_MS` is left out with its movement, because a fast shaft could have turned more than half a turn in it. A window that covers less than `AS5600_MIN_COVERAGE_PCT` of its length gives no rpm.

Every place that compares against a stored `millis()` value which may be more than 24.8 days old was checked for the same fault:

| Where | What we found | What we did |
|---|---|---|
| The post schedule | A signed comparison against a stored time that only moves on a failure. Broke at 24.9 days | Fixed. The gate stores when the failure happened and compares an unsigned elapsed time and is asked on every pass |
| The reading timer (`nextReadingMs`) | Signed comparison, but the stored value moves every 5 s | Nothing needed |
| The restore deadline | Signed comparison, only used for 10 s after a restore | Nothing needed |
| The post watch (`PostWatch`) | Unsigned differences on values that move every pass or are only read while busy | Nothing needed. The OTA pause has a limit |
| Time since a post succeeded | A stored time would alias after 49.7 days | Kept from a success counter. The stale state is latched until a success |
| Link watch (last valid line, last byte, low run) | Unsigned differences on values that only move on an event | The silent, garbage and `line_low` states are latched until a new line, a byte or a high sample |
| The link failure ring and the sensor flap ring | Failure times only move on a failure | Entries older than their window are forgotten on every call, so a stale one is never compared again |
| The rate window | Advances on every call and now also while a link is dead | Nothing needed |
| Ping timing | Moves every 30 s | Nothing needed |
| Set-up retries (`Recovery`) and the DS18B20 re-search | A stored time of the last try, compared while a set-up is wanted | Aliasing can only delay one retry by up to 10 s. Left as it is |
| The alert repeat (`lastAlertMs`) | Only compared while an alert is sounding. Set when it starts | Nothing needed |
| The "Wi-Fi down" log time | Only moves when it logs | Aliasing can only delay one log line. Left as it is |
| The DNS cache time | Compared on each post, set on each lookup | A host that resolves is looked up again every 10 minutes at most. Aliasing can only add one extra lookup |
| The display and shaft timers | Move every second or every 20 ms | Nothing needed |

### Watchdog

The task watchdog is armed in the hub core's boot, straight after the relay pins are driven low and before the restore and the board check. It has a 15 s timeout (`WDT_SETUP_TIMEOUT_S`) and is fed between the set-up stages, so a library call that never returns during sensor set-up ends in a reset. `setup()` no longer waits for Wi-Fi or the OTA check. Most stages take a few seconds at most. The VL53L0X's bounded polls can take about 10 s on a bus where every transaction times out. At the end of `setup()` the timeout drops to `WDT_TIMEOUT_S` (10 s). The loop's worst legitimate pass is about 3 s, so that is more than three times the worst case.

The ESP-IDF task watchdog has one timeout for every task it watches, so the post task is not subscribed. The main loop supervises it instead and feeds the watchdog only while the post task is healthy. Healthy means the task is not busy in one post for longer than `POST_BUSY_LIMIT_MS` (30 s, which is more than the 20 s wall clock plus one blocking step) and, when idle or backing off, has beaten within `POST_IDLE_LIMIT_MS` (10 s). A stuck post task therefore ends in a watchdog reset of the whole node. An OTA download suspends this supervision for at most `POST_OTA_PAUSE_LIMIT_MS` (5 minutes), so a download that hangs cannot leave the hub silent for ever. The MQ-2 warm-up only compares `millis()`, so it never blocks. A timeout resets the node and shows as reset reason `task_wdt`. Firmware cannot hold a pin through a reset. The watchdog is a recovery and not a protection (see Safety in `firmware/README.md`).

### Set-up protection

The pinned libraries wait in loops that never end once a part stops answering part way through its set-up: `Adafruit_BME280.cpp` line 120 (`while (isReadingCalibration())`) and `Adafruit_MPU6050.cpp` line 158 (`while (device_reset.read() == 1)`). The watchdog turns that into a reset. A part that keeps doing it would have meant a reset loop that hangs in set-up on every boot, with a dark panel and no post. Four measures stop that.

1. A marker in RTC memory names the sensor whose set-up is running. A strike is given only when the reset that follows really was a task watchdog reset, which is what a stalled set-up ends in. A panic, an interrupt watchdog or a software reset that happened to land inside a set-up costs nothing. After a task watchdog reset that finds the marker, that sensor gets a strike and is skipped for this boot. It is reported `missing` and the reason is printed in words. It is retried later on the normal re-init path with the same protection. After `SETUP_MAX_STRIKES` (2) strikes it stays out until the next power-up and is posted by name in `setup_excluded`. A cold start clears the strikes.
2. A strike is forgiven after the sensor has completed a set-up and given good readings for `SETUP_FORGIVE_MS` (10 minutes), so two stalls in a year do not exclude a part that works.
3. The panel, the display, the buzzer and the post task start before any sensor set-up. The panel shows a fault and the display shows `STARTING` until the first judgement. Bodies are built only in the main loop, so a boot that stalls in set-up posts nothing until the watchdog ends the stall with a reset. The marker stops the stall from repeating.
4. We do not patch the pinned libraries. The BME280 and MPU6050 set-ups first run our own bounded checks. The library is called only when they pass. The BME280 status register (0xF3) must read three times in a row and its update bit must clear within 100 ms. The MPU6050 identity and power registers must read three times in a row.

Every I2C set-up and the DS18B20 re-search go through the marker. The DS18B20 re-search is tried at most every `REINIT_MIN_INTERVAL_MS`. `initMQ2` and the display set-up call only bounded code and are not marked.

What is left, library call by library call:

| Call | Can it still block | For how long |
|---|---|---|
| `Adafruit_BME280::begin` (the wait at line 120) | Yes, if the part stops answering in the few milliseconds between our check and the library's own wait | Until the watchdog (15 s at boot) resets the hub. The marker then skips the sensor |
| `Adafruit_BMP280::begin` | It has a `delay(100)` and no wait on a register | About 100 ms |
| `Adafruit_MPU6050::begin` (the wait at line 158) | Yes, if the part stops answering during the reset wait | Until the watchdog (15 s at boot and 10 s at run time). The marker then skips it |
| `Adafruit_INA219::begin` | No wait on a register. Each write is one Wire transaction | A few milliseconds. A Wire transaction times out after about 50 ms |
| `Adafruit_VL53L0X::begin` | The ST API polls are capped at 200 loops, each one Wire transaction | At most about 10 s on a bus where every transaction times out, bounded by the watchdog |
| `Adafruit_MLX90614::begin` | Only creates the bus object | None |
| `DallasTemperature::begin` and `requestTemperatures` | Bounded one-wire scan. The conversion is not waited for | A few milliseconds |
| Our AS5600 code | No wait | A few milliseconds |

### After a reset

A reset returns the relay pins to inputs, so the cooling relay used to stay off for the length of a boot after a watchdog reset during an over-temperature. We keep the judged state in RTC memory that a watchdog, panic or software reset does not clear. After such a reset the hub restores relays 1, 2 and 4 straight after the relay pins are set low, then the rest in the order of the board check.

- What is restored: the per-source critical counts and latches and the commanded state of the four relays. The state is trusted only when its magic word (which carries a layout version) and checksum are right.
- What is not: anything after a cold power-up, a brown-out, the reset pin or deep sleep. RTC memory is not trusted then. The relay starts off as it always did.
- The restored state is held only until a trusted temperature reading from any source confirms it. A confirmed state is handed to the normal judgement. If no trusted reading arrives within `RELAY_RESTORE_CONFIRM_MS` (10 s) it is dropped and the relay goes off.
- Every warm reset is counted until a trusted temperature reading arrives, whatever the relay was doing. A reading from any trusted source clears the count. After `RESTORE_MAX_UNCONFIRMED` (2) the hub stops restoring and is in a reset loop. The saved latches are not restored then. The relay takes its state for no information and the panel and the display show `FAULT: LOOP` first in the list. The post carries `reset_loop: true`. The loop ends the moment a trusted reading arrives. The relay then stays on while any source is over its threshold or still being confirmed.
- The state for no information is one named constant, `COOLING_RELAY_NO_INFO_ON`. We chose on. For a cooling output on is the safe side: the fan or valve runs when it was not needed. Nothing overheats. Set it to 0 only where the cooling load must not run unattended or the hardware does not tolerate it running continuously. A reset loop therefore holds the cooling relay on for as long as it lasts, whatever it was doing before the loop began. With the constant at 1 a refused restore switches relay 1 on during boot, so scope the contacts with no load on them.
- The same memory records that a link has delivered a checksummed line since power-up, which keeps the old line format refused after a warm reset. It also records that the MQ-2 warm-up has completed.
- After a brown-out or power-up nothing is restored, so the relay waits for three readings (about 10 s after the first judgement). The brown-out case where the relay or its load pulls the supply down and restarts the hub is a hardware question for the bench.

`test_host/test_core.cpp` replays a reset loop through the hub core for every relay state and every latch state and the saved-state rules are in `test_host/test_post.cpp`.

### Temperature sources and the cooling relay

`outputs/temp_judge.cpp` judges the over-temperature state from every source the hub has. Each source has its own count and its own latch, so a healthy cool sensor can never cancel a hot one. `test_host/test_temp.cpp` runs the review's sequences, a model check over every combination and random runs.

- A source's count goes up on its own trusted reading over its threshold. Only its own trusted reading under its threshold lowers it. A source that is not trusted on a pass neither raises nor clears anything, so a BME280 that drops one reading in three cannot starve the alarm even when a cool DS18B20 is healthy.
- A latch is set when its count reaches `CRITICAL_CONFIRM_READINGS`. It is cleared only by that source's own trusted reading below its threshold minus `TEMP_HYSTERESIS_C`. A reading past the junk limit is not trusted, so while a latch is set it does not clear it. Critical is any latch set.
- A BME280 reading above its range (over 85 degC and up to `BME_TEMP_OVERRANGE_MAX_C`) from a part that passes its address, identity and control register checks counts as over-temperature for the BME280's count and latch. It is still left out of the post and reported `out_of_range`.
- The DS18B20 contact probe and the MLX90614 object temperature back the BME280 up with their own counts and latches and their own thresholds (`TEMP_CRITICAL_DS18_C` and `TEMP_CRITICAL_MLX_C`). They start at the BME280's 60 degC. A contact probe or an infrared spot on a hot part of a machine may need a higher value, so tune them on the machine. This is unproven. The warning level follows the BME280 alone.
- A latch is held across any length of untrusted passes. When no source is trusted at all the over-temperature alarm is unavailable and the panel shows `FAULT: NOTMP`. The panel says critical when it is critical, whatever else is wrong.
- The counts and the latches are in the saved state, so a reset does not lose a confirmation that was under way.

A consequence: a BME280 that was critical and is then lost stays critical until its own trusted reading clears it, however healthy the other sensors are. That is deliberate. It means a lost BME280 never cancels a critical state and the cooling relay stays on. It also means the relay stays on while the BME280 is lost until it comes back and reads cool.

### The panel

The light, the strip and the display follow this precedence, highest first.

1. `CRITICAL`: a confirmed critical temperature. It always wins and never alternates, so a critical machine condition is never hidden.
2. `WARNING`: a warning temperature, gas or water.
3. `FAULT`: any fault. Any sensor or link in a fault state, the gas alarm not being available (warming up or unplugged), the over-temperature alarm not being available, a board mismatch or unknown board, a reset loop or no successful post for `POST_STALE_MS` (5 minutes).
4. `NORMAL`.

When a warning and a fault both exist and nothing is critical, the light, the strip and the display alternate between them on every reading, so neither hides the other. The sound follows the highest level and does not alternate, so it does not beep on every flip. The fault text lists what failed as short codes, most important first and fits the row (17 characters). Only whole codes are shown and a `+` marks a longer list. The codes in order are `LOOP` (reset loop), `NOTMP` (no trusted temperature source), `MQ-2`, `WARM` (gas warm-up), `TEMP` (BME280 lost, dropped when `NOTMP` is shown), `PRB` (probe unplugged), `BRD` (board check), `PLN` (plain HTTP bench mode), `CTR` (the server answered 409: an admin has to accept a new counter) and `NET` (no post for `POST_STALE_MS` or the backend answered 401 or 403) and `SENS` (any other fitted sensor or link). A sensor that is built out with its `HAS_` switch never shows. A fitted sensor that is missing shows `SENS`.

Two design choices to state plainly. Gas and water are `WARNING` level: amber, two beeps every 30 s and no relay. Only a confirmed over-temperature is `CRITICAL` and switches the relay. And the gas alarm is not available for the first 180 s after every power-up or brown-out, so the panel shows `FAULT: WARM` for the whole warm-up.

### Failed sensors and fault reporting

Sensors that fail to start are logged on the serial monitor and left out of the telemetry. The boot carries on without them. Every I2C sensor is probed on the bus before each read. The BME280, MPU6050 and VL53L0X identity registers are checked as well. A sensor that has dropped off is left out. So is a BME280 temperature outside -40 to 85 degC. Each is logged once in words. The BME280 socket also accepts a BMP280, which has no humidity, so `humidity` is left out in that case.

One small health table (`sensors/health.h`) holds a state and a since time for each sensor key. The read functions update it and the post reads it. A sensor in a fault state has its readings left out of the post. The states are:

| State | Meaning |
|---|---|
| `missing` | No I2C acknowledge, no 1-wire presence or a wrong identity register, three probes in a row. Also a sensor that answers but fails its set-up or one skipped after a stalled set-up |
| `intermittent` | Three failed probes inside a minute that never run three in a row. Also a Black Pill that sends no complete window, a satellite status bit that comes and goes (set on three or more of the last ten lines and not set on two in a row right now, which is then its debounced fault state) and a link that loses more than a fifth of its lines. Readings that come and go always come with this reason |
| `out_of_range` | Outside what the part can report. Also a sensor whose registers show it has reset or lost its magnet |
| `warming_up` | The MQ-2 during its heater warm-up |
| `unplugged` | The microphone or moisture input reads at or near 0 V |
| `line_low` | A serial receive line rests low with no byte (cable out or far end unpowered) |
| `silent` | A serial receive line idles high and no valid line has arrived |
| `garbage` | Bytes keep arriving on a link but no line has passed its checksum |
| `one_way` | Lines arrive but the satellite never answers a ping |
| `stuck` | A satellite reports that its sensor value is frozen |
| `stale` | The node cannot say: nothing fresh has been read. Used only for the expander and the seven rails on the revised board |

The keys are `bme280`, `mpu6050`, `ina219`, `mlx90614`, `vl53l0x`, `as5600`, `ds18b20`, `mq2`, `ldr`, `max4466`, `fc28`, `nano_link`, `stm32_link`, `supply`, `nano_bme280`, `nano_supply` and `stm32_mpu6050`. The revised image adds `expander`, `aux_rail`, `feed1_rail`, `feed2_rail`, `feed3_rail`, `sens_rail`, `strip_rail` and `enable_rail`. They are never set on the present board, so its faults map and its `not_fitted` list are as they were. On the revised image a rail is `stale` whenever the node cannot say (see Port expander on the revised board). The supply is `out_of_range` when the 12 V input reads under 9 V or over 15 V. The hub detects `stuck` only on its own BME280 or BMP280. The 8 raw data words are read and compared and 24 identical reads in a row (2 minutes) mean a frozen part. The part is read at the library's default oversampling of x16, so its own noise moves the low bits and a repeat of 24 is not credible from a working part. That reasoning is the same as the Nano's and the noise figure is not measured. A stuck reading is left out and reported `out_of_range`. Every other hub sensor has no stuck test. The satellites' `stuck` bits are passed on.

The MQ-2 has its own rule, because its digital output is pulled high by the board and an unplugged module would otherwise look like clean air. After the warm-up an analogue reading under `MQ2_FAULT_ADC_MAX` is a fault whatever the digital line says. The gas alarm is not available. The warm-up and the fault both show on the panel and the display. The digital alarm level is the potentiometer on the module and the analogue level is `GAS_ANALOGUE_ALARM_COUNTS` (see sensor 7). We deleted the unused `GAS_WARNING_LEVEL` and five other thresholds in `config.h` that nothing read.

The moisture input is the one place where a fault must not hide an alarm. Without the series resistor an unplugged input and a probe flooded with a conductive liquid read the same on this circuit, so the leak alarm wins. `fc28: unplugged` withholds `moisture_level` only. `water_detected` is still posted. The backend alarms on it. With the series resistor (`HAS_PROBE_SERIES_R`, the revised board) an unplugged probe reads about 0 V and a flooded one about 0.6 V, so they are told apart. A reading at or under `PROBE_UNPLUGGED_MAX_COUNTS` is unplugged and never an alarm. Only a real flood raises it. A hub with no probe sets `HAS_FC28` to 0.

THE WATER ALARM IS UNPROVEN. `WATER_THRESHOLD` is 2,000 counts and it is worked out and not measured. The old value of 500 counts (about 0.4 V) was on the wrong scale. The arithmetic is in `config.h`. The Nano's wiring note puts a probe in water at 300 to 400 of 1023 on a 5 V circuit, which is 29 to 39 per cent of the supply. On the hub's 3.3 V circuit that is 0.96 to 1.29 V, about 1,270 to 1,700 counts. The Nano's own threshold of 500 of 1023 is about 2,130 counts. A damp probe is about 2,180 to 3,040 counts and a dry one about 3,950. So 2,000 sits under the Nano's equivalent and above the in-water band. The hub says at boot, on the serial monitor and on the splash screen, that the water alarm is unproven. `WATER_ALARM_PROVEN` stays 0 until the threshold has been measured on a real probe.

#### Getting a sensor back without a reboot

Any failed probe marks a sensor's set-up as lost. The next probe that succeeds runs that sensor's set-up again before the sensor is read, so a short power dip that resets a part and leaves its address unchanged is recovered. A set-up is tried at most every `REINIT_MIN_INTERVAL_MS` per sensor, so a part that flaps cannot hold the loop. A part that answers but fails its set-up is reported as `missing`. Every I2C set-up and the DS18B20 re-search are marked in RTC memory (see Set-up protection).

A part that has reset can keep answering with the right identity and then return a plausible constant. This table says what each hub sensor reads as after a reset and how the firmware now tells.

| Sensor | Reads after a reset | How the firmware tells |
|---|---|---|
| BME280 | Sleep mode. The data registers hold the reset word. The driver returns NAN | `ctrl_meas` (0xF4) mode bits read 0. NAN also triggers it |
| BMP280 | Sleep mode. The driver compensates the reset word into about 26 degC and 820 hPa, which looks real | `ctrl_meas` (0xF4) mode bits read 0. We read the register on every pass and do not rely on the reading. A NAN pressure also triggers it |
| MPU6050 | Sleep bit set and all axes read zero | The sleep bit in register 0x6B. All three axes exactly zero also triggers it. A working part always sees gravity on one axis |
| INA219 | Configuration 0x399F (the range we use is the same) and calibration 0. The library writes the calibration again on every current read, so the part recovers by itself | The calibration register (0x05) reading zero logs the loss. The overflow bit (register 0x02) marks current and power as unusable |
| MLX90614 | Keeps its settings in its own memory. Nothing plausible and constant | A bad reading for `CONTENT_REINIT_PASSES` passes triggers one new set-up |
| VL53L0X | Needs its full set-up again. Ranging returns an error or a stale value | Only the driver's error return and range status 5, which trigger a set-up. The pinned library sets no register that we could read back to show a reset, so a part that ranges without error after a reset would not be noticed. This is unproven without a board |
| AS5600 | Defaults, which are the settings we use. Nothing is lost | Not needed. The status register (0x0B) must show the magnet detected. A marginal gap is only logged |
| DS18B20 | Holds exactly 85.0 degC until its first conversion ends | An exact 85.0 that is not within `DS18_POWER_ON_NEAR_C` of the reading before it is not believed. A real 85.0 reached by a rising temperature is |
| MQ-2 and the analogue inputs | No reset state | Not applicable |

Calling an init again is safe when the part answers. The Adafruit `begin` calls delete the old bus object first and the INA219 reuses its own. A part that stops answering part way through an init is a different case (see Set-up protection).

A lost temperature sensor shows as `FAULT: TEMP` on the display, lights the amber LED and never switches the cooling relay on by itself. A dead MQ-2 5 V rail shows as `FAULT: MQ-2` and leaves `gas_level` and `gas_alert` out of the telemetry, as does the warm-up. The cooling relay switches on when a source has `CRITICAL_CONFIRM_READINGS` over-threshold trusted readings (default 3, one reading every 5 s) and switches off once every source that latched is `TEMP_HYSTERESIS_C` below its threshold on its own trusted reading.

### Port expander on the revised board

> [!IMPORTANT]
> No revised board has been made. This driver has run only against a scripted chip in the host tests. Every timing figure is chosen and not measured.

The revised image (`HAS_EXPANDER` 1) starts a driver for the MCP23017 once the board check has found it. The present image carries none of it and its driver never starts. The boot check still probes 0x20 up to five times on both images to tell the boards apart. The driver reads seven rail inputs (AUX_OK, FEED1_OK to FEED3_OK, SENS_OK, STRIP_OK and ENABLE_OK) and the push button by polling, because no interrupt line reaches the module. It makes one two-byte read every 20 ms and a full register read-back every second. A call to it makes at most 19 transfers when it reconfigures the chip and at most 3 otherwise and in any ten seconds it costs the loop at most 500 ms (5 per cent), checked by simulating failure patterns and based on a Wire time-out of 50 ms that is not measured. The pin table, the start sequence, the input thresholds for each rail and the band where each input is undefined are in `sensors/README.md`.

Six of the rail inputs are active low (a transistor with a pull-up) and SENS_OK is active high. Present means the rail is up. It does not mean the rail is in range: the `supply` reading and the `ina219` reading tell that. The thresholds are estimates, measured at bring-up.

What it adds to the fault reporting. Silence never means up. A watched rail is `ok` only from a fresh reading. While the expander is not running and trusted (never started, not answering, not trusted or waiting to be read again), before a rail has been read or when the last good reading is older than 2 s, every watched rail is posted `stale`. An absent rail is `missing` and a rail near its threshold is `intermittent`, each said once in words on the serial monitor with the time it began. The sensor rail is called present only while a cable sensor on it has also answered, because SENS_OK can be held high through the I2C pull-ups with the rail off. The chip itself is `missing` when it does not answer or the bus is stuck, `out_of_range` when a register read back differs from what was written and `stale` when it was never started. A reset of the chip (a brown-out) is found by the read-back, written again and counted. None of this stops the sensors or the post. The counters and how long the rails have been unknown are on the once-a-minute `expander:` line of the serial monitor and not in the post.

After the sensor supply is power-cycled the firmware checks that SENS_OK reads high again within 300 ms. The check is judged on the polls the loop makes anyway and does not hold it. It never waits for the input to fall, because the pull-ups can keep it high while the switch is off.

The button's long press (5 s in the first 30 s after a power-up) clears the stored credentials. A warm reset does not open that window. A short press is only logged. A press counts only after a release has been seen since the driver started or came back.

The telemetry body is unchanged. On the revised image the body and document limits are 256 bytes larger (`TELEMETRY_BODY_MAX_BYTES` 2304 and `TELEMETRY_DOC_BYTES` 3328), because the faults map can hold eight more entries.

### Serial link protocol

Each satellite sends one line per window in the shape `<body>*<CCCC>` followed by CR LF. `<CCCC>` is four upper-case hex digits of CRC-16/CCITT-FALSE over the body (polynomial 0x1021, start 0xFFFF, no reflection, no final XOR). A line is at most 160 bytes including CR LF. The body is `KEY:value` pairs. After the node's own readings every data line carries `ST` (a status bit mask), `SEQ` (lines sent since boot, wrapping at 65535) and `UP` (seconds since boot). The Nano line also carries `VCC` in millivolts. The Black Pill line also carries `RMS`, `PK`, `MT`, `RF` and `BR`. Counters said to be "since boot" are since the hub's power-up or reset, whichever was last.

The parser, the CRC and the counters live in `comms/link_protocol.cpp`. It has no Arduino types, so `test_host/test_link.cpp` covers it. `comms/serial_parser.cpp` only moves bytes into it.

- A line with a correct checksum is parsed. A wrong, short, lower-case or missing checksum counts as an error and the line is dropped.
- The old format (no `*`) is accepted only while no checksummed line has been seen on that link since power-up. It is parsed strictly: the keys in their exact order, nothing after the last one and numbers in their plain form. A single bit error cannot turn a checksummed line into an old one. A line that loses its tail can: a checksummed line cut off after its last old-format key is a valid old-format line. `test_host/fuzz.cpp` shows how often a damaged line is accepted while that window is open. The window is one line long at a cold boot. The first checksummed line closes it for good. That fact is kept in RTC memory, so a warm reset keeps it closed. A cold power-up reopens it.
- The checksum is 16 bits. A line damaged beyond the 1, 2 and 3 bit errors it is guaranteed to catch passes about one time in 65,536. `test_host/fuzz.cpp` counts the damaged lines it accepts with a different reading and prints the figure on each run.
- On a checksummed Nano line the status bits decide whether a value is usable and never the value. A real -1.0 degC is a reading. The `-1` form is believed only on an old-format line. A humidity under zero still means no humidity element.
- A status bit becomes a fault only when it is set on two lines in a row. The values on the line itself are left out at once, so one glitch line withholds a reading but does not raise a fault. A bit set on three or more of the last ten lines is `intermittent` for that part, unless it is set on two lines in a row right now. Then the debounced fault shows instead, so flapping is reported as soon as it is seen and never late.
- A sequence jump is counted as a gap. A restart needs `SEQ` to have gone back (or stayed the same) and either `UP` to have gone back too or both numbers to be small. The Black Pill sends no line for a window dropped by a single failed read. `SEQ` counts lines sent, so one missing line is not a gap.
- The hub sends `PING:<n>` every `LINK_PING_INTERVAL_MS` on GPIO17 and GPIO19 and expects `PONG:<n>*<CCCC>` back. Writing it never blocks. A late pong is accepted until the next ping. The 500 ms window only starts the count of unanswered pings. Pings missed while the link was dead do not count against it when it comes back.
- Status bits become entries in `faults`. A reset bit is information only.

| Satellite bit | Key | State |
|---|---|---|
| Nano BME_MISSING or BME_ASLEEP | `nano_bme280` | `missing` |
| Nano BME_STUCK | `nano_bme280` | `stuck` |
| Nano BME_RANGE | `nano_bme280` | `out_of_range` |
| Nano SUPPLY_RANGE | `nano_supply` | `out_of_range` |
| Black Pill SENSOR_MISSING or ID_MISMATCH | `stm32_mpu6050` | `missing` |
| Black Pill SENSOR_STUCK | `stm32_mpu6050` | `stuck` |
| Black Pill NO_DATA | `stm32_mpu6050` | `intermittent` |
| Black Pill CLIPPING | none | Not a fault. See below |

Clipping means the vibration is stronger than the sensor's range, which is the reading that matters most. The hub forwards every Black Pill value while CLIPPING is set and posts `vib_clipping: true`. It posts `false` otherwise and leaves it out when the link is down. A satellite reading whose bit marks it missing, stuck or without data is left out of the post. For the Nano that is the three BME280 values. For the Black Pill it is every vibration field.

Link states are checked in this order. Nothing is reported until a link has had `LINK_SILENT_MS` since the end of the set-up, so a normal restart raises no link fault.

1. `line_low`: the receive line has rested low for `LINK_LINE_LOW_MS` with no byte. It stays latched until a byte or a high sample, so the 49.7 day `millis()` alias cannot clear it.
2. `garbage`: no valid line for `LINK_SILENT_MS`, bytes keep arriving and at least three lines failed in that time. A stream with no line end (the wrong baud rate) counts again for every 159 bytes, so it reads as `garbage` and not `silent`.
3. `silent`: no valid line for `LINK_SILENT_MS` and no such failures. The state stays latched until a new valid line, so a `millis()` rollover cannot make a dead link look live. The link's reading is dropped when it is declared dead.
4. `one_way`: lines arrive but `LINK_ONE_WAY_PINGS` pings in a row got no pong. An old-format satellite cannot answer, so it is never called `one_way`.
5. `intermittent`: more than a fifth of the lines expected over the last minute were lost (a sequence gap) or failed a check, with at least `LINK_RATE_MIN_LINES` expected.
6. `ok`.

`garbage` is checked before `silent` because it is a link with no valid line and bytes still arriving.

### Posting over TLS

The hub posts to an `https://` address over TLS with the certificate checked. The documented deployment puts the API behind Certbot (Let's Encrypt) with a redirect to HTTPS and a plain `http://` post would get that redirect and fail.

- **Trust.** The connection is verified against two pinned roots, ISRG Root X1 and ISRG Root X2, compiled in from `comms/trust_roots.h` through `setCACert()`. The hub's own post path never calls `setInsecure()` in any build. (The dormant update code in `ota.ino` uses the core's `HTTPClient`, which calls `setInsecure()` for an `https://` address that has no certificate given. That code cannot be compiled into a release build and a bench build of it must allow plain HTTP, so it is honest about being a plain path. See Firmware updates over the air.) If a bench has no certificate the only way to post is plain `http://` behind the explicit bench flag `ALLOW_PLAIN_HTTP`, which is not a TLS connection that verifies nothing. The certificate chain is verified against the host name and the pinned roots by mbedTLS, so the address has to use a name and not a bare IP address. An `https://` address with an IP address is refused.
- **Dates and protocol version are checked by the hub, not by the core.** The pinned core's mbedTLS is precompiled with `CONFIG_MBEDTLS_HAVE_TIME_DATE` unset (`tools/sdk/esp32/sdkconfig`, line 1440). We confirmed on the built `firmware.elf` with the toolchain's objdump that `mbedtls_x509_time_is_past` and `mbedtls_x509_time_is_future` are each `movi.n a2, 0; retw.n`, so the handshake never looks at a certificate's dates. Without a check of our own an attacker on the path who held the private key of any certificate ever issued for the API's name under the pinned roots could present it for ever. So after the handshake succeeds and before any header or the key is written, the hub walks the chain the server presented (`getPeerCertificate()` returns the peer's chain and `->next` reaches the intermediates) and refuses the post unless the clock lies inside `valid_from` to `valid_to` of every certificate in it, both ends included. A chain of more than ten certificates is refused outright and never cut short, so a padded chain cannot hide an expired certificate past the limit (`comms/tls_checks.cpp`, host tested). It also refuses unless TLS 1.2 was negotiated. What is not checked: the dates of the pinned roots, because a root is not in what the server presents. They expire in 2035 and 2040 and are rechecked whenever an image is rebuilt. The core's mbedTLS also negotiates TLS 1.0 and 1.1 (`CONFIG_MBEDTLS_SSL_PROTO_TLS1` and `TLS1_1` are set) and has no TLS 1.3 and its `WiFiClientSecure` has no call to set a minimum, so a downgrade is refused after the handshake and before anything is sent. The hub speaks TLS 1.2 only. The server has to keep TLS 1.2 enabled. The alternative to our own checks is a custom build of the core with `CONFIG_MBEDTLS_HAVE_TIME_DATE` on and the minimum version set in `ssl_client.cpp`. That means rebuilding the Arduino core (an ESP-IDF toolchain and a long build) and keeping a fork. We have not done it.
- **The two roots are placeholders until the owner pastes them.** We did not write a certificate from memory. A release build (`pio run -e esp32dev_release` or `-e esp32dev_revb_release`) fails to compile with a message until both PEMs are pasted. A default build compiles and then refuses every TLS post at run time while a placeholder is there. The pinned core ships no certificate bundle file that can be checked offline: its `WiFiClientSecure` library has the bundle code and the data is not a file in the package. So the owner takes each PEM from the issuing authority's own page. The steps are in `comms/trust_roots.h` and in "What the owner does" below.
- **Time.** The certificate dates are checked against the clock, so the post task sets the clock by SNTP before the first TLS post. The main loop never does. A round of asking lasts `TIME_SYNC_WINDOW_MS` (15 s). After a round with no answer it waits 10 s and doubles that up to 5 minutes before asking again. While the clock is unset no TLS post is tried, nothing is taken from the mailbox (newer bodies replace older ones), the panel shows `FAULT: NET` after `POST_STALE_MS` and the alarms and relays carry on. A clock counts as set once it is not before the date this image was built (`__DATE__` or the build flag `TIME_FLOOR_EPOCH`). A hub flashed long after it was built has a floor that is only a lower bound. The floor never rejects a right clock and the certificate dates do the real work. SNTP is not authenticated. A network attacker can choose any time after that date, so they could make a certificate that has expired look valid. That is a limit of SNTP and not something this firmware closes. We do not use the server's `Date` header as a clock source. It arrives inside the very connection that needs the clock, so the handshake it would help has already failed before it can be read and a header from an unverified server is not a source to trust.
- **Time budget.** The whole post, handshake included, still fits the 20 s wall clock (`POST_WALL_CLOCK_MS`). After the lookup the client plans the rest: the TCP connect gets at most 2 s, the handshake at most `HTTP_TLS_HANDSHAKE_MS` (8 s) and 3 s are kept for sending the request and reading the status line. When too little time is left after a slow lookup the post is not started. `test_host/test_http.cpp` checks that the phases always fit the budget. The handshake on this chip is documented at roughly one to three seconds. We have not measured it. The hub prints the measured time after its first post and every 60 posts, with the lowest free heap, so the first bench session can read it.
- **Heap.** A TLS session in the pinned core uses two 16 KB record buffers (`CONFIG_MBEDTLS_SSL_MAX_CONTENT_LEN` = 16384 in its sdkconfig) and the parsed certificates, which is roughly 40 to 50 KB of heap while it is open. That is an estimate from the configuration and not a measurement. The hub keeps one session at a time and frees it after every post (the client object goes out of scope and `stop()` releases the context). We chose a new session per post over keeping one alive, because a kept session holds that block for weeks, which is the fragmentation risk the review raised and the server would close an idle connection anyway. The price is a handshake on every post. At one body every 5 s a handshake of one to three seconds is a large share of the post task's time on core 0 and on a slow link bodies will be replaced. `diag.heap_min` and `diag.heap_block` show whether the heap holds up over weeks.
- **Flash.** TLS and the checks that go with it (the date and version checks, the response reader, provisioning and the one-record credential store) added 163,964 bytes of flash to the present-board image (886,249 to 1,050,213 bytes, now 80.1% of the 1,310,720 byte application partition). RAM at build time rose by 2,568 bytes (58,732 to 61,300).
- **Responses.** A 429 waits at least the server's `Retry-After` (seconds only, capped at one hour) and never less than the normal back-off. A 401 or a 403 means the key is wrong and retrying will not fix it, so the hub tries again once in ten minutes (`POST_AUTH_RETRY_MS`) and shows `NET` at once. A 404 means the address is wrong (a trailing slash, a wrong path or the wrong host). The hub says so on the serial monitor, shows `NET` at once and tries again once in ten minutes, as for a rejected key. Any other failure backs off 5 s doubling to 60 s.
- **Plain mode.** `ALLOW_PLAIN_HTTP` is off by default and a release build refuses it. When a hub does post to an `http://` address the panel shows `PLN` and the post carries `plain_http: true`. A default build with compiled secrets fails to compile unless its `API_URL` starts with `https://`.

What the owner does, once:

1. Download ISRG Root X1 and ISRG Root X2 as PEM from https://letsencrypt.org/certificates/ (the issuing authority's own page, over HTTPS).
2. Compare each file's SHA-256 fingerprint with the one the same page publishes: `openssl x509 -in file.pem -noout -fingerprint -sha256`, character by character.
3. Note the expiry: `openssl x509 -in file.pem -noout -enddate`. X1 expires in 2035 and X2 in 2040.
4. Paste each PEM into its slot in `comms/trust_roots.h` and delete its `TRUST_ROOT_..._PLACEHOLDER` line.
5. Build with `pio run -e esp32dev_release` (or `-e esp32dev_revb_release`).

### Provisioning a hub

No secret is compiled into the image. A hub keeps its Wi-Fi network and password, the API address, its device id and its device key in its own flash and reads them from there on every boot. One image fits every hub.

1. Flash the image. The hub runs its sensors, panel and relays at once. With nothing stored it never touches the radio, posts nothing and prints `Not provisioned` on the serial monitor.
2. Connect at 115200 baud and send these lines, one per line, in any order: `SSID <name>`, `PASS <password>`, `URL https://<host>/api/v1/telemetry` (no slash at the end: the server answers 404 for `/api/v1/telemetry/`, so the hub refuses an address that ends in one and says why and the same rule applies to `tools/provision.py` and to `API_URL` in `secrets.h`), `ID <device id>`, `KEY <device key>`. `PASS` on its own is an open network. `SHOW` lists what is set. It shows the network name, the address and the id and only says whether the password and the key are set. Every reply is short and none ever repeats the password or the key. A rejected value says what the rule is and not what was sent. The console takes at most 256 bytes and handles one line per pass of the main loop and writes an error reply at most once a second, so a flood of lines cannot hold the loop.
3. Send `SAVE`. The hub refuses until all five are set and valid, stores them as one checksummed record in one write (a reset part way leaves either the old five values or the new five and never a mixture), reads them back, wipes its copy and restarts. `CLEAR` forgets everything and restarts. `HELP` lists the commands.
4. `tools/provision.py` does the same and asks for the password and the key without echo. It needs `pyserial` in your own environment. A terminal program works too, but most echo what you type on your own screen, so type the key where nobody is looking and clear the terminal's scrollback.
5. To clear a hub at the bench hold the BOOT button (GPIO0) for 5 seconds during the first 30 seconds after power-up. Do not hold it while pressing reset: GPIO0 low at reset starts the bootloader. On the revised board the push button is on the port expander (GPB0). Holding it for 5 seconds in the first 30 seconds after a power-up does the same clear. A warm reset does not open that window (see Port expander on the revised board). It counts only after the button has been seen released since the driver started.

For a bench build that must carry its values: copy `secrets.example.h` to `secrets.h`, fill it in and build with `-DUSE_COMPILED_SECRETS=1`. `secrets.h` is never tracked and the owner has to add a line for it to the repository's `.gitignore`. A build that still has a placeholder fails with a message naming it. The core's own copy of the Wi-Fi password is switched off (`WiFi.persistent(false)`). A hub that ran older firmware may still hold a copy the old core wrote. Erase its flash once (`esptool.py erase_flash`) before provisioning. An erase also wipes the boot counter, so the hub starts again at boot 1 and the server will answer 409 until an admin accepts a new counter for that machine in the dashboard (the "accept a new counter" action). The core also erases the whole non-volatile partition by itself if it runs out of free pages, which has the same effect.

What this protects: no secret is in the tracked source or in a built image, one image fits every hub and a careless `git add` cannot publish a password. What it does not protect: the flash is not encrypted. Anyone who holds the hub can read the stored password and key with `esptool.py read_flash`. Only flash encryption and Secure Boot stop that and they are one-way hardware settings this firmware does not use (see Safety in `firmware/README.md`).

### Boot and sequence numbers

The backend refuses a post whose `(boot, seq)` is not newer than the last it saw for the machine. The hub makes sure the pair only ever goes up.

- `boot` is a counter in non-volatile storage, raised once per boot (a warm reset counts as a boot). It is read with `nvs_get_u32` directly, because `Preferences::getUInt` returns 0 for a read error as well as for a counter that was never written. It is raised, written, committed and read back before the first post.
- `seq` is a counter in RAM raised for every body built, including one that is later replaced before it is sent. It restarts at 0 on each boot and the pair still goes up because `boot` has.
- If the boot counter cannot be read (a storage error), cannot be written or read back or is at its limit, the hub builds no bodies at all. A counter that is not found counts as a first boot only on a hub with no stored credentials. On a hub that has stored credentials a missing counter means it was lost and a boot that restarted at 1 would be refused by the server, so the hub builds no bodies then either. It sends no guessed `boot`. The alarms, relays, panel and display do not depend on it. The panel shows `NET` after 5 minutes.
- At its limit `seq` does not wrap. The hub stops building bodies until the next boot raises `boot`. At one body every 5 s that takes about 680 years.
- A 409 means the server has seen a newer `(boot, seq)` from this machine, for example after a storage wipe. The hub says so on the serial monitor and shows `FAULT: CTR` on the panel and tries again once in ten minutes, as it does for a rejected key. **An admin has to accept a new counter in the dashboard (the "accept a new counter" action) for that machine.** An exact repeat of the last accepted pair is answered 200 with `status: duplicate`, which the hub counts as delivered.
- `test_host/test_rules.cpp` runs 300 simulated boots with resets after any number of bodies and storage failures and checks every pair is new and greater than the one before.

### Posted node information

Each post carries these extra fields. The backend treats them as optional.

| Field | Type | Meaning |
|---|---|---|
| `seq` | integer | Rises by one for every body built. A body that is replaced before it is sent still takes a number, so a gap shows the loss. Kept in RAM |
| `boot` | integer | Boot count kept in non-volatile storage and raised once per boot. Left out if storage does not open |
| `up` | integer | Uptime in seconds |
| `faults` | object | Maps a sensor key to a state. Empty when all is well |
| `links` | object | Per fitted link counters: `ok`, `crc`, `fmt` (lines that passed their checksum but did not parse or ran too long), `gaps` and `restarts`. `st` and `up` (plus `vcc` for the Nano) are present only while the link delivers lines, so they are never stale |
| `diag` | object | For the first bench session: `post_ok`, `post_failed`, `replaced`, `too_big`, `stack_post`, `stack_loop`, `heap_min` and `heap_block`. The backend schema does not keep it today, so the hub also prints the same counters on the serial monitor once a minute. Read them there |
| `board_mismatch` | boolean | Present, as `true`, only when the image and the board disagree about GPIO14. The backend schema does not keep it today |
| `board_check` | string | `mismatch` or `unknown`. Left out when the board check is `ok` |
| `reset_loop` | boolean | Present, as `true`, while the hub is in a reset loop |
| `plain_http` | boolean | Present, as `true`, only when the hub posts over plain HTTP (a bench build) |
| `setup_excluded` | array | The sensors (`bme280` and so on) whose set-up is left out until power-up, by name |
| `not_fitted` | array | The sensors this image is built without. Sent once per boot, in the first body |
| `reset_reason` | string | From `esp_reset_reason()`, such as `poweron`, `brownout`, `task_wdt` or `panic` |
| `rssi` | integer | Wi-Fi signal in dBm. Left out while Wi-Fi is down |
| `heap_free` | integer | Free heap in bytes |
| `fw` | string | `FIRMWARE_VERSION` |

The Black Pill values `vib_rms_x`, `vib_rms_y`, `vib_rms_z`, `vib_peak`, `stm32_vib_x`, `stm32_vib_y`, `stm32_vib_z` and `vib_clipping` are forwarded beside `fft_peak_hz` and `vib_magnitude`. Floats are rounded to a sensible number of decimals (two for temperatures and pressure, three for acceleration and voltage, one for humidity, current and the shaft). A float posted as it is would print nine digits.

There is no `ts` field, because the hub has no synchronised clock. The JSON document holds `TELEMETRY_DOC_BYTES` (3072) and the serialised body must stay under `TELEMETRY_BODY_MAX_BYTES` (2048). `test_host/worst_json.cpp` calls the same body builder as the firmware with every field at its longest and measures it: about 1,430 bytes with one fault and about 1,840 bytes with every key faulted at once, which cannot happen because a faulted sensor drops its readings. A body that would not fit is dropped and counted with a serial warning and is never sent cut short.

### Firmware updates over the air

The update path stays off. `OTA_ENABLED` is guarded with `#ifndef` so the switch is real, it is 0 and turning it on is a compile error. It cannot be part of a release build at all (`PHAEMOS_RELEASE`). It needs the bench flag `OTA_UNSIGNED_BENCH_ONLY`, compiled secrets and `ALLOW_PLAIN_HTTP` and its `API_BASE_URL` has to start with `http://` or `https://` and not be the placeholder. It needs `ALLOW_PLAIN_HTTP` because it uses the core's `HTTPClient`, which calls `setInsecure()` for an `https://` address that has no certificate given, so even an `https://` base address would verify nothing there. It is a plain path whatever the address says. The code in `ota.ino` fetches over plain HTTP, compares only a version number and checks no signature, so anyone who can answer the hub's request could have it flash any image, with the four relays and the stored key in reach of that image. It has also never run in its new place in the post task and its read loop may starve the idle task's watchdog on core 0.

Before it is ever turned on all of this has to exist:

1. TLS with the pinned roots for the version request and for the image download.
2. Images signed offline (Ed25519 or ECDSA P-256) with the public key compiled in and the private key kept off the server.
3. The signature and the hash checked before the image is activated and not the hash the server sends.
4. The version inside the signed data, so an old signed image cannot be replayed as a newer one, with a cap on the size of the version reply.
5. Rollback to the old image unless the new one makes its first good post and anti-rollback set in the SDK configuration.
6. No secret in the image (done: provisioning), so one signed image fits every hub.

We have not built signing in this round. When the check is on, the main loop stops supervising the post task while the download runs, for at most `POST_OTA_PAUSE_LIMIT_MS` (5 minutes).

### Telemetry fields

Every existing field and key is unchanged. Telemetry field names follow the backend schema. Acceleration is sent as `vibration_x/y/z` and gyro as degrees per second. The Nano values go out as `nano_temp`, `nano_hum`, `nano_pres`, `nano_light`, `nano_moist` and `nano_water`, which the backend schema already has. The MQ-2 warm-up is skipped after a warm reset only when the saved state says it had finished, because the heater is still hot then.
