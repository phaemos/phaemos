# Firmware

Firmware for all 4 Phaemos nodes. Each node has its own subfolder.

> [!NOTE]
> This folder is published to [phaemos/firmware](https://github.com/phaemos/firmware) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

> [!IMPORTANT]
> Nothing in this folder has run on hardware. The hub firmware has been built and run through host tests only. The Nano and the Black Pill firmware have been built, run through host tests and run on emulated chips. The revised ESP32 carrier board has not been built. Every electrical figure in the READMEs comes from the wiring notes or the data sheets. None of them comes from a measurement. The bring-up plan at the end of this page is the list of what a board has to show before any of it is trusted for alarms.

| Folder | Node | Board | Language |
|---|---|---|---|
| [esp32/](esp32/) | Primary gateway (the hub) | ESP32 DevKit V1 on a carrier board | Arduino C++ with PlatformIO |
| [stm32_blackpill/](stm32_blackpill/) | Vibration and FFT satellite | STM32F411 Black Pill | C (STM32Cube HAL) with PlatformIO |
| [arduino_nano/](arduino_nano/) | Auxiliary sensor satellite | Arduino Nano | Arduino C++ with PlatformIO |
| [pico_w/](pico_w/) | Ambient environment | Raspberry Pi Pico 2W | MicroPython |

---

## How the nodes connect

```
[STM32 Black Pill] <--UART--> |
                              |---> [ESP32 hub] --Wi-Fi--> [Backend API]
[Arduino Nano]     <--UART--> |

[Pico 2W] ----------------------Wi-Fi--> [Backend API]
```

- The ESP32 is the central hub. It reads its own sensors and talks to the Nano and the Black Pill over two UARTs, in both directions.
- The Pico 2W runs independently and posts directly to the backend over Wi-Fi.
- The hub and the Pico 2W post to `POST /api/v1/telemetry` with their device API keys in the `X-API-Key` header. The Nano and the Black Pill post nothing. They send lines to the hub.

### The link between the satellites and the hub

Each satellite sends one data line per window. The hub sends a ping to each every 30 s. The format is one contract that three firmwares and the backend share.

- A data line is ASCII, ends in CR LF and has the shape `<body>*<CCCC>`. `<CCCC>` is four upper-case hex digits of CRC-16/CCITT-FALSE over the body. A line is at most 160 bytes. The check value for the string `123456789` is `29B1`. Every implementation carries that as a test.
- After its readings every line carries `ST` (a status bit mask for what the node knows about its own sensor and its last reset), `SEQ` (lines sent since boot) and `UP` (seconds since boot). The Nano line also carries `VCC`. The Black Pill line also carries `RMS`, `PK` and three counters.
- A lost sensor never looks like a dead link. The node keeps sending lines and `ST` says why the readings are empty.
- The hub sends `PING:<n>` and the satellite answers `PONG:<n>*<CCCC>` within 500 ms. A satellite never blocks on its receive side.
- The hub parses and judges all of it in `esp32/comms/link_protocol.cpp`, which has no Arduino types so the host tests cover it. It turns the status bits into entries in the telemetry `faults` map. It counts lines, checksum errors, sequence gaps and restarts. It reports each link as `line_low`, `garbage`, `silent`, `one_way`, `intermittent` or ok.
- The hub still accepts the old line format (no checksum) until the first checksummed line from a link since power-up, so an older satellite keeps working.

The details are in the three READMEs: [esp32/README.md](esp32/README.md) (what the hub does with a line), [arduino_nano/README.md](arduino_nano/README.md) and [stm32_blackpill/README.md](stm32_blackpill/README.md) (what each satellite sends).

---

## Flashing

| Board | Tool | Notes |
|---|---|---|
| ESP32 hub | PlatformIO. `pio run -t upload` in `esp32/`. Build the image for a real hub with `-e esp32dev_release` or `-e esp32dev_revb_release` once the two trust roots are pasted in. Then provision it over the serial console | Two environments: `esp32dev` is the present board and the default. `esp32dev_revb` is the revised board, which is not built yet. Check which board is in front of you. The firmware checks for the revised board's MCP23017 at boot and will not drive GPIO14 if the image and the board disagree or if the check cannot tell |
| STM32 Black Pill | PlatformIO and an ST-Link V2. `pio run -t upload` in `stm32_blackpill/` | SWD, 4-wire connection |
| Arduino Nano | PlatformIO. Pick an environment in `arduino_nano/nano_node/` | `nanoatmega328new` for the new bootloader and `nanoatmega328` for the old bootloader found on many clones. The watchdog build is for the new bootloader only. See the Nano README |
| Pico 2W | Thonny or rshell | Hold BOOTSEL on power-up, copy .uf2 or use MicroPython REPL |

---

## Checks

| Command | What it does |
|---|---|
| `make firmware-check` | Builds every firmware environment (the hub's two, the Nano's four and the Black Pill's one) and runs every host test under `esp32/test_host/` and `stm32_blackpill/test_host/`. Each test is built and run with the command in its own file header, with the sanitizers where the header asks for them. It stops at the first failure |
| `make sim-nano` | Runs the compiled Nano firmware on a simulated ATmega328P (simavr) against a simulated BME280 or BMP280. Needs simavr. See `arduino_nano/sim/README.md` |
| `make sim-blackpill` | Runs the compiled Black Pill firmware on an emulated STM32F411 (Renode) against a scripted MPU6050. Needs Renode. See `stm32_blackpill/sim/README.md` |

The hub posts over TLS with pinned roots and keeps its secrets in its own flash, not in the source (see `esp32/README.md`). The hub's host tests also run under the address and undefined-behaviour sanitizers. The hub core test (`esp32/test_host/test_core.cpp`) replays whole scenarios through the order of `setup()` and the judgement of every reading pass. The host tests prove the pure logic: the line format and parser, the status bits, the health table, the over-temperature judgement, the post schedule across simulated days, the watchdog supervision rules, the saved state kept across a warm reset and the body the hub posts. The emulations prove the firmware's behaviour against models of the chips and the sensors. Neither proves anything about real timing, real analogue levels, the real power supply, the real bootloaders on a real board or the relay path. Only the bring-up plan below can show those.

---

## Bring-up plan

The first bench session, in the order that the most depends on. For each item the pass criterion is given where the code gives one. Where it does not, the criterion is to measure and record the figure and then change the constant or the wiring it decides.
1. **Confirm the board verdict on each board.** Run the present-board image on the present board and the revised-board image on the revised board with nothing on the relay contacts. Read the serial monitor for the board check and the `board_check` field.
   - Pass: the verdict is OK on both. Then confirm a mismatch the other way: the revised image on the present board must say `mismatch` and never drive GPIO14 and the same for the present image on the revised board. Hold SDA low and see `unknown` and no GPIO14 drive. Until this passes, nothing else on this list means anything.
2. **TLS to the real server and provisioning.** Paste the two roots into `comms/trust_roots.h` (see `esp32/comms/trust_roots.h` for where each comes from and how to check its fingerprint), build `-e esp32dev_release`, flash it and provision the hub over the serial console. Watch the serial monitor for the clock, the first post and the line `TLS connect and handshake took ... ms, lowest free heap ... bytes`.
   - Pass: the clock is set within one 15 s round. The post returns 2xx. The handshake time is recorded (documented at one to three seconds and unmeasured). The lowest free heap after a post leaves a margin over 40 to 50 KB and `diag.heap_block` does not shrink over 48 hours. With the hub's clock blocked or the server's certificate wrong, nothing is posted and the panel shows `NET` after 5 minutes while an over-temperature still switches the relay. A wrong key shows `NET` at once and is retried once in ten minutes. Hold BOOT for 5 seconds in the first 30 s after power-up and see the stored credentials clear.
3. **The parts' identities.** WHO_AM_I of the MPU6050 on the hub and on the Black Pill. Also the chip ID of each BME280 or BMP280.
    - Pass: the MPU6050 reads 0x68 on both. Many breakouts carry a part that answers 0x70, 0x72 or 0x98. The firmware would treat those as missing for ever. The BME280 reads 0x60 and the BMP280 reads 0x56 to 0x58 on the hub. The Nano accepts only 0x58, so a 0x56 or 0x57 part on the Nano is missing for ever.
4. **The relay outputs through power-up, reset and brown-out.** Scope GPIO13, GPIO12, GPIO23 (relay 3 on the revised board), GPIO14 and GPIO27 and the relay contact, with no load on the contacts. With `COOLING_RELAY_NO_INFO_ON` at 1 a refused restore switches relay 1 on during boot, so a load on the contact would run. Watch them through a cold start, a watchdog reset and a supply dip. Measure the processor rail while the relay and its load switch. This decides whether the load goes on the normally open or the normally closed contact and whether a brown-out loop is possible.
   - Pass: the relay pins are off or high impedance through a cold start. After a cold power-up or a brown-out nothing is restored and the cooling relay waits for confirmed readings. GPIO14 shows a floating pin through reset and then a weak pull-up (the datasheet says so). Record whether the relay 3 driver follows it.
5. **Over-temperature end to end.** Warm the BME280 past 60 C and time the relay. Force a watchdog reset during the alarm. Unplug the BME280 during the alarm. Try to unplug it during its set-up too. That last step may not be reachable: an unplugged BME280 fails the firmware's own check and returns with no reset. The reset path needs the part to drop out within a few milliseconds of the library's own wait. Do it only after the identity check above.
   - Pass: critical and the relay in 10 to 18 s (three readings of 5 s plus a pass). After the forced reset the relay is back within the boot. It stays on until a reading below 58 C. Otherwise it is dropped about 10 s after boot when no trusted reading confirms it. With the BME280 unplugged during the alarm the relay is held on, with a DS18B20 fitted or not, because each source holds its own latch. The panel shows `CRITICAL`. If the set-up stall can be reached, the hub skips the sensor after one task watchdog reset (`[setup] bme280 is skipped on this boot`). The panel is never dark.
6. **The water probe.** Read the counts dry, damp, in tap water and in the liquid the machine uses, then unplugged on each board.
   - Pass: in water under `WATER_THRESHOLD` (2,000) with dry and damp above it. On the revised board with the 2.2 kohm resistor, unplugged reads at or under `PROBE_UNPLUGGED_MAX_COUNTS` (200) and a flooded probe is above it. Then set `WATER_THRESHOLD` from the figures and set `WATER_ALARM_PROVEN` to 1. Until then the hub says at boot that the water alarm is unproven.
7. **The MQ-2.** The analogue reading in clean air after warm-up, with the module unplugged and with its 5 V off. The digital line in each case. A test gas. Record the analogue level at which the digital output alarms, which decides `GAS_ANALOGUE_ALARM_COUNTS` (1,600, unproven) and the clean-air band (530, unproven). Then set `GAS_ALARM_PROVEN` to 1.
   - Pass: clean air is at or above `MQ2_FAULT_ADC_MAX` (100 counts) and an unplugged module is under it, so the panel shows `FAULT: MQ-2`. The panel shows `FAULT: WARM` for the whole 180 s warm-up. The digital line and the analogue level both alarm with the gas and the panel shows a warning. A digital alarm on a clean analogue level shows `FAULT: MQ-2` and keeps the alarm.
8. **Hub timing and memory under load.** The longest loop pass with every sensor fitted, with one unplugged and with SDA shorted to ground. The loop task's stack, the post task's stack, the free heap and the largest block over 48 hours of posting, including a dead DNS and a dead backend.
   - Pass: the longest pass is about 3 s or less with no watchdog reset (`reset_reason` is never `task_wdt`) against the 10 s limit. The lowest free stack figures (`diag.stack_loop` of 8,192 and `diag.stack_post` of 10,240) keep a margin. `diag.heap_min` and `diag.heap_block` do not fall steadily. The backend does not keep `diag` today, so read the figures on the serial monitor, where the hub prints them once a minute.
9. **The sensor rail on the revised board through a reset.** The rail voltage, the I2C lines and whether each sensor comes back without a hub reset.
   - Pass: every sensor answers again after a reset without a second reset. Record the rail and bus levels in the half-powered state the pull-up can leave.
10. **The links on real cable.** The hub's transmit level at Nano D0. The pong rate over an hour. The `crc`, `gaps` and `restarts` counters over a day. `line_low` with a cable out. An upload to the Nano with the link attached.
    - Pass: Nano D0 reads about 5.0 V for a high and about 0.5 V for a low (the carrier board's BSS138 shifter). One pong per 30 s and never `one_way`. `crc`, `gaps` and `restarts` stay at or near zero. On the revised board `line_low` appears within about 5 s of pulling the cable on a running hub. On the present board the internal pull-up stays on, so a pulled cable reads `silent` and `line_low` can never appear.
11. **The Black Pill clock and timing.** That the crystal starts and the PLL locks, the tick period on a pin, the delay of the first sample after each line, a tick pass with SDA held low and the pong latency in that state.
    - Pass: the tick period is 10 ms and the pong comes within 500 ms.
12. **The Black Pill watchdog.** The real LSI frequency and so the real timeout, a forced hang, the reset flag on the next line and a cold start that does not read as a brown-out.
    - Pass: a forced hang resets the node and the next line carries RESET_WATCHDOG. A power-up does not carry a brown-out bit.
13. **The Nano's sensor.** One hour of raw words from a real part in a closed box, replayed through emulation scenario 9e. The I2C levels on A4 and A5 with the internal pull-ups on. `VCC` against a meter.
    - Pass: no `BME_STUCK` on a still, healthy part and `VCC` within the tolerance the Nano README states.
14. **The Nano's reset cause on each bootloader.** A power cycle, a brown-out, the reset button and a forced hang in the watchdog build.
    - Pass: it matches the table in the Nano README for each bootloader.
15. **A soak of several days** with everything connected, watching `seq` gaps, `boot`, `reset_reason` and the link counters at the backend. It will not reach 24.9 days, which is why the post schedule has a host test that runs across 60 simulated days.
    - Pass: no unexplained `boot` increments, no `task_wdt` resets and no `seq` gap beyond the ones the post back-off explains.
16. **One OTA update, if that switch is ever to be turned on.** It has never run in its new place in the post task. The updater's read loop may also starve the idle task's watchdog on core 0.
    - Pass: an update downloads and the hub reboots into it, with no watchdog reset during the download and the main loop still reading and judging while it runs. Until then `OTA_ENABLED` stays 0.

### Bring-up of the port expander (revised board only)

Item 9 above covers the sensor rail. These are the steps for the MCP23017 driver, in order. Nothing here has run on a board and every figure is an estimate or a worked figure until it is measured. Use the revised image on the revised board only.

1. **The start in either addressing mode.** Power the board and read the `[expander] started` line. Then hold the node in reset and power the expander from a bench supply so that it keeps a stray configuration, set IOCON.BANK to 1 with a probe and release the node. Read the registers back with the node's read-back (the `expander:` line shows `untrusted` and `reconfigured`).
   - Pass: the chip starts and reads back in both modes with no `untrusted` count. A chip left in bank 1 mode is put right by the first two writes.
2. **J23 pin 3 and J28 pin 4.** GPA7 and GPB7 are output only and are driven low. Measure both with nothing connected and then with 10 kohm to 3V3.
   - Pass: both read under 0.4 V. Anything wired to those two pins sees a driven output. Record the level.
3. **Each rail input's low level.** For each of the six transistor inputs (AUX_OK, FEED1_OK to FEED3_OK, STRIP_OK and ENABLE_OK) measure the pin with its rail up, at the lowest supply the hub allows.
   - Pass: each reads under 0.66 V (0.2 x VDD at 3.3 V) and never over 0.4 V by a wide margin. The supply is 3.235 to 3.365 V. Record the figures.
4. **Each rail's switching points.** Replace each rail with a bench supply and raise it from 0 V. Note the rail voltage where the input first reads present and where it falls back to absent on the way down. Do the same for SENS_OK.
   - Pass: the 5 V rails read present from 4.2 V at the latest and absent under 2.6 V. The 12 V feeds read present from 8.1 V and absent under 5.0 V. The sensor rail reads present from 2.72 V and absent under 0.65 V. Replace the estimates in `config.h`, `sensors/mcp23017_logic.h`, `sensors/README.md` and the fixture with the measured figures.
5. **A rail in its undefined band.** Hold a 5 V rail at about 3.4 V (between 2.6 V and 4.2 V) for a minute.
   - Pass: the rail is reported `ok`, `missing` or `intermittent` and never flaps between present and absent more than once in 500 ms.
6. **Silence is not up.** Unplug the expander's SDA wire. Then drop AUX with the wire still out. Reconnect.
   - Pass: within about 3 s `expander` is `missing` or the bus is called stuck, every watched rail is `stale` in the post and none is ever `ok`. After reconnecting every rail is read again and AUX is reported `missing` at once.
7. **The sensor rail is not proven off.** Switch the sensor rail off with a bench switch while leaving the I2C pull-ups connected and read SENS_OK.
   - Pass: if SENS_OK stays high the rail is `stale` (not proven up) and never `ok` once the sensors stop answering. Record the level the pull-ups hold.
8. **The sensor rail's return time.** Power-cycle the sensor rail and record when SENS_OK reads high and when the first sensor answers.
   - Pass: SENS_OK reads high within the 300 ms limit (`SENSOR_RAIL_RETURN_LIMIT_MS`) and no `did not come back` line appears. Change the limit if the measured time needs it.
9. **The button.** Press it for 20 ms, 40 ms and 100 ms and hold it for 6 s inside the first 30 s after a power-up and again after a brown-out reset.
   - Pass: 20 ms is ignored and 40 ms and longer is one press. The 6 s hold clears the credentials only after a power-up and never after a reset. A button held from before power-up does nothing until it has been released.
10. **Brown-out detection.** Pull the 3V3 rail under the chip's operating range for 50 ms with the node still running (if the board allows it) and release it.
    - Pass: the `expander:` line shows `reconfigured` one higher within 1 s. The rails and the button read their true state throughout and no rail is reported changed.
11. **What the driver costs the loop.** Short SDA to ground for 10 s and then hold SCL low for 10 s with every sensor fitted. Read the longest loop pass and the AS5600 rpm gaps.
    - Pass: the loop is held for about 100 ms at most per failed read (two Wire time-outs, the figure in the README is a calculation) and no more than 500 ms in any ten seconds. Record the real Wire time-out.

---

## Safety

Firmware cannot hold a pin through a reset. A watchdog reset, a panic or a brown-out returns every pin to its reset state for a while and the hub's relay can drop out with it. A machine that must not overheat therefore needs a thermostat or a thermal cut-out in its own load circuit as well as this hub. The hub's relay is a convenience and an early action. It is not the last line of protection.

### What the hub protects about its keys and what it cannot

The hub posts over TLS with the certificate checked against two pinned roots, so a node on the same network can no longer read the device key or the readings off the wire or answer a post with a fake success. Its Wi-Fi password, device key, API address and device id are written to the hub's own flash over the serial console and are not in the source or in the built image, so a careless `git add` cannot publish them and one image fits every hub.

What no software change can fix: anyone who holds a hub can read its flash. The stored password and key are not encrypted and the same person can write a modified image back. Stopping that needs flash encryption and Secure Boot, which are one-way hardware settings made per board and a move from the Arduino bootloader to the ESP-IDF one. This firmware does not use them. The same goes for the UART wires to the satellites, the sensors and jamming the radio, which are physical.

The practical advice follows from that:

- Put the nodes on a Wi-Fi network that reaches only the API, so a stolen password gives nothing else.
- Rotate a device key as soon as a hub is lost or someone you do not trust has held one. A stolen key lets its holder post as that one machine and nothing else.
- Treat a key that ever crossed a network in clear, which includes every key used before this firmware, as lost and rotate it.
- A compromised server can always drop or falsify what it receives. Signing images offline, once updates are ever switched on, is the one defence that survives that. Updates stay off until it exists (see `esp32/README.md`, Firmware updates over the air).
