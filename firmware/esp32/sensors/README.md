# ESP32 Sensor Modules

Each sensor has a `.h` header and `.cpp` implementation. Include the header in `esp32.ino` and call `init()` then `read()`.

| File pair | Sensor | Interface | Notes |
|---|---|---|---|
| bme280.h / .cpp | BME280 | I2C 0x76 | Temperature, humidity, pressure |
| mpu6050.h / .cpp | MPU6050 | I2C 0x68 | Accelerometer, gyroscope (6-axis) |
| ina219.h / .cpp | INA219 | I2C 0x40 | Bus voltage, current, power |
| mlx90614.h / .cpp | MLX90614 | I2C 0x5A | Non-contact IR surface temperature |
| vl53l0x.h / .cpp | VL53L0X | I2C 0x29 | Time-of-flight distance |
| as5600.h / .cpp | AS5600 | I2C 0x36 | Magnetic shaft angle and RPM |
| mq2.h / .cpp | MQ-2 | Analogue GPIO34 and digital GPIO35 (active LOW) | Gas level and alarm from the digital output or the analogue level, with a warm-up hold-off |
| ldr.h / .cpp | LDR | Analogue GPIO33 | Ambient light level |
| ds18b20.h / .cpp | DS18B20 | OneWire GPIO4 | Contact temperature probe |
| fc28.h / .cpp | FC-28 | Analogue GPIO36 | Moisture / water ingress. On the revised board it reads 0 V when unplugged |
| ldr.h / .cpp | Microphone (MAX4466), in the same files as the LDR | Analogue GPIO32 | Peak-to-peak swing and mean. On the revised board it reads 0 V when unplugged |
| input_voltage.h / .cpp | 12 V input | Analogue GPIO39 | Calibrated millivolts times 11 (100 kohm over 10 kohm) |
| sensor_rail.h / .cpp | Sensor supply switch | GPIO14 (input except while cycling) | Power-cycles the 3.3 V feed to the cable sensors |
| health.h / .cpp | none | none | State and since time per sensor key, plus the serial link watch. No Arduino types, so the host test builds it |
| analog_checks.h | none | none | The microphone and moisture bands and the 12 V conversion. Header only. The LDR has no fault band |
| content_checks.h | none | none | Register checks that show a part has reset (BME280 and BMP280 `ctrl_meas`, MPU6050 sleep bit, INA219 calibration and overflow, AS5600 magnet) and the DS18B20 power-on value. Header only |
| mcp23017.h / .cpp | MCP23017 port expander | I2C 0x20 (revised board only) | The Wire binding and the start-up and loop hooks. Compiled in only when `HAS_EXPANDER` is 1, so the present board's image carries none of it |
| mcp23017_logic.h | none | none | The driver's decisions: the pin table, the start sequence, the read-back check, the debounce and the failure handling. No Arduino types, so the host test drives it against a scripted chip. Header only |
| board_check.h | none | none | The board verdict (OK, MISMATCH or UNKNOWN) from the MCP23017 at 0x20 and whether the bus is known to work. Header only |
| fitted.h | none | none | Which sensors this build has, from the `HAS_` switches. Header only |
| stuck_check.h | none | none | The stuck test for the hub's own BME280 or BMP280, on the raw data words. Header only |
| shaft_math.h | none | none | The AS5600 rpm arithmetic, which divides by the time the samples cover. Header only |

The revised board also carries an MCP23017 at 0x20, a second INA219 at 0x41 and a push button. The firmware probes 0x20 once at boot to recognise the board and then, on the revised image only, starts the expander driver described below. The second INA219 has no driver yet (see Not done).

All I2C sensors share SDA=GPIO21 and SCL=GPIO22. See `hardware/wiring/esp32_pinout.md` in the repo root for full wiring details.

## Port expander and push button (revised board)

> [!IMPORTANT]
> No revised board has been made and nothing here has run on a chip. The driver is proven only against a scripted chip in `test_host/test_expander.cpp`. Every timing figure is chosen and not measured. The input levels come from Microchip's data sheet (DS20001952D) and the board's port table (second issue, 22 November 2026). The rail thresholds are estimates, measured at bring-up.

