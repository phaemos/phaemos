# Nano node emulation test

We run the real compiled Nano node firmware (`firmware.elf` from PlatformIO) on a simulated ATmega328P
with [simavr](https://github.com/buserror/simavr). The sensors around it are simulated too: a BME280 or
BMP280 on the I2C bus, an LDR and a moisture probe on the ADC, a water level that follows the moisture
reading, the supply voltage and the hub on the serial input. No hardware is needed and no firmware source is
changed. The point is to show that the firmware tells a failed sensor from a real reading, that every line it
sends is well formed and that it answers the hub.

Most scenarios run twice: against the default build and against the build with `NANO_WATCHDOG` on. Scenarios 1 and 10b also run against a third image with `BANDGAP_CALIBRATED` on. The reset cause scenarios (15, 15b, 15c, 16 and 16c) start the chip in the real bootloader image, the new one and the old one, taken from the pinned Arduino core.

**No bytes logged from a real sensor have been replayed through this emulation.** Everything the sensor returns here comes from our own model of the data sheet. Scenario 9e is a hook for a file of raw words from a real part: `--replay FILE` runs it and without a file it does not run (see below).

## Running it

From the repository root:

```bash
make sim-nano
```

That builds the firmware with `pio run -e nanoatmega328 -e nanoatmega328new_wdt -e nanoatmega328new_cal`, builds the harness and runs
the scenarios against the default and watchdog builds (scenarios 1 and 10b also against the calibrated image and
scenarios 16, 16b and 16c against one build each). The exit code is non-zero if any scenario fails. A scenario marked `FINDING`
does not fail the run: it records a result that is worth knowing and that no firmware change here removes. None is open. The one thing
worth knowing that the run cannot settle, the old bootloader's reset loop that simavr does not reproduce, is scenario 16c and
is marked as an observation (see below). A
scenario marked `OBSERVED` is an observation and not a test: it reports what the model did and has no check that its claim
could fail. Scenario 16c (which fails only on an unexpected outcome) and the still room sweeps below half the data sheet noise (9c5, 9c10, 9c20, 9d5, 9d10 and 9d20)
are observations unless they find a stuck verdict, which they report as a `FINDING`.

Useful options (pass them with `ARGS` from this folder):

```bash
cd firmware/arduino_nano/sim
make run ARGS="--only 7b"             # one scenario by its id in the table (a comma list also works)
make run ARGS="--only 9c1 --build wdt" # one scenario against one build (default or wdt). Ids match whole
make run ARGS="--soak-s 60"           # shorter timing soak than the default 300 s (scenario 11, the timing check, runs in every run and has no id)
make run ARGS="--jobs 4"              # run four scenarios at a time (the default is one per core)
make run ARGS="--serial"              # one scenario at a time
```

Needs: PlatformIO, a C compiler and simavr 1.8 (Homebrew keeps it in `/opt/homebrew`, override with
`make run SIMAVR=/path`). Build outputs go to `sim/build/`, which `.gitignore` already covers.

Simulated time is not real time. The simulator runs at roughly two to five simulated seconds per CPU second on
one core, so each scenario takes a few minutes of CPU. The scenarios run side by side in separate processes, one
per core, so a full run takes about ten minutes on an idle machine and longer on a busy one. Each scenario process
has a wall-clock alarm so a stuck run fails instead of hanging.

## What the harness checks on every line of every scenario

- The line ends in `,ST:n,SEQ:n,UP:n,VCC:n*CCCC` and CR LF, with no extra spaces or zeros. It is at most 160 bytes.
- The checksum is right by an implementation of CRC-16/CCITT-FALSE written in the harness from the definition
  (the message fed one bit at a time into a register that starts at 0xFFFF). It is a different arrangement from the
  firmware's byte oriented code on purpose. The harness also compiles the firmware's own `linkframe.h` and checks
  that both give `29B1` for `123456789` and agree on 2000 random messages before any scenario starts.
- `SEQ` runs 0, 1, 2 and so on without gaps and restarts at 0 after a reset.
- `UP` advances by 2 per line, within one second of tolerance.
- The `-1` form of the line and the sensor status bits agree. `SUPPLY_RANGE` agrees with `VCC`.
- The reset bits do not change inside one boot. Every pong is exactly `PONG:<n>*CCCC`.
- The chip did not reset unless the scenario caused it. A reset the scenario did not cause means the firmware
  restarted by itself.
- The gap between lines is 2000 ms plus or minus 100 ms (scenario 11).

## What is in this folder

| File | Purpose |
|------|---------|
| `sim_nano.c` | Harness: boots the ELF, wires up the ADC, UART, supply and pin 7, injects serial input and runs the scenarios |
| `bme280_sim.c` and `bme280_sim.h` | Register level BME280 and BMP280 model on the simavr TWI bus |
| `Makefile` | Builds the three firmware images and the harness and runs them with the two bootloader images from the pinned Arduino core |

## The simulated sensor

The BME280 model is a register model and not a list of canned replies. It has the chip id register
(0x60 for a BME280 and 0x58 for a BMP280), the calibration registers, `ctrl_hum` (latched by a write to
`ctrl_meas`), `ctrl_meas`, `config`, `status` and the raw data registers. It converts for the data sheet's longest conversion time for the oversampling it is set to (46.1 ms for the BME280 at the firmware's
settings) after a mode change and shows the power-on "not measured" values (0x80000) until then. Sleep mode keeps the last
data and forced mode converts once. Register writes arrive as address and data pairs and reads increment the
register pointer, as in the data sheet.

