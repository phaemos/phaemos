# Arduino Nano Secondary Node

This node reads a BME280 or BMP280 (temperature, pressure and for the BME280 humidity), an LDR (light)
and an FC-28 moisture sensor. It emits one line every 2 seconds over Serial at 9600 baud and answers a
ping from the hub. A value of -1 means a reading is absent. A BMP280 has no humidity element so it always
sends `HUM:-1`.

Example output (the checksum at the end is real):
```
TEMP:25.1,HUM:50.7,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:0,SEQ:12,UP:26,VCC:4980*F6B1
```

---

## The line

The line is ASCII and ends in CR LF. The first six keys are unchanged. We append four more and then a
checksum:

| Key | Meaning |
|-----|---------|
| `ST` | Status bit mask as a decimal number. 0 means all is well (table below) |
| `SEQ` | Data lines sent since boot, 0 to 65535, then back to 0. A pong does not move it |
| `UP` | Whole seconds since boot |
| `VCC` | The supply in millivolts, measured against the internal 1.1 V reference |
| `*CCCC` | CRC-16/CCITT-FALSE of every byte before the star as four upper-case hex digits (polynomial 0x1021, start 0xFFFF, no reflection, no final XOR). The check value of `123456789` is `29B1` |

A line is at most 160 bytes with its CR LF. A lost sensor never looks like a dead link: the line still comes
every 2 seconds with `-1` readings and `ST` says why.

| Bit | Value | Name | Set when |
|-----|-------|------|----------|
| 0 | 1 | BME_MISSING | The sensor does not answer |
| 1 | 2 | BME_STUCK | Every raw value (temperature, pressure and humidity on a BME280) was byte-identical for 60 reads in a row (120 s) |
| 2 | 4 | BME_ASLEEP | The control registers did not read back as written, so the part was not converting. We read the identity and calibration again, rewrite the set-up at once and the bit clears on the next good read. A part that falls asleep twice within 10 reads keeps the bit for the next 5 lines |
| 3 | 8 | SUPPLY_RANGE | `VCC` is under 4000 or over 6000 (under 4500 or over 5500 once the band gap is calibrated, see Supply voltage) |
| 4 | 16 | RESET_WATCHDOG | This boot followed a watchdog reset (held for the whole boot). With the new bootloader, which clears the flags, it means the node restarted with its RAM intact while the watchdog build was running: a watchdog reset, the reset line or a brown-out or power dip that kept RAM (see Reset cause) |
| 5 | 32 | RESET_BROWNOUT | This boot followed a brown-out: the brown-out flag set with the power-on flag clear (held for the whole boot). Never sent with the new bootloader |
| 6 | 64 | BME_RANGE | Temperature outside -40 to 85 C, pressure outside 300 to 1100 hPa or humidity, before clamping, under -5 or over 105 per cent |

While BME_MISSING, BME_STUCK, BME_ASLEEP or BME_RANGE is set the three sensor values are sent as `-1`, so a
frozen or impossible value never reaches the hub as a reading.

**What the node does about a sensor fault.** Each cycle we read `ctrl_meas` (and `ctrl_hum` on a BME280) back.
If they are not what we wrote, the part has reset its set-up and sits in sleep mode while still answering. We
set BME_ASLEEP, read the chip identity and calibration again (the part may have been swapped for another one),
write the set-up again and discard that cycle, so one line carries `ST:4` and the next is good. A part that falls
asleep twice within 10 reads is flapping and then the bit stays set, with `-1` values, for the next 5 lines so that it
shows on consecutive lines (the hub treats a bit on a single line as a glitch).
If every raw value is identical for 60 reads we set BME_STUCK and try one soft reset (register 0xE0, value
0xB6), then read the identity and calibration again and write the set-up again, once per stuck episode. That is the only
repair the node can make. The episode ends on the first read that differs and the next one may use a reset again.
We compare all the raw values together because a real sensor in a still room can hold one channel steady for
minutes (temperature with the heating off) while its pressure word moves with the converter's own noise. A converter
that has frozen freezes every channel at once.