The driver is `mcp23017.cpp` (the Wire binding) over `mcp23017_logic.h` (the decisions). It is compiled in only for `esp32dev_revb` and `esp32dev_revb_release` (`-DHAS_EXPANDER=1`) and starts only when the boot check says the expander answered. The present board's image carries no expander code and its driver never starts. The boot check itself still probes 0x20 up to five times (`BOARD_PROBE_TRIES`) on both images, with address-only transfers, to tell the two boards apart. Nothing else is sent to 0x20 on the present board.

### What the pins do

The table is a copy of the board's port table. `test_host/fixtures/expander_pins.md` is the copy the pins test compares with the driver's table, line for line, including the polarity of every input and the circuit behind it. The hardware files are the source and win if the two disagree. The polarity of every input is in one table in `mcp23017_logic.h`.

| Pin | Net | What the driver does |
|---|---|---|
| GPA0 | AUX_OK | Input through a transistor. Low means the 5 V AUX rail is present |
| GPA1 to GPA3 | FEED3_OK, FEED2_OK, FEED1_OK | Inputs through a transistor. Low means the 12 V feed is present |
| GPA4 to GPA6 | SPARE_A4 to SPARE_A6 | Inputs on J23 with the chip's own pull-up on, because the board leaves them floating |
| GPA7 | SPARE_A7 | Output only (J23). Driven low. Never read |
| GPB0 | BUTTON | Input. Low means pressed |
| GPB1 | SENS_OK | Input from a plain divider. High means the sensor rail is present |
| GPB2 | STRIP_OK | Input through a transistor with a clamp diode (D8). Low means the strip rail is present |
| GPB3 | ENABLE_OK | Input through a transistor. Low means the relay 5 V is present |
| GPB4 to GPB6 | SPARE_B4 to SPARE_B6 | Inputs on J28 with the chip's own pull-up on |
| GPB7 | SPARE_B7 | Output only (J28). Driven low. Never read |

Three facts from the data sheet shape this.

- GPA7 and GPB7 are output only on the MCP23017 (features list page 1, table 2-1 page 11 and section 3.5.1 page 18: IO7 must be set to 0). So the driver writes bit 7 of both direction registers as an output and both output latches low, never reads those two pins and includes them in the read-back. Anything wired to J23 pin 3 or J28 pin 4 will see a driven output. The earlier revision C of the sheet lists the pins as bidirectional, so use revision D. The board's own port table still says "unverified" for these two rows and the hardware side should update it.
- The input levels are VIL at most 0.2 x VDD and VIH at least 0.8 x VDD for the whole supply range, with leakage of 1 uA either way (table 1-1 page 4). At 3.3 V that is 0.66 V and 2.64 V.
- The weak pull-up is 40 to 115 uA at 5 V (table 1-1). The sheet states no resistance and gives no figure at 3.3 V, so the spare pull-ups are only a way to stop the inputs floating. We do not rely on a value.

At reset the chip has all pins as inputs and the pull-ups off. Polarity is left as wired (not inverted) and the firmware reads the level as the table gives it.

### The start

1. Write IOCON as 0x00 at 0x05 and then at 0x0A. The chip is in one of two addressing modes (IOCON.BANK) and nothing in the board resets it, because RESET is tied high. In bank 1 mode IOCON is at 0x05 and the first write puts the chip in bank 0 mode. In bank 0 mode 0x05 is GPINTENB and the write sets its reset value. The second write then lands on IOCON in either case. Nothing before it writes an output latch.
2. Write the output latches low, then the direction registers (0x7F: every pin an input except bit 7), polarity, interrupt enables, default values and interrupt control (all zero), then the pull-ups (0x70 on each port: pins 4 to 6).
3. Read all 22 registers in one transfer and compare each with what was written. The pin, capture and flag registers are live and are not compared. If any register differs the driver does not trust the chip, reports the register and its two values once and reads nothing from it.

That is 17 transfers once at start and again after a reset. At 100 kHz we work out about 8 ms for the lot.