The temperature and pressure calibration words and the raw values (519888 and 415148) are the worked
example in the Bosch BMP280 data sheet, which gives 25.08 degrees C and 100653 Pa. The BME280 uses the same
compensation for both. The data sheets publish no humidity example, so the humidity words are values we chose and not
measured from any part and the expected humidity comes from the data sheet formula in the harness.

The model also has the behaviours the fault scenarios need. It follows the oversampling the firmware writes to `ctrl_meas`
and `ctrl_hum`: the raw words have the resolution that setting gives (16 bits at x1 up to 20 bits at x16, pressure and
temperature each by their own setting, humidity fixed at 16 bits) and the conversion time follows the data sheet formula
(43.2 ms on a BMP280 and 46.1 ms on a BME280 at pressure x16, temperature x2 and humidity x1). Its noise has three modes. The default
dithers the pressure and temperature words by one count either way, small enough to leave the printed digits of the nominal
reading alone so the other scenarios can compare text exactly. The still room scenarios use gaussian noise from the data
sheet figures for the oversampling in use, scaled from 1 down to a twentieth. The third mode is none, for the frozen and
exact-value scenarios.

The figures come from the two data sheets (BMP280 BST-BMP280-DS001-26 tables 4, 5, 8, 9 and 13 and BME280 BST-BME280-DS001-23
tables 11 and 12 and section 9.1), read from the PDFs. They are typical values, so a particular part may be quieter or noisier.
We are sure of the pressure figure (1.3 Pa rms at x16 with the filter off, 0.16 Pa a count, so about 8 counts of the 20 bit word)
and of the humidity figure (0.07 %RH rms at x1 and 0.008 %RH a count, about 9 counts). The temperature figure is 0.004 C rms at
x2 (0.0025 C a count, so 1.6 counts of the 17 bit word) and comes from the BMP280 sheet: the BME280 sheet gives a temperature
figure only at x1, so for a BME280 it is the less certain one. The sweep down to a twentieth exists because none of these is
a guarantee. The noise is measured on the compensated output and we divide it by the nominal resolution to get raw counts, which
is an approximation.

The data registers can be frozen, either with a stopped drift or until the sensor receives a soft reset (0xB6 written to 0xE0).
The part can fall asleep after every Nth data read and it can be swapped for another module with its own chip id and
calibration. The model counts the soft resets, the raw conversions and the longest run of identical raw reads.

**Replaying a real part.** `bme_load_replay` plays back a text file of raw words: three whole numbers per line (the 20 bit
pressure word, the 20 bit temperature word and the 16 bit humidity word of one conversion), one line per conversion,
looped. Start the harness with `--replay FILE` and scenario 9e runs the firmware against it for 30 minutes of simulated
time and fails on any BME_STUCK. No such file exists yet. An hour of words logged from a real part in a closed box would
be the proof that the stuck test never fires on a working one.

The harness computes every expected value itself. Pressure uses the 64 bit data sheet formula and the
32 bit one. The firmware implements the 32 bit formula, which gives 100656 Pa for the example. That prints as
`1006.6` where the 64 bit result of 100653.27 Pa would print `1006.5`, a gap of 2.7 Pa that is far inside the
part's own accuracy. The test expects the 32 bit result and checks the two agree to within 0.05 hPa.

## Scenarios