**Sensor set-up.** We read pressure at oversampling x16 and temperature at oversampling x2, with humidity at x1 on a
BME280, in normal mode with the filter off and 0.5 ms standby: `ctrl_meas` is `0x57` (010 for temperature, 101 for
pressure and 11 for normal mode), `ctrl_hum` is `0x01` and `config` is `0x00`. That is the data sheet's ultra high
resolution setting. The pressure word then has its full 20 bit resolution (0.16 Pa a count) and the converter's own noise
(1.3 Pa rms in the data sheet, about 8 counts) moves it on nearly every read. At oversampling x1 the word has only 16 bits
and a quiet part could repeat it, which is why the stuck test needed this. The longest conversion is 43.2 ms on a BMP280
(data sheet table) and 46.1 ms on a BME280 by the data sheet formula
1.25 + 2.3 x 2 + (2.3 x 16 + 0.575) + (2.3 x 1 + 0.575) ms. With 0.5 ms standby the part converts about 21 times a second,
so the report every 2 seconds always finds a fresh result. The only wait is 50 ms after set-up so that the first read is
real. The compensation maths already takes 20 bit raw values, so nothing in it changes: the largest intermediate in the
32 bit pressure formula is 1048576 x 3125, which is under 2^32.

The emulation sweeps the converter's noise from the data sheet figure down to a twentieth of it and reports the longest
run of identical reads against the limit of 60 (see `sim/README.md`). With the noise at a tenth of the data sheet figure the longest run is 4 reads on a BMP280 and 3 on a BME280 and at a twentieth 12 and 13, so the margin to 60 is wide at every level. The limit has not been checked against
logged bytes from a real part.

> [!NOTE]
> BME_RANGE tests the humidity before the data sheet clamp to 0 to 100 per cent, because a clamped value always
> passes. A working BME280 in condensing air can compute a little over 100 per cent, so the bit is set only
> under -5 or over 105 per cent. Inside that band the printed humidity is clamped to 0 to 100 and nothing is set.

## Ping

The hub sends `PING:<n>` and a line feed every 30 seconds, where `n` is a decimal number from 0 to 65535. We
answer `PONG:<n>*CCCC` and CR LF within 500 ms (the slowest answer in the emulation is under 200 ms). The ping has
no checksum. We read the serial input without ever waiting, ignore anything that is not exactly a ping and
clear a receive buffer that fills, together with the rest of that over-long line. A pong does not move `SEQ`
and does not disturb the 2 second rhythm of the data lines.

## Supply voltage

`VCC` comes from the standard method: the ADC takes the internal band gap as its input with AVcc as the
reference, waits 2 ms for the band gap to settle, discards the first conversion and keeps converting until two in a
row agree within one count (three conversions in all when the supply is steady). The ADC is shared with the LDR and
the moisture probe, so the multiplexer is put back afterwards and the first conversion after each switch is
discarded.

The band gap is nominally 1.1 V but it varies by about 10 per cent between chips, which is as large as the whole
SUPPLY_RANGE window. `VCC` is always printed as measured. Until a board is calibrated the SUPPLY_RANGE limits are
4000 and 6000 mV, which still catch a rail that has really gone. Once it is calibrated they are 4500 and 5500 mV.

To calibrate: measure the 5 V pin with a meter, set `BANDGAP_MV_NOMINAL` in `sensors.cpp` so the printed `VCC`
matches the meter, then build with `BANDGAP_CALIBRATED` set to 1. The environment `nanoatmega328new_cal` does that
for the new bootloader. The same flag works on any environment with `-DBANDGAP_CALIBRATED=1`.

A Nano powered over USB may sit near 4.6 V after the diode on the board (a figure we have not measured on this board),
which would be only about 100 mV above the lower calibrated limit. A calibrated build on a USB-powered bench board could
then report SUPPLY_RANGE for a healthy supply.

## Reset cause

We read `MCUSR` in a function placed in the `.init3` section so that it runs before anything else, keep it in a
`.noinit` variable and clear the register. What reaches us depends on the bootloader. We read both bootloaders'
source in the pinned Arduino core and ran the real bootloader images in the emulation:

| Bootloader | What it does with `MCUSR` | What we report |
|------------|---------------------------|----------------|
| New (Optiboot 4.4, `nanoatmega328new`) | Reads it, writes zero to it and starts the sketch. We always read 0. After a reset on the reset line it waits a second and restarts itself through its own watchdog first | No flag ever arrives, so the marker below decides |
| Old (ATmegaBOOT_168, `nanoatmega328`) | Leaves it alone, so we read the real flags | The flags: RESET_WATCHDOG when the watchdog flag is set. RESET_BROWNOUT when the brown-out flag is set **and the power-on flag is clear**, because an ordinary power-up sets both flags together |

Where the flags read 0 we tell a restart that kept power from a power-up with a marker in `.noinit`. The sketch writes
the marker (a 32 bit magic number and its complement, 8 bytes) at the end of `setup()` and `.init3` checks and clears
it. RAM that still holds it means the node restarted without losing power. In the watchdog build we report that as
RESET_WATCHDOG: it was a watchdog reset, the reset line or a brown-out or dip that kept the RAM and the node cannot tell which. In the default build we send
no reset bit in that case.

After a real power loss RAM is not guaranteed to be random: it can hold zeros or ones or part of its old content for
a moment. A match of 8 bytes against the magic and its complement by chance is out of the question for any of those. A
brief power dip that does not clear RAM looks exactly like a restart that kept power, so in the watchdog build with the
new bootloader it is reported as RESET_WATCHDOG. A real brown-out that does clear RAM is reported as nothing on the new
bootloader. The new bootloader therefore never sends RESET_BROWNOUT.

## Watchdog (off by default)

The build flag `NANO_WATCHDOG` turns the watchdog on. It is off unless you ask for it. The reason is the
bootloader. Many Nano boards carry the older bootloader, which does not turn the watchdog off after a watchdog
reset. The watchdog is still running when the bootloader starts, so the board resets again and again until it is
power-cycled. A board with the new bootloader recovers by itself. Do not build with the flag for a board with the
old bootloader unless you have replaced the bootloader. The emulation cannot show this loop: simavr keeps the 8 s
timeout through the reset where the data sheet's reset value is the shortest timeout, so the warning rests on the
bootloader source and the data sheet. The sketch's own start-up switches the watchdog off, but only after the old
bootloader has run for far longer than the shortest timeout.

With the flag on we call `wdt_disable()` in `.init3`, enable the watchdog at 8 s at the end of `setup()` and reset
it once per pass of `loop()`. The longest legitimate pass, read off the code, is about 0.35 s:

| Part of a pass | Longest |
|----------------|---------|
| Probe both I2C addresses after a lost sensor (two timeouts of 25 ms each way, plus the transfers that did work) | about 130 ms |
| Settle after a sensor is found, then one read that times out twice | 50 ms and 50 ms |
| A sleeping or frozen part: identity and calibration read again, then the set-up written | about 100 ms |
| Moisture probe settle | 50 ms |
| Supply measurement (2 ms settle and three conversions) | about 3 ms |
| Sending the line (about 105 bytes through a 64 byte buffer at 9600 baud) | about 45 ms |
| Sending a pong | about 15 ms |

If every one of those fell in the same pass the pass would still be about 0.35 s, well under the 8 s limit, so only a real hang trips it. The Wire library already ends a stuck I2C bus
after 25 ms, so what the watchdog covers is the rest, such as an ADC conversion that never ends.

## Memory

This chip has 2 kB of RAM and 32 kB of flash (30 kB left after the bootloader). The line is built in one fixed
buffer of 160 bytes, the checksum is worked out over that buffer and there are no `String` objects and no
dynamic allocation. Constant text uses `F()`.

| Build | Flash before | Flash after | RAM before | RAM after |
|-------|--------------|-------------|------------|-----------|
| `nanoatmega328` (the default environment) | 8980 B | 10718 B (34.9 %) | 527 B | 688 B (33.6 %) |
| `nanoatmega328new` (same code, new bootloader) | 8980 B | 10718 B (34.9 %) | 527 B | 688 B (33.6 %) |
| `nanoatmega328new_wdt` (watchdog on) | not built | 10840 B (35.3 %) | not built | 689 B (33.6 %) |
| `nanoatmega328new_cal` (band gap calibrated) | not built | 10718 B (34.9 %) | not built | 688 B (33.6 %) |

---

---

## Wiring

### BME280 or BMP280 (I2C)