### Polling

No interrupt line reaches the module, so the driver polls. Every figure is a setting in `config.h`.

| What | Setting | Value |
|---|---|---|
| Pin read (GPIOA and GPIOB, two bytes) | `EXPANDER_POLL_MS` | 20 ms. About 0.5 ms of bus time per read, about 2.5 per cent of the bus |
| Read-back of all 22 registers | `EXPANDER_CONFIG_CHECK_MS` | 1 s. About 2.5 ms per read, about 0.25 per cent of the bus |
| Button press | `BUTTON_PRESS_MS` | Low for 40 ms in a row |
| Button release | `BUTTON_RELEASE_MS` | High for 60 ms in a row |
| Rail present or absent | `RAIL_DEBOUNCE_MS` | The same reading for 500 ms in a row |
| Rail flapping | `RAIL_FLAP_EDGES` in `RAIL_FLAP_WINDOW_MS` | 6 changes in 10 s |

A failed read counts for nothing: it is never a sample and the time around it is credited to no debounce. After any failed read the driver sends one address-only probe, because in the pinned core a read that fails does not say why (`requestFrom` returns 0 for a refused address and for a time-out alike). No acknowledge is a chip that does not answer and a time-out is a bus that is held. The next poll then waits `EXPANDER_FAIL_BACKOFF_MS` (1 s). `EXPANDER_FAIL_LIMIT` (3) failed reads inside `EXPANDER_FAIL_WINDOW_MS` (10 s), in a row or not, call the chip down, so a bus that fails every other read cannot hold the loop.

What a call can cost the loop. A call that reconfigures makes at most 19 transfers (a pin read, the read-back and the 17 of the start), about 9 ms at 100 kHz by calculation. Any other call makes at most 2 transfers or 3 when a failed read is followed by its probe and it ends at the first one that fails. A failed transfer costs one Wire time-out (about 50 ms in the pinned core, not measured), so a call can hold the loop for two time-outs, 100 ms, at worst. In any ten seconds the driver costs the loop at most 500 ms (5 per cent): `test_host/test_expander.cpp` simulates 13 failure patterns for 20 minutes each, including a dead chip, every other read failing, random failures and a chip that is up for 1 s and down for 2 s and the worst it found was 450 ms. Time between two good reads is credited to a debounce up to `EXPANDER_MAX_CREDIT_MS` (100 ms), so a pass that holds the loop for seconds never makes a short glitch look long.

### The rail inputs

Six of the seven rail inputs go through an NPN transistor (a BC337-40). The rail feeds the base through a resistor and a 10 k resistor takes the base to ground. The collector is the expander pin and a 10 k resistor pulls it up to the chip's supply. So the pin reads low when the rail is up and high when it is absent. With the rail off the input reads high, which is "absent" and the same holds at reset. SENS_OK is the one plain divider and reads high when the rail is up.

Present means the rail is up. It does not mean the rail is in range. The readings that tell the node a rail is in range are the 12 V input (`supply`, out of range under 9 V or over 15 V) and the INA219 bus voltage and current (`ina219`). No other rail has a reading of its own that this driver can use and the second INA219 at 0x41 has no driver yet. The health text says "present (up, not checked for range)" for this reason.

The input levels are VIL 0.2 x VDD and VIH 0.8 x VDD (data sheet table 1-1) with the supply at 3.235 to 3.365 V. A transistor input has to read under 0.66 V to be low. The thresholds below are estimates (base-emitter 0.6 to 0.7 V and a forced gain of 100), measured at bring-up. The bring-up step is to measure each input's low level against 0.66 V and each rail's switching points with a bench supply. Between the two figures the reading is undefined, so a rail that sits in that band is a real case.

These are estimates, measured at bring-up. The table follows the board's table in `test_host/fixtures/expander_pins.md` and the pins test fails when the two differ.