| # | Scenario | What it proves |
|---|----------|----------------|
| 1 | Healthy BME280 at 0x76 | First line within the promised time, exact values, exact line format, `ST:0` and `VCC` within 1 per cent of 5000 mV. The set-up written decodes to temperature x2, pressure x16, normal mode (`ctrl_meas` 0x57) and the longest conversion is 46.1 ms |
| 2 | BME280 at 0x77 only | Found on the second address after 0x76 is probed |
| 3 | BMP280 (id 0x58) | `HUM:-1` and correct temperature and pressure |
| 4 | No sensor | `-1` for the three values with `ST:1`, a line every 2 s and a retry after 30 s |
| 5 | Sensor stops answering mid-run | `-1` with `ST:1` from the first failed read and polling stops after three |
| 5b | One missed read | One `-1` line and then good values with no retry delay |
| 6 | Sensor returns after 40 s | Readings come back after the 30 s retry |
| 6b | Sensor plugged in late | Same, from a start with no sensor |
| 7a | Brown-out, all sensor registers reset | One `-1` line with `ST:4` and good values on the next line, with no 30 s wait |
| 7b | BME280 control registers reset, data kept | `BME_ASLEEP` on the first line after the reset only and good values on the second, 2 lines or 4 s after the reset |
| 7c | The same on a BMP280 | The same, with only `ctrl_meas` to read back |
| 7d | Part falls asleep after every third read | The bit shows on consecutive lines (the second sleep within 10 reads holds it for 5 more lines, with `-1` values) and clears within 7 lines of the flapping stopping |
| 8 | Data line held low mid-run | The 25 ms Wire timeout fires and the lines keep coming with `ST:1` |
| 8b | Data line held low from power-up | Same, from power-up |
| 9 | Frozen raw data | `BME_STUCK` on exactly the 60th identical read and not before, `-1` values for as long as the data stays frozen, one soft reset in the episode, good values on the first read that differs and one more reset in a second episode |
| 9b | Frozen converter that the soft reset cures | `BME_STUCK` for one line, one soft reset and good values from the next line. The cure is a flag in the model that the reset clears, so this proves the firmware's sequence and not that a real reset cures a real part |
| 9c1 to 9c20 | Still room, BME280, noise at 1, 0.5, 0.2, 0.1 and 0.05 times the data sheet figure for the settings in use, 10 minutes each | Longest run of identical reads against the limit of 60 (table below) |
| 9d1 to 9d20 | The same for a BMP280 (temperature and pressure only) | The same |
| 9e | Replay of raw words logged from a real part | Runs only with `--replay FILE`. No BME_STUCK |
| 10 | Analogue inputs | LDR at 0, mid-scale and full scale. Moisture around the 500 threshold. Pin 7 high for at least 50 ms before each moisture conversion and low after it. Every LDR and moisture conversion has AVcc as the reference and its own pin selected. Three band gap conversions per pass (one discarded and two that agree), each with `ADMUX` 0x4E |
| 10b | Supply arithmetic and limits, on the default, watchdog and calibrated builds | `VCC` equals the value that follows from the applied voltage by the arithmetic of the method, worked out in the harness and not taken from the firmware. `SUPPLY_RANGE` follows the applied voltage and the limits of the build (4000 and 6000 mV or 4500 and 5500 mV when calibrated). The LDR and moisture counts are unchanged at every voltage |
| 11 | Timing | Gap between lines stays within 2000 ms plus or minus 100 ms over five minutes of simulated time in every scenario (gaps across a reset are not counted) |
| 12 | BME_RANGE and the humidity band | Temperature above 85 C and below -40 C, pressure below 300 hPa and above 1100 hPa, humidity at 105.1 and -5.1 per cent: `ST:64` and `-1` values on every line and good values again as soon as the value is back in range. Humidity of 100.5 and 104.9 per cent sets nothing and prints clamped to 100.0 |
| 13 | Ping | 25 pings swept across the 2 s cycle (including `PING:0` and `PING:65535`), six sent while a data line was being sent, three in a row twice (once mid-line), a CR LF ping, a ping sent one byte every 150 ms and a stream of 200 pings 300 ms apart. Each is answered once and in order within 500 ms of its last byte. `SEQ` and the rhythm are untouched |
| 13b | Ping with the bus hung | 48 pings 2.1 s apart while every transfer times out, including the 30 s probe of both addresses, the slowest pass the node has |
| 14 | Garbage and over-long input | 21 junk lines, binary noise, a 299 byte line that ends in a valid ping, a 70 byte line and a 2000 byte flood: no pong for any of it. `PING:77` and `PING:0` are still answered afterwards |
| 15 | Reset cause: brown-out, on the new and the old bootloader | The old bootloader passes `BORF` on and the node reports RESET_BROWNOUT. The new one clears it and the node reports nothing, except that in the watchdog build a restart that kept the RAM is reported as RESET_WATCHDOG |
| 15b | Reset causes: power-up, whatever the RAM holds and the reset line | A power-up (power-on flag or power-on and brown-out flags together) with the RAM zeroed, ones or noise is never a brown-out and carries no reset bit. A reset on the reset line with the RAM kept is RESET_WATCHDOG in the watchdog build with the new bootloader and nothing otherwise |
| 15c | Reset cause: watchdog flag | The old bootloader passes it on: RESET_WATCHDOG in both builds. With the new bootloader only the watchdog build reports it and only when the RAM survived |
| 16 | Forced hang, watchdog build, new bootloader | The harness makes every ADC conversion hang for ever. The loop stops, the 8 s watchdog resets the chip, Optiboot clears `MCUSR` and starts the sketch and the first line of the next boot has RESET_WATCHDOG from the marker, `SEQ` back at 0 |
| 16b | The same hang, default build | The node stays hung for ever and never resets. This is why the flag exists |
| 16c | Forced hang, watchdog build, old bootloader | An observation that fails on anything unexpected. It accepts two outcomes only (repeated resets and no line or one reset and lines again with RESET_WATCHDOG) and records which one simavr gives. A build whose watchdog is never armed fails it. See the observation below |
| 17 | Negative temperatures | -0.9, -1.0, -1.1, -10.0 and -39.9 C print exactly (`TEMP:-1.0` and so on) with `ST:0` and all three values present. A real -1.0 C is a reading and only `ST` says whether a value is usable |
| 18 | Sensor swapped mid-run | A BME280 is swapped for a BMP280 with different calibration, then back. One line of `ST:4` each time and then the values follow the new part's own calibration (`HUM:-1` for the BMP280). The old calibration does not stay |