On the carrier board the I2C lines go through the board's own level shifters to the 3.3 V breakout, with the
pull-ups on the board. A bare jumper-wire build needs the same two level shifters and 3.3 V pull-ups: the Wire
library switches on the Nano's internal pull-ups to 5 V, so the breakout must not be wired straight to A4 and A5.
The table lists the connections of the breakout itself.

| Breakout Pin | Nano Pin | Notes                             |
|------------|----------|------------------------------------|
| VCC        | 3.3V     | The breakout is 3.3V; do NOT use 5V |
| GND        | GND      |                                    |
| SCL        | A5       | I2C clock - shared bus             |
| SDA        | A4       | I2C data - shared bus              |
| SDO        | GND      | Sets I2C address to 0x76 (default) |
| CSB        | 3.3V     | Selects I2C mode (not SPI)         |

> The firmware tries 0x76 first and falls back to 0x77 automatically.
> SDO tied HIGH sets address 0x77.
> The chip ID tells the parts apart (0x60 is a BME280 and 0x58 is a BMP280).
> If no sensor answers at start-up we probe again every 30 seconds so a sensor plugged in late is picked up.

### LDR (Light Sensor) - A0

Wire the LDR as a voltage divider between 5V and GND with a 10 kohm resistor:

```
5V ---[LDR]--- A0 ---[10k]--- GND
```

Higher light = lower resistance = higher voltage = higher ADC reading (0-1023).

### FC-28 Moisture Sensor - A1

| FC-28 Pin | Nano Pin | Notes                                 |
|-----------|----------|---------------------------------------|
| VCC       | 5V or D7 | Chosen by solder jumper JP1 (see below) |
| GND       | GND      |                                       |
| AO        | A1       | Analogue output - used by this firmware |
| DO        | Not used | Digital output - threshold not used   |

Lower ADC value = wetter soil. Values below 500 trigger `WATER:1` in output.
A 100 k pull-up on the board means an unplugged sensor reads high, which is the same as dry soil. **Known limit:**
the node cannot tell an unplugged probe from a dry one on this board. Both read about 1023, there is no status bit for
it and an unplugged probe never reports water. A `WATER:0` therefore also covers a probe that is not connected.

**Power jumper JP1.** Bridged 1 to 2 (as made) the module has 5 V all the time and D7 is not connected.
Bridged 2 to 3 the module is powered from D7. The firmware drives D7 HIGH for 50 ms before each moisture
read and LOW afterwards, so the probe is only powered while it is read and corrodes more slowly.
Driving D7 is harmless when the jumper is on the 5 V rail.

> [!WARNING]
> A Nano pin is limited to 20 mA. Measure the module's current before moving JP1 to 2 to 3.

**Calibration.** The threshold of 500 assumes the FC-28 on 5 V. The board's 100 k pull-up can shift a
mid-range reading by up to about 5 per cent. Calibrate on the finished board, which has not been done yet: read dry air and a glass of
water then set `isWaterDetected` in `sensors.cpp` accordingly.

---

## Connecting to the hub

The serial link carries the 9600 baud line to the hub and the hub's ping back, so both directions are used. The carrier
board has two circuits and `hardware/wiring/nano_pinout.md` has the full table.

| Nano pin | Direction | Circuit on the carrier board | Level at the far end |
|----------|-----------|------------------------------|----------------------|
| TX (D1)  | Nano to hub | Resistor divider, 10 k from D1 to the hub's receive pin and 20 k from there to GND | 3.33 V for a high, source resistance about 6.7 k |
| RX (D0)  | Hub to Nano | Transistor level shifter, a BSS138 with 100 R in series and 10 k to 5 V, not inverting | D0 sees 5.0 V for a high and about 0.5 V for a low |
| GND      | Both        | Common ground | Required |

> [!WARNING]
> The Nano's UART outputs 5V logic but the ESP32's RX pin only tolerates 3.3V. The divider on the carrier board is
> what protects it. A bare jumper-wire build without the carrier board needs the same two circuits, one on each
> direction.

> The Nano's USB-to-serial chip also drives D0 through 1 k and D1 feeds its input. A ping arriving during an upload
> could corrupt the upload and whether uploading over USB works with the link attached is a bench check and not a known
> fact. Unplug the link to upload until it has been checked.
> The firmware reads its serial input only to answer a ping. It never waits for input.

---

## Building