| Rail | Net | Circuit | Present when the input reads | Present from | Absent under | Undefined between |
|---|---|---|---|---|---|---|
| 12 V feed 1 | FEED1_OK | Transistor, 100 k and 10 k | low | 8.10 V | 5.00 V | 5.00 V to 8.10 V |
| 12 V feed 2 | FEED2_OK | Transistor, 100 k and 10 k | low | 8.10 V | 5.00 V | 5.00 V to 8.10 V |
| 12 V feed 3 | FEED3_OK | Transistor, 100 k and 10 k | low | 8.10 V | 5.00 V | 5.00 V to 8.10 V |
| 5 V AUX | AUX_OK | Transistor, 47 k and 10 k | low | 4.20 V | 2.60 V | 2.60 V to 4.20 V |
| Sensor rail | SENS_OK | Divider, 1 k and 100 k | high | 2.72 V | 0.65 V | 0.65 V to 2.72 V |
| Strip rail | STRIP_OK | Transistor, 47 k and 10 k, with a 1N4148 clamp diode on the base | low | 4.20 V | 2.60 V | 2.60 V to 4.20 V |
| Relay 5 V | ENABLE_OK | Transistor, 47 k and 10 k | low | 4.20 V | 2.60 V | 2.60 V to 4.20 V |

What follows from it.

- A 5 V rail that sags to 4.2 V or more is present. One that falls under 2.6 V is absent. Between the two the input may read either way, so a brown-out of a 5 V rail to 3 V or 4 V cannot be seen from this input.
- A 12 V feed is present from 8.1 V and absent under 5.0 V. A feed at 6 V may read either way.
- The pin never sits above its supply. The strip input has a 1N4148 clamp diode (D8) from ground to the transistor's base, because the strip rail is the one 5 V rail an outside source can reach and a reversed supply would exceed the base's reverse rating. The board may add the same diode to another input where a reversed or back-fed rail would put more than 4 V in reverse on the base. Polarity, thresholds and pins do not change.

A rail that reads the same for 500 ms is reported present or absent. The sense is taken from the table: a transistor input that reads high is absent and SENS_OK that reads low is absent. A rail is `ok` only from a fresh reading. Whenever the expander is not running and trusted (never started, not answering, not trusted or waiting to be read again) or a rail has not yet been read and settled or the last good reading is older than `EXPANDER_FRESH_MS` (2 s), every watched rail is posted `stale`, which is the backend's word for old values and means the node cannot say. Silence never means up: a rail that is not in the faults map was read up from a fresh reading. The `stale` since time is the last good reading, so the age of the reading is how long the rail has been unknown. The posted body carries the state only. The serial monitor says when the chip's loss makes the rails stale and the once-a-minute `expander:` line prints `rails_unknown_s`. A rail whose reading changes 6 times in 10 s is reported `intermittent` and is never reported absent from those readings, because it never holds one level for 500 ms. It goes back to ok after a window with fewer changes. An absent rail is `missing`. The words go to the serial monitor once per change and name the rail and the net, for example "12 V feed 2 is absent: FEED2_OK reads high, since 12.3 s after boot". The since time is the first reading of the absent level and not the time of the verdict. The health table keeps the same since time. The post carries the state only, under the keys `aux_rail`, `feed1_rail`, `feed2_rail`, `feed3_rail`, `sens_rail`, `strip_rail` and `enable_rail`. `EXPANDER_RAIL_EXPECTED_MASK` in `config.h` leaves out a feed that a hub does not use, so it is never reported.

SENS_OK reading present does not prove the sensor rail is on, because the I2C pull-ups can hold it high with the rail off. So the sensor rail is called present only while a cable sensor on it (the sensors `initCableSensors` sets up) has also answered within `EXPANDER_SENSOR_FRESH_MS` (12 s). While SENS_OK reads high and no sensor has answered the rail is `stale` (not proven up) and after 15 s the serial monitor says so. SENS_OK reading low is absent either way.

The chip's interrupt pins:

| Pin | Package pin | Net | What the driver does |
|---|---|---|---|
| INTA | 20 | EXP_INT, to test pad TP33 only | Not used |
| INTB | 19 | not connected | Not used |

No interrupt line reaches the module, so the driver polls.