The gap is measured between the first bytes of consecutive lines. A line starts after the sensor reads, so a
stalled bus transfer (25 ms for each) moves a line by up to 50 ms and the next gap back by the same amount.
That is the reason for the 100 ms tolerance.

## What fails each scenario (the negative control)

A scenario that no change to the firmware can make fail is not a test. For each scenario here is a mutant of the firmware, built
outside the repository, that makes it fail. Each was run against the scenario with the harness and failed it (`FINDING` where
stated). The mutants are one-line changes.

| Scenario | Mutant that fails it |
|----------|----------------------|
| 1 | CRC start value 0x0000. Band gap constant 1000. Report interval 2200 ms (the timing check) |
| 2 | No 0x77 fallback |
| 3 | BMP280 humidity printed as 0 and not -1 |
| 4, 6, 6b | Sensor retry every 300 s and not 30 s |
| 5 | Keeps polling a lost sensor (30 failed reads before it is dropped) |
| 5b | Drops the sensor on the first failed read |
| 7a, 7b, 7c | No read-back of the control registers |
| 7d | No hold after a repeated sleep |
| 8, 8b | No Wire timeout |
| 9 | Stuck threshold 3. Stuck threshold 3000. No soft reset on a stuck sensor |
| 9b | Stuck threshold 3000. No soft reset |
| 9c1, 9c2 | Stuck threshold 1 (see the note below) |
| 9d1, 9d2 | Stuck threshold 2 |
| 9c5, 9c10, 9c20, 9d5, 9d10, 9d20 | Observations, not tests (see below). They report a `FINDING` for: threshold 2, comparing the temperature bytes only and the old oversampling of x1 |
| 10 | Water threshold 600. No probe settle time |
| 10b | Band gap constant 1000. Default supply limit 4600 and not 4000 |
| 11 | Report interval 2200 ms |
| 12 | No range check. Humidity band 0 to 100 as before |
| 13 | A pong that moves `SEQ`. A pong delayed 600 ms |
| 13b | A pong delayed 600 ms |
| 14 | A ping with no digits is answered. An over-long line that is cleared but not skipped |
| 15, 15b | Brown-out rule without the power-on test (on the old bootloader). No RAM marker (watchdog build, new bootloader) |
| 15c | Watchdog flag ignored (old bootloader). No RAM marker (watchdog build, new bootloader) |
| 16 | Watchdog never enabled (watchdog build) |
| 16b | The watchdog image run in the default build's place |
| 17 | The sign of a negative temperature lost |
| 18 | No identity and calibration reload after a sleep |