We build with [PlatformIO](https://platformio.org/). The settings live in `nano_node/platformio.ini`
and the platform version is pinned. No external libraries are needed because the sensor is read by a small
driver in `sensors.cpp`.

```bash
cd firmware/arduino_nano/nano_node
pio run -e nanoatmega328new   # Nano with the new bootloader
pio run -e nanoatmega328      # Nano with the old bootloader (many clones)
pio run -e nanoatmega328new -t upload
pio run -e nanoatmega328new_wdt   # new bootloader with the watchdog on (NANO_WATCHDOG)
pio run -e nanoatmega328new_cal   # new bootloader with the band gap calibrated (BANDGAP_CALIBRATED)
```

Pick the environment that matches the bootloader. If an upload fails with the new one try the old one.
`nanoatmega328new_wdt` is for the new bootloader only (see the watchdog section above). Both
settings compile with the commands above. A default build uses about
10.7 kB of the 30 kB flash and about 0.7 kB of the 2 kB RAM.

To use the Arduino IDE instead open `nano_node/nano_node.ino`, choose **Arduino Nano** and the matching
processor (ATmega328P or ATmega328P (Old Bootloader)) then upload. Open the Serial Monitor at 9600 baud to
check the output.

---

## Emulation test

We run the compiled firmware, the default build and the watchdog build, on a simulated ATmega328P with a
simulated BME280 or BMP280 and simulated analogue inputs, so the behaviour can be checked without hardware.
The scenarios cover a healthy BME280 and a BMP280. They also cover a missing sensor, a sensor that stops
answering or comes back or resets (including a reset of only the control registers), a hung I2C bus, frozen
data and a still room, the analogue inputs, the supply voltage, impossible values, the ping, junk on the
serial input, both reset causes, a forced hang that the watchdog must clear and the 2 second timing. The reset
cause scenarios start the chip in the real new and old bootloader images. Every line is checked against an independent
CRC-16 written from the definition.

```bash
make sim-nano   # from the repository root, needs PlatformIO and simavr
```

The run exits non-zero if any scenario fails. See `sim/README.md` for the scenarios and for what the
simulation can and cannot prove. It cannot show the old bootloader's reset loop (simavr's watchdog model does not
reproduce it), how long RAM survives a power dip, the band gap spread or how a real sensor behaves. No bytes logged
from a real sensor have been replayed. Those need a board.

---

## Troubleshooting

| Symptom                        | Cause                              | Fix                                |
|--------------------------------|------------------------------------|------------------------------------|
| `TEMP:-1,HUM:-1,PRES:-1` with `ST:1` | No BME280 or BMP280 found on I2C bus | Check wiring, try swapping SDO to 3.3V (address 0x77) |
| `-1` readings with `ST:2`      | Every raw value was identical for 60 s | The sensor has frozen. We try one soft reset, then check the part and its supply |
| `-1` readings with `ST:4` for one line | The sensor reset its own set-up | Nothing, we rewrote it. If it repeats, check the 3.3 V supply of the breakout |
| `-1` readings with `ST:64`     | A value outside the data sheet range | Check the part and wiring |
| `ST:8`                         | `VCC` under 4.0 V or over 6.0 V (4.5 and 5.5 when calibrated) | Check the supply, then calibrate `BANDGAP_MV_NOMINAL` |
| `ST:16` on every line          | The last reset was the watchdog (old bootloader) or in the watchdog build with the new one a restart that kept its RAM: a watchdog reset, the reset line or a brown-out that kept RAM | Look for what hung or whether the hub reset the node |
| `ST:32` on every line          | The last reset was a brown-out. Only the old bootloader passes this on | Check the supply and the USB cable |
| No pong                        | The hub's transmit line is not reaching D0 | Check the level shifter on the carrier board or the same circuit on a bare build and that the hub's TX goes to D0 |
| `HUM:-1` with real TEMP and PRES | The breakout is a BMP280 (no humidity) | Expected, nothing to fix        |
| `LIGHT:0` always               | LDR wiring error                   | Check voltage divider polarity     |
| `MOIST:0` always               | FC-28 has no power                 | Check the JP1 position and the module's VCC |
| No output on Serial Monitor    | Wrong baud rate or board reset     | Set monitor to 9600 baud           |