The spare headers are split. J23 has 6 pins: 3V3, GND, SPARE_A7, SPARE_A6, SPARE_A5, SPARE_A4. J28 has 5 pins: SPARE_B4, SPARE_B5, SPARE_B6, SPARE_B7, GND. J28 has no 3.3 V pin.

### The sensor rail after a power cycle

`sensorRailPowerCycle()` arms a check and returns, so it does not hold the loop. The polls that follow have to read SENS_OK high twice in a row within `SENSOR_RAIL_RETURN_LIMIT_MS` (300 ms) of the bus coming back. If they do not the rail is reported `missing` (`sens_rail`), counted and said in words and the sensors are still set up again, because they report their own loss. A poll made late (the sensor set-up that follows can hold the loop for seconds) that finds the rail up still passes. The check proves SENS_OK came back and never that it went off. The pull-ups can keep the input high while the switch is off, so nothing waits for it to fall and a high reading alone does not make the rail present: a sensor has to answer too. The sensors that answered before the cycle say nothing about the rail now, so that proof is cleared. If the expander cannot be read the check says it cannot confirm and claims nothing about the rail.

### The push button

The button is debounced as above. The driver gives a press event and a long press event. A long press is `BUTTON_LONG_PRESS_MS`, which is the same 5 s hold as the BOOT button. What the firmware does with them:

- A short press is written to the serial monitor and counted. Nothing in the firmware asks for a button press, so it does nothing else.
- A long press in the first 30 seconds after a power-up clears the stored credentials and restarts (`PROVISION_CLEAR_WINDOW_MS`). A warm reset (a brown-out or a watchdog) does not open the window, because a node reset next to a pressed button must not clear its credentials. This differs from the BOOT button, whose window counts from every reset. Outside the window the long press is logged and ignored.
- A press counts only after the button has been seen released at least once since the driver started or came back, so a button that reads pressed from the start (or held across a loss of the chip) can never clear the credentials.

### When the chip misbehaves

None of these stops the sensors, holds the main loop for more than the bound above or stops the node posting. The node goes on reading its other sensors and posting. Each case is said once in words on the serial monitor and counted. The counters are on the once-a-minute `expander:` line. In every case where the chip cannot be read the watched rails are posted `stale` and the expander key says why.

| Case | What the node does | Health | Counter |
|---|---|---|---|
| Does not answer at start | Reports it. The rails are `stale`. Tries again after 1 s and then 2 s and so on up to 30 s | `expander: missing` | `start_failed` |
| Stops answering later (3 failed reads inside 10 s) | Reports it. The rails are `stale`. Tries again on the same schedule. Reads every rail again from scratch when it answers | `expander: missing` | `lost`, then `recovered` |
| Answers with a changed configuration (a brown-out reset) | The 1 s read-back finds it, reports the register, writes the configuration again and reads it back. All pins are inputs after a reset, so the rails and the button still read their true levels. During the gap and the reconfigure the driver reports nothing about any rail and keeps their states | none while it holds | `reconfigured` |
| Read-back does not match | Does not trust it. Reads nothing from it. The rails are `stale`. Tries again on the same schedule | `expander: out_of_range` | `untrusted` |
| Bus stuck (most failures are time-outs) | Reports that the whole bus is affected. The rails are `stale`. Tries again on the same schedule. It does not try to free the bus | `expander: missing` | `bus_stuck` |
| One read fails | The sample counts for nothing. The next poll waits 1 s. The last readings stay while they are fresh | none | `read_failed` |
| Never started (a board mismatch or an unknown board on a revised image) | Nothing is sent to the chip. The rails are `stale` | `expander: stale` | none |

A lone failed read is written to the serial monitor at most once a minute. A flag or capture register that older firmware left set is not compared, because only a read of the pins clears it. An interrupt enable that is left set is a mismatch, because that register is written.

### Not done

The second INA219 at 0x41 is not set up in this round. Its reading has nowhere to go: the post has no field for it and the telemetry contract is frozen except for optional fields. When it is done, the Adafruit library's default `begin()` calibration for 32 V and 2 A selects the 320 mV shunt range that the 0.1 ohm shunt needs, which we have only read in the library source and not run.