**Observations, not tests.** Scenario 16c reports whether simavr reproduces the old bootloader's reset loop and either of two outcomes is accepted, so it
records which one simavr gives, but it fails on anything else (a watchdog that is never armed). The still room sweeps at 0.2, 0.1 and 0.05 times the data sheet noise (9c5, 9c10, 9c20, 9d5,
9d10 and 9d20) cannot fail on the stuck verdict: a verdict there is reported as a `FINDING` and not a failure, so they are
labelled `OBSERVED` in the summary table when they find none. The sweeps at the data sheet noise and at half of it (9c1, 9c2, 9d1
and 9d2) are weak tests: at that noise the longest identical run is 1 or 2, so only a very small threshold fails them. The real
tests of the stuck limit are scenarios 9 and 9b. Scenario 9e only runs with a replay file.

## How the harness does the hard ones

- **Supply voltage.** simavr gives the ADC a band gap input of 1100 mV measured against the selected reference.
  The firmware selects AVcc, so the harness sets simavr's AVcc, AREF and VCC together and the count the firmware
  sees moves as a real falling or rising supply would. The LDR and moisture voltages are re-applied in the same
  ratio so their counts stay 300 and 700.
- **Serial input.** The harness raises the UART input of the simulated chip one byte at a time, 1.04 ms apart
  (9600 baud), while the firmware keeps running. It measures the pong from the last byte of the ping to the last
  byte of the pong. It finds the middle of a data line from the bytes received so far.
- **Reset causes.** The chip starts in the real bootloader image (the new one at 0x7E00 or the old one at 0x7800, from the
  pinned Arduino core) and the bootloader decides whether and when the sketch runs. simavr resets the chip and the harness
  then sets the reset flags in `MCUSR` and puts the RAM in the state a real event leaves: kept (a restart that kept power or
  a dip too short to clear it), zeroed, ones or noise (power lost). That supplies what a real event leaves behind. It does
  not lower the supply. What the node must report is worked out in the harness from the rules and not from the firmware.
- **The hang and the watchdog.** The harness hooks the ADC control register so that a conversion start is accepted
  and never completes. The firmware then waits for ever at a place with no timeout of its own. simavr's watchdog
  model resets the chip after 8 s (it measures 8.1 s here), keeps the RAM and sets the watchdog flag in `MCUSR`. The harness
  releases the hang at the reset, as a transient fault would end. The same hang on the default build never
  resets. We did not use a bus hang for this because the Wire timeout already ends one (scenario 8).
- **Time.** simavr zeroes its cycle count at a reset, so the harness keeps its own time line that runs straight
  through resets.

## What was found and what changed

**Sensor faults the earlier emulation recorded as findings are fixed.** A partial sensor reset (scenario 7b) is seen on the
first read and repaired with `BME_ASLEEP` on one line. A frozen converter (scenario 9) is called `BME_STUCK` after 60
identical reads, with one soft reset per episode. A full sensor brown-out (scenario 7a) recovers one line after it.

**The reset cause did not work on the new bootloader.** The first version read `MCUSR` and reported what it found. The
real Optiboot image zeroes `MCUSR` before the sketch starts, so the watchdog and brown-out bits were never sent on the
only bootloader the watchdog build is meant for. The old bootloader passes the flags on, but a normal power-up sets the
power-on and brown-out flags together and was reported as a brown-out. The earlier emulation started the sketch directly
with the flag written into `MCUSR`, so it could not see either. Scenarios 15 to 16 now start the chip in each real
bootloader and the node uses a `.noinit` marker where the flags are lost and reports a brown-out only with the power-on
flag clear.

**The stuck margin was thin at oversampling x1.** With 16 bit words a quiet BMP280 repeated them: at a tenth of the data
sheet noise it was called stuck and at a fifth it came within one read of the limit. The firmware now reads pressure at x16
and temperature at x2, which gives the pressure word its full 20 bit resolution. The sweep below shows the margin at the new
settings and the same sweep on a build with the old setting (a mutant kept outside the repository) shows the thin margin again.

**A swapped sensor kept the old calibration.** The firmware now reads the chip identity and calibration again whenever it
rewrites the set-up (scenario 18).

**Negative temperatures were never printed by the emulation.** Scenario 17 prints -0.9 to -39.9 C and checks the text.

**The noise sweep.** Ten minutes of still room at each noise level, 299 reads, identical on the default and watchdog builds.
The noise is a multiple of the data sheet figure for the settings in use (pressure x16 and temperature x2). The limit is 60
identical reads in a row. Each cell is the longest run, with the number of reads out of 299 whose raw bytes changed.

| Noise | BME280 | BMP280 |
|-------|--------|--------|
| 1.0 | 1 (299) | 2 (298) |
| 0.5 | 1 (299) | 2 (293) |
| 0.2 | 2 (293) | 2 (257) |
| 0.1 | 3 (276) | 4 (205) |
| 0.05 | 13 (194) | 12 (128) |

No level reaches the limit and BME_STUCK is never set, so there is no stuck finding at the new settings. A BMP280 at a tenth of the
data sheet noise has a longest run of 4 against 60, a wide margin. For comparison the old setting (x1 on both, 16 bit
words) gave a longest run of 59 at a fifth and BME_STUCK on 240 lines at a tenth and a twentieth. That run was made on a
mutant of the firmware, outside the repository, to show that the sweep can tell the two designs apart.

**Observation from scenario 16c.** The run shows one reset and lines again, so simavr's watchdog model does not reproduce the reset loop the README warns about for the
old bootloader. It keeps the 8 s timeout through the reset, where the data sheet's reset value is the shortest timeout
(about 16 ms). The warning therefore rests on the bootloader source and the data sheet and not on this run.

Behaviours worth knowing that are not faults: the first failed read already prints `-1` and the third in a
row stops the polling until the 30 s retry. A sensor that comes back is therefore picked up on the next retry
and not at once, up to about 30 seconds later.

## What simulation can and cannot show

It proves the firmware logic: the real compiled code reads the right registers, applies the compensation,
handles NACKs and timeouts, keeps its 2 second rhythm, prints the exact line format with a correct checksum, runs
the fault checks, answers a ping and starts again with the right reset bit after a watchdog reset.

It cannot show:

- Real bus electrical behaviour. simavr's TWI is message based with no SDA and SCL wires. We model a hung bus
  at the TWCR register: a START is accepted and never completes, so the interrupt flag never returns and the
  firmware has to rely on its 25 ms Wire timeout. A real stuck line can also break arbitration or clock
  stretching in ways this does not reproduce.
- ADC noise, settling or reference error. simavr converts millivolts as `mv * 1023 / vref`, where a real part
  divides by 1024. The harness applies the voltage that gives each wanted count so the check is exact.
  The 50 ms settle time of the probe's RC network is a firmware delay here and not an analogue effect.
- Real sensor timing or self-heating. The model converts in the data sheet's longest time for the settings in use. Its noise comes from our reading of the data sheet and
  has never been compared with bytes from a real part.
- UART framing errors, level shifting or cabling to the ESP32.
- Crystal tolerance. The CPU runs at exactly 16 MHz.
- The supply measurement beyond its arithmetic. Scenario 10b proves the division and the limits only, because simavr's
  band gap is exactly 1100 mV and converts at once. The 10 per cent spread between chips that `BANDGAP_MV_NOMINAL`
  calibrates, ADC noise, settling after a switch (the discarded conversions have no effect here) and supply ripple are not
  modelled. simavr also divides by 1023 where a real ADC divides by 1024, so `VCC` reads about 0.1 per cent high.
- The old bootloader's reset loop. See the observation from scenario 16c.
- Real brown-out and power-on behaviour. The harness supplies the flags and the RAM state a real event leaves. It does not
  lower the supply, so how long RAM really survives a dip is not shown.
- A real BME280. The model is a register level model of the data sheet and not a real part, so a real part's
  start-up time after a soft reset, the consistency of a burst read while it converts and its noise at the oversampling
  settings the firmware uses are assumptions. A board with a real sensor in a still room or a log of its raw words replayed
  with scenario 9e is the only proof that 60 identical reads never happen to a working part.
- The cable and the hub. Framing errors, the level shifter and the hub's own parser are not in the emulation.

## Limits of the library on this machine

The installed simavr library needs libelf for its own ELF reader and libelf is not installed. The harness reads
the ELF program headers itself and loads each segment into flash at its load address. It also defines two
unused stub functions so the link does not pull the ELF reader in. Nothing about the firmware or the CPU model
changes because of this.
