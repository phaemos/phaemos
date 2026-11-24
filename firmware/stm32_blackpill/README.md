# STM32 Black Pill F411CEU6 - Vibration Node

This node samples the MPU6050 IMU at 100 Hz, runs a 128-point FFT over each
1.28-second window and sends one checksummed line per window on USART1 to the
hub. It also answers a ping from the hub. The line looks like this (the
numbers are an example and the checksum is the real CRC of that text):

```text
VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,ST:0,SEQ:7,UP:9,MT:0,RF:0,BR:0*AD94
```

> **Status:** the firmware compiles and links for the target with no warnings
> (about 32 KB of flash and 5 KB of RAM) and every piece of logic that needs
> no hardware passes a host test and the real build runs on an emulated part
> (see [Emulation](#emulation)). **We have not yet run it on a board.** The
> clock set-up, the I2C timing and recovery, the watchdog timing and the UART
> receive path under noise are all unproven until it does (see
> [What only a board can prove](#what-only-a-board-can-prove)).

---

## Building

The project builds with [PlatformIO](https://platformio.org) using the
`ststm32` platform, the `blackpill_f411ce` board and the `stm32cube`
framework. Sources stay in `Core/Src` and `Core/Inc`. `platformio.ini` points
the build at them.

```bash
cd firmware/stm32_blackpill
pio run                  # build
pio run -t upload        # flash through an ST-Link on the SWD header
```

What the framework supplies and what lives here:

| Part | Where it comes from |
| --- | --- |
| Startup file and `system_stm32f4xx.c` | the `stm32cube` framework package |
| Linker script | the `tool-ldscripts-ststm32` package |
| HAL drivers | the `stm32cube` framework package |
| `stm32f4xx_hal_conf.h` | this folder (only the modules we use are enabled) |
| Line, CRC, statistics, status, ping and uptime logic | plain C in `Core/Src`, no HAL include |
| Clock, GPIO, I2C, UART, TIM2 and IWDG set-up | `Core/Src/main.c` and `Core/Src/stm32f4xx_hal_msp.c` |
| Interrupt handlers | `Core/Src/stm32f4xx_it.c` |
| System calls | the `nosys` specs in the framework link line |

Build flags worth knowing about:

- `-DHSE_VALUE=25000000U` matches the 25 MHz crystal.
- `-mfpu=fpv4-sp-d16 -mfloat-abi=softfp` uses the hardware FPU while keeping
  the soft-float calling convention, so objects link against the default
  libraries with no extra script.
- `-Wl,-u,_printf_float` (in `build_flags`, which the build system routes to
  the linker) lets the `%.2f` telemetry line print floats.
- `-DFFT_USE_CMSIS_DSP=0` selects the built-in FFT (see below).

---

## FFT back ends

`Core/Src/fft.c` has two interchangeable back ends behind
`FFT_GetPeakFrequency`, chosen by the `FFT_USE_CMSIS_DSP` build flag:

| Flag | Back end | Needs |
| --- | --- | --- |
| `0` (default) | self-contained radix-2 FFT in `fft.c` | nothing |
| `1` | CMSIS-DSP `arm_rfft_fast_f32` | `-DARM_MATH_CM4`, `-larm_cortexM4lf_math` and the hard-float ABI on the link line |

The default has no external dependency so the first build does not rely on a
DSP library being present in the framework package. We have not yet checked
whether it is, so the CMSIS-DSP path is untested. That library is built for the hard-float
ABI, so using it would also need an extra build script that appends the
hard-float flags to the link line.

Both back ends take a 128-point window at 100 Hz, remove the mean, skip the DC
and Nyquist bins and return the strongest remaining bin. The frequency
resolution is 100 / 128 = 0.78 Hz per bin and the Nyquist limit is 50 Hz.

### Host test

The FFT code includes no HAL header, so it also builds on a normal computer.
The test checks that 10 Hz and 25 Hz sines sampled at 100 Hz give a peak
within one bin:

```bash
cd firmware/stm32_blackpill/test_host
cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_fft.c ../Core/Src/fft.c -lm \
   -o "${TMPDIR:-/tmp}/test_fft" && "${TMPDIR:-/tmp}/test_fft"
```

---

## Clock tree - 96 MHz

| Parameter | Value |
| --- | --- |
| Clock source | HSE (25 MHz crystal) |
| PLL M divider | 25 (1 MHz VCO input) |
| PLL N multiplier | 192 (192 MHz VCO) |
| PLL P divider | 2 (SYSCLK 96 MHz) |
| PLL Q divider | 4 (48 MHz) |
| AHB prescaler | 1 (HCLK 96 MHz) |
| APB1 prescaler | 2 (PCLK1 48 MHz, limit 50 MHz) |
| APB2 prescaler | 1 (PCLK2 96 MHz) |
| Voltage scaling | Scale 1 |
| Flash latency | 3 wait states |

APB1 cannot run undivided at 96 MHz because its limit is 50 MHz.

### TIM2 - 100 Hz sampling timer

TIM2 is on APB1. When the APB1 prescaler is not 1 the timer clock is twice
PCLK1, so TIM2 runs at 2 x 48 MHz = 96 MHz.

```text
Timer tick rate  = 96,000,000 / (PSC + 1) = 96,000,000 / 9,600 = 10,000 Hz
Interrupt period = Timer tick rate / (ARR + 1) = 10,000 / 100 = 100 Hz
```

| Field | Value |
| --- | --- |
| Prescaler (PSC) | 9599 |
| Counter period (ARR) | 99 |
| Counter mode | Up |
| TIM2 interrupt priority | 1 (below SysTick at 0) |

Both PSC and ARR use (value - 1) because TIM2 counts from 0 to ARR inclusive.

The interrupt only sets a flag. The main loop reads the sensor when the flag is
set, because blocking HAL calls time out on the SysTick counter and can hang if
they run inside an interrupt that SysTick cannot pre-empt. If the main loop is
late, the missed tick is counted in `g_missed_ticks` and the partly filled
window is discarded, so a timing gap never reaches the FFT.

### I2C1 - MPU6050

| Pin | Function | Setting |
| --- | --- | --- |
| PB6 | I2C1_SCL | AF4, open drain, no internal pull |
| PB7 | I2C1_SDA | AF4, open drain, no internal pull |

- Speed: **100 kHz** (standard mode). The sensor is on a cable, whose
  capacitance slows the edges, so we do not use 400 kHz.
- The carrier board has 4.7 kohm pull-ups, so the internal pulls stay off.
- Before I2C starts and again after repeated failed reads, the firmware
  recovers the bus: it pulses SCL up to nine times until SDA reads high, makes
  a STOP condition and hands the pins back to I2C1. Without this, a sensor left
  mid-byte by a reset can hold SDA low for ever.
- After five failed reads in a row the firmware recovers the bus and
  re-initialises the sensor. While the sensor stays lost it tries again once a
  second, not every 50 ms. An exactly all-zero accelerometer reading counts
  as a failed read, because a sensor that browns out keeps acknowledging and
  returns zeros. A missing sensor at boot does not halt the node: it carries
  on, sends lines with the missing flag set and keeps retrying.
- The I2C timeout is 20 ms. A normal transfer takes about 1 ms. In the HAL driver
  (version 1.8.5, inside framework package 1.28.3) the timeout is one deadline per call, counted from the start of the call,
  plus a fixed 25 ms wait while the bus reports busy. So a failed read ends at
  the 20 ms timeout or after 25 ms on a busy bus, so about 25 ms at worst. We kept
  the timeout short so the watchdog margin below holds.
- PA0 is unused. The sensor INT line only reaches PA0 through a solder jumper
  that is open as made. PA0 is also the board's KEY button.

### Sensor low-pass filter and the sample rate

The driver sets the MPU6050 `CONFIG` register to 0x03, a 44 Hz digital
low-pass filter and we read the latest value 100 times a second. The sensor
runs its filter on a 1 kHz stream, so reading at 100 Hz is not an anti-aliasing
decimation. Anything above 50 Hz that the filter lets through folds back into
the 0 to 50 Hz span the FFT covers.

| `CONFIG` (DLPF) | Accelerometer bandwidth | Effect at 100 Hz sampling |
| --- | --- | --- |
| 0 | 260 Hz | No help: everything up to 260 Hz aliases |
| 1 | 184 Hz | Almost no help |
| 2 | 94 Hz | 50 to 90 Hz content passes and aliases at nearly full size |
| 3 (ours) | 44 Hz | Keeps the whole 0 to 44 Hz band. 50 to 60 Hz is only slightly attenuated (the data sheet gives the corner, not the slope) and still aliases |
| 4 | 21 Hz | Attenuates 50 Hz and above well, but the usable band is about 0 to 20 Hz, so a half of the FFT span is lost |
| 5 | 10 Hz | Usable band about 0 to 10 Hz |
| 6 | 5 Hz | Usable band about 0 to 5 Hz. Useless for machine vibration |

We kept 44 Hz. No setting is clearly right: a filter that removes the alias
also removes the upper half of the band the FFT reports and moving to a higher
sample rate changes the 1.28 s window the hub relies on. The limitation is
real. Mains hum at 50 or 60 Hz and a machine running at 50 to 60 Hz alias into
the 40 to 50 Hz bins (60 Hz appears at 40 Hz). The 50 Hz bin itself is skipped
by the peak search, so 50 Hz hum falls on the skipped bin and 60 Hz does not.
A peak near 40 Hz should be checked against the machine speed before it is
trusted. A higher sample rate with the same filter would fix it and is a
design change for later.

### USART1 - telemetry output

| Pin | Function | Setting |
| --- | --- | --- |
| PA9 | USART1_TX | AF7 |
| PA10 | USART1_RX | AF7, no internal pull (the board pulls it up) |

Settings: 115200 baud, 8 data bits, no parity, 1 stop bit. A 160-byte line
takes about 14 ms on the wire, longer than the 10 ms sample tick. Transmit is
therefore interrupt driven and never holds the main loop, so a sample is never
delayed by sending. A blocking send would cost a tick whatever the order of the
calls.

Every message goes through a queue (`tx_queue.c`, plain C, host tested): it is
copied into one of 4 slots of 160 bytes and sent in the order it arrived, one at
a time. A slot is released only when the HAL reports the transfer finished, so a
message that arrives while another is on the wire waits behind it and never
overwrites it. A first version let a second ping within about 0.9 ms overwrite
the first pong and a data line that came due while a zero line was still on the
wire was skipped (about one phase in 128 of the first window after an outage).
The queue fixes both. At most 2 pongs wait at once, the one on the wire
included, so a burst of pings cannot fill the queue and keep a data line out.
A pong past the limit is dropped and counted (`g_pong_dropped`) because the hub
asks again in 30 s. A line that finds every slot taken (only possible if the
transmitter has stopped) is skipped and counted (`g_tx_skipped`). A pong waits
for a line on the wire to finish (at most 14 ms), well inside its 500 ms.

Receive is interrupt driven, one byte at a time (see [Ping](#ping)).

### LED - PC13

The on-board LED is active low. It toggles once per FFT window as a heartbeat.
A slow blink (1 Hz) means the sensor is not answering, either at boot or after
it drops out while running. It is driven from the tick count, so it never
blocks the loop. A very fast blink (roughly 10 Hz, approximate) means a fault:
`Error_Handler` runs with interrupts off. Once the watchdog is running that
blink lasts about 4 s and then the chip resets (see [Watchdog](#watchdog)).

### Diagnostic counters

Three counters are sent on every line as `MT`, `RF` and `BR` and are also
visible as globals in a debugger watch window:

| Counter | Line key | Meaning |
| --- | --- | --- |
| `g_missed_ticks` | `MT` | 100 Hz ticks the main loop did not consume in time |
| `g_read_failures` | `RF` | failed sensor reads since reset |
| `g_bus_recoveries` | `BR` | I2C bus recoveries since reset |

Two more are for the debugger only: `g_rx_errors` (UART receive errors) and
`g_rx_dropped` (bytes lost because the receive ring was full).

---

## The line

```text
VIB:x,y,z,MAG:m,FFT_PEAK:fHz,RMS:x,y,z,PK:p,ST:s,SEQ:n,UP:u,MT:a,RF:b,BR:c*CCCC\r\n
```

| Key | Meaning |
| --- | --- |
| `VIB` | mean acceleration of each axis over the window in g, two decimals |
| `MAG` | vector magnitude of those three means in g, two decimals |
| `FFT_PEAK` | strongest frequency on the Z axis, one decimal. It is 0.0 when the window is stuck |
| `RMS` | root mean square of each axis with the mean removed, in g, three decimals |
| `PK` | largest absolute sample of any axis with the mean removed, in g, three decimals |
| `ST` | status bit mask as a decimal number (below). 0 means all well |
| `SEQ` | data lines sent since boot, 0 to 65535, then back to 0. The first line is 0. A pong does not move it |
| `UP` | whole seconds since boot |
| `MT` `RF` `BR` | the three counters above |
| `*CCCC` | CRC-16/CCITT-FALSE of every byte before the asterisk, four upper-case hex digits |

The keys before `RMS` keep the name, order and number format they had before.
The line is at most 160 bytes with CR LF. It is built in one fixed buffer.
Every float is clamped first (`VIB` and `MAG` to 9.99, `RMS` and `PK` to 9.999,
`FFT_PEAK` to 99.9), which fixes the longest possible line at 157 bytes with
all four counters at 4294967295, `SEQ` at 65535 and `ST` at 255 (its largest, so
NO_DATA at 128 fits). A compile-time check keeps
that figure under 160. `snprintf` is also given the space left and its result
is checked, so the builder cannot write past the buffer. The accelerometer
works at +/-2 g so no real reading is clamped.

The CRC check value for the ASCII string `123456789` is `29B1`.

### When the sensor is lost

A line is still sent every window period, with zeros in every reading and
`SENSOR_MISSING` set, so the hub can tell a lost sensor from a dead link:

```text
VIB:0.00,0.00,0.00,MAG:0.00,FFT_PEAK:0.0Hz,RMS:0.000,0.000,0.000,PK:0.000,ST:1,SEQ:8,UP:10,MT:0,RF:5,BR:1*6AFC
```

The sensor counts as lost only after five failed reads in a row (50 ms) or
when it did not answer at start-up. It stays lost until the first complete
window after it returns. While it is lost the node sends the zero line once per
window period, counted as 128 ticks of 100 Hz. `SENSOR_MISSING` is set on
exactly those lines and nowhere else.

A single failed tick is a bus glitch, not a lost sensor. It discards the partly
filled window and nothing more: no zero line is sent and `SENSOR_MISSING` stays
clear. The next complete window sends its line with `WINDOW_DROPPED` set. `SEQ`
counts only lines that were sent, so the hub sees no gap. After one failed tick
the next line can therefore be up to about two window periods after the last
one (it needs 128 good reads in a row). The hub's 15 s silence limit allows
that.

### Retry within the tick

A read that fails quickly is retried once in the same 10 ms tick, so one bad
read does not cost a whole window. The rules:

- **Quick** means the first attempt came back within 2 ms of HAL tick (a 1 ms
  counter, so the read really took under 3 ms). A normal read takes about 1 ms
  and a timeout takes 20 ms, so the two cannot be confused. The first attempt
  plus a retry of about 1 ms stays well inside the tick.
- The retry uses a short timeout of 3 ms. A timeout (the 20 ms case) is never
  retried in the same tick. There is at most one retry per tick.
- A sample that needed a retry counts in `RF` as one failed read and the
  window carries on. A tick whose two attempts both fail counts two in `RF` and
  is a failed tick exactly as before: the window is discarded.
- The five-in-a-row rule counts failed **ticks**, not attempts. A retry that
  works makes it a good tick and resets the run, so four failed ticks, one
  rescued tick and four more failed ticks is not lost.
- An all-zero triple counts as a failed read and is retried the same way.
- The decision lives in `sensor_state.c` and the per-tick logic in
  `node_core.c`, both plain C that `test_sensor_state.c` covers. `main.c` and the
  test call the same `Node_Tick`.

The cost is bounded but not measured on a board: the retry adds about 1 ms
normally and a few ms at most to a tick that already failed quickly.

### When reads keep failing (NO_DATA)

A window needs 128 good ticks in a row. If ticks keep failing, for example one
in nine because both attempts fail, no window completes and the sensor never
reaches five failed ticks in a row, so it does not count as lost. Without a
rule the node would go silent with no status bit. So when no window has
completed for two window periods (256 ticks) and the sensor is not lost, the
node sends one zero-reading line per period with `NO_DATA` (and
`WINDOW_DROPPED`, as the discard already sets it) until a window completes. The
first complete window's line clears `NO_DATA`.

- `NO_DATA` and `SENSOR_MISSING` are never set together. Lost takes precedence.
  Five failures in a row while in `NO_DATA` give `SENSOR_MISSING` lines. A
  sensor that returns clears `SENSOR_MISSING` at its first complete window and
  can then go on to `NO_DATA` if it turns flaky again.
- `RF` and `BR` keep counting, so the hub can see the failure rate.
- The node is never silent for more than two window periods in any state.
- The readings on a `NO_DATA` line are zeros and must not be used.
- A mildly flaky bus (2 per cent of read attempts failing at random) now
  completes about 95 per cent of its windows, because a tick fails only when
  both attempts fail (0.02 squared). Without the retry only about 7.5 per cent
  of windows completed. The emulation shows the difference (scenario 14).

### Status bits

| Bit | Value | Name | Set when |
| --- | --- | --- | --- |
| 0 | 1 | `SENSOR_MISSING` | the sensor counts as lost (five failed reads in a row or no answer at start-up) |
| 1 | 2 | `SENSOR_STUCK` | every sample in the window was identical on all three axes |
| 2 | 4 | `CLIPPING` | at least one sample was at full scale |
| 3 | 8 | `ID_MISMATCH` | WHO_AM_I did not read 0x68 at the last check |
| 4 | 16 | `RESET_WATCHDOG` | this boot followed a watchdog reset (held for the whole boot) |
| 5 | 32 | `WINDOW_DROPPED` | at least one partly filled window was discarded since the last line |
| 6 | 64 | `RESET_BROWNOUT` | this boot followed a brown-out reset (held for the whole boot) |
| 7 | 128 | `NO_DATA` | no window completed for two window periods although the sensor is not lost. Readings are zeros |

How each bit is decided:

- **Stuck** and **clipping** are tested on the raw 16-bit counts, before any
  scaling. Two nearly equal floats cannot be compared reliably and full scale
  is a count. Stuck means all 128 counts match on all three axes. Clipping
  means a count at or beyond full scale for the configured range. The driver
  sets +/-2 g, which is 16384 counts per g, so full scale is 32767 or -32768.
  Both numbers live in `imu_config.h` so the driver and the tests share them.
- **RMS and peak** are also worked out on the raw counts. The mean is removed
  exactly in 64-bit integers. In floats a 1 g offset would swallow the low bits
  that a few-milligram vibration lives in. A constant signal gives exactly 0.
- **Identity.** WHO_AM_I is read at start-up, after every recovery and once
  every 100 windows (about 128 s). The last value read is kept in `g_imu_id` for
  a debugger or the bench (0 until one read has worked). We accept 0x68 only
  and any other value sets `ID_MISMATCH` until the next check reads 0x68. We did
  not widen the set: the parts that answer differently are not the same chip.
  0x70 (MPU6500), 0x71 (MPU9250) and 0x98 (ICM-20689) put the accelerometer
  low-pass in a different register (`ACCEL_CONFIG2`), so the 44 Hz setting above
  would not apply to them and 0x72 is what some clone parts report, whose
  register map we have not checked. The node keeps sampling with a mismatched part, so it
  is not missing: it sends data with `ID_MISMATCH` set and the hub decides what
  to do with that. A failed read leaves the last result alone, because a bus
  that does not answer is a missing sensor and not a wrong part.
- **Sleep.** An MPU6050 that has reset keeps returning its last values. At the
  same 100-window interval and straight away on any stuck window, the node
  reads PWR_MGMT_1 and configures the sensor again if the sleep bit is set.
- **Dropped.** A window that is partly filled is discarded when a tick is
  missed or a read fails. The next line then carries `WINDOW_DROPPED` once.
- **Reset cause.** `RCC->CSR` is read first thing in `main` and then cleared.
  IWDG or WWDG gives `RESET_WATCHDOG`. On the STM32F4 the BOR flag is also set
  by a power-on reset, so we report `RESET_BROWNOUT` only when BOR is set and
  POR is not. Otherwise every cold start would look like a brown-out.
  **`RESET_BROWNOUT` probably reports nothing on a new board.** As we remember
  the reference manual (RM0383), the brown-out reset level is set by the
  `BOR_LEV` field of the flash option bytes and a new chip ships with it at
  "off" (reset value of `FLASH_OPTCR` 0x0FFFAAED, `BOR_LEV` = 0b11). With the
  level off the chip resets only at the power-on/power-down level of about
  1.8 V, which sets POR as well as BOR, so the firmware reads it as a cold
  start. Only after the option bytes enable a level (level 3, about 2.7 V, is
  the usual choice for a 3.3 V part) does a dip that stays above POR set BOR
  alone. We are about 85 per cent sure of this, from memory and not from the
  document in front of us. We keep the bit and do not write option bytes from
  the firmware. Until they are programmed treat `RESET_BROWNOUT` as never set.
  See the bench list.

### Uptime

`UP` is kept by `uptime.c`. The HAL tick is a 32-bit millisecond counter that
wraps after 49.7 days, so dividing it by 1000 would jump back. The code adds up
the milliseconds between calls with unsigned subtraction and counts whole
seconds, which is correct across the wrap as long as it is called once in 49
days. The main loop calls it every 10 ms.

---

## Watchdog

The independent watchdog (IWDG) runs from the internal LSI oscillator. The
prescaler is 64 and the reload is 2000, so the timeout is
2000 x 64 / 32000 = 4.0 s at the nominal 32 kHz. The LSI is only specified as
17 to 47 kHz, so the real timeout lies between about 2.7 s and 7.5 s.

It starts straight after `HAL_Init`, before the clock set-up and is refreshed
once per main loop pass. Starting it early means a crystal that never starts, a
PLL that does not lock or any other fault in start-up ends in a reset about 4 s
later and not in a halt for ever. Start-up needs well under a second (the
crystal wait is capped at 100 ms). A node with no crystal therefore resets every
4 s and stays silent, which the hub reports as a silent link on the present hub board. The revised hub board has a pull-down on the receive line, so there the hub reports `line_low`. We chose this over
falling back to the 16 MHz internal oscillator because a fall-back would need a
new status bit in the contract and would run the UART and the 100 Hz tick about
1 per cent off. A pass is a tick pass (read, window work, line queued) or an
idle spin between ticks. Idle spins refresh only while ticks keep arriving (one
in the last second), so a stopped TIM2 still ends in a reset.

The longest legitimate pass, from reading the code and the HAL driver (not measured):

| Step | Time |
| --- | --- |
| Failed read on a hung bus (one 20 ms deadline per call, 25 ms while busy) | up to about 25 ms |
| Sensor recovery (bus recovery under 1 ms, init stops at its first failure, one identity read) | up to about 50 ms |
| Window statistics, FFT and number formatting | estimated at a few ms |
| Line or pong transmit | nothing: queued, the UART interrupt does the rest |

A failed read followed by a recovery is the worst pass, about 75 ms, which we
round up to 0.1 s. Against the shortest possible timeout of 2.7 s the margin is
about 27 and against the nominal 4 s it is about 40. A normal pass is a few ms. None of these figures has
been measured on a board.

If a fault handler runs, nothing refreshes the watchdog, so the chip resets
about 4 s later and the next line carries `RESET_WATCHDOG`.

**Debugging.** The IWDG keeps counting while a debugger halts the core, so it
resets the chip at a breakpoint unless the debugger freezes it. In debug builds
(`DEBUG` or `__PLATFORMIO_BUILD_DEBUG__` defined) `main.c` sets
`__HAL_DBGMCU_FREEZE_IWDG()` as it starts the watchdog, which stops it
counting during a halt. Release builds do not set it. We have not tried a
debug build on a board.

---

## Ping

The hub sends `PING:<n>\n` every 30 s, with `n` a decimal from 0 to 65535 and
no checksum. The node answers within 500 ms with `PONG:<n>*CCCC\r\n`, with the
CRC taken over `PONG:<n>`. A pong is not a data line and does not move `SEQ`.

- USART1 receive is interrupt driven, one byte at a time. The interrupt
  only pushes the byte into a 64-byte ring and starts the next receive. It
  never waits.
- The main loop drains the ring into a small parser (`ping.c`) and sends the
  pong from the loop, never from the interrupt. The loop spins between ticks,
  so a normal pong goes out within a few milliseconds. It also drains the
  ring after the sensor read and after a recovery, so a slow pass on a hung bus
  should still answer inside the 500 ms. We have not measured that case.
- CR LF, LF and CR all end a line. Anything that is not exactly `PING:` and one
  to five digits no larger than 65535 is ignored and so is a line whose
  buffer (16 bytes) filled. The rest of an over-long line is skipped to its end.
- The HAL stops receiving after every byte and after an overrun. Receive is
  restarted in exactly two places, the receive-complete callback and the error
  callback, both in the interrupt. A byte received with a framing, noise or
  parity error is dropped. The main loop does not restart receive: an earlier
  version did as a safety net, but a write to the UART control register from
  the main loop is not atomic against the receive and transmit interrupts and
  could re-enable the transmit interrupt with nothing left to send. Every way
  the HAL stops receiving ends in one of the two callbacks. If the HAL ever
  refuses to restart, `g_rx_rearm_failed` counts it, so a stopped receiver is
  visible in a debugger. `test_uart.c` runs the real callbacks against a stub
  HAL for a good byte, a framing error, an overrun, a noise error, a full ring
  and a refused restart. We have not seen it recover on a real noisy line.

---

## Memory

Everything large is static, none of it on the stack.

| Buffer | Size | Where |
| --- | --- | --- |
| Raw samples for the window (3 x 128 x 2 bytes + count) | 770 bytes | `s_core.win`, inside `s_core` in `main.c` |
| Z axis as float for the FFT | 512 bytes | `s_fft_z`, `main.c` |
| FFT work buffers and twiddle tables | about 2.5 KB | static, `fft.c` |
| Line being built | 161 bytes | `s_line`, `main.c` |
| Transmit queue (4 slots of 160 bytes) | about 660 bytes | static, `uart_output.c` |
| Receive ring and ping parser | 66 and 18 bytes | static, `main.c` |

The linker script reserves a minimum of 1 KB for the stack and checks that it
fits. The stack itself starts at the top of the 128 KB of RAM and grows down, so
nothing but the static data (about 4.9 KB) sits in its way. By the compiler's
own report the deepest call chain in our code (`main`, `Line_Emit`,
`Line_Build`) uses about 400 bytes before it calls `snprintf` and the float
printing inside newlib-nano adds more that we have not measured. We would
measure the real depth on a board by filling the stack with a pattern and
checking how far it is overwritten.

Build size (release, `pio run`) is 32924 bytes of flash and 5612 bytes of RAM. It was 28472 and 3860 before the line, statistics and emulation work. Check the current figure with `pio run`: this number goes out of date with every change.

---

## Host tests

All logic that needs no hardware lives in plain C files with no HAL include, so
it builds on a normal computer: `crc16.c`, `line.c`, `window_stats.c`,
`status.c`, `sensor_state.c`, `node_core.c`, `ping.c`, `uptime.c` and `fft.c`.
`main.c` keeps the hardware calls and wires them together.

The build line in the header of each `test_host/test_*.c` file is the one source
of truth for how to build and run that test, including the sanitizer variant.
Do not copy the lines into other documents: they go out of date. To run every
one exactly as written, from a clean checkout:

```bash
cd firmware/stm32_blackpill/test_host
./run_all.sh
```

`run_all.sh` reads those header lines and runs each one, so it cannot drift from
them. It exits non-zero if any build or test fails.

| Test | What it proves |
| --- | --- |
| `test_fft.c` | 10 Hz and 25 Hz sines and two-tone cases give the right peak within one bin |
| `test_line.c` | CRC check value `29B1`, a fully worked line against a checksum computed separately in Python, the sensor-lost line, the 160-byte limit at the largest field values, clamping, the pong |
| `test_window.c` | RMS of a sine (amplitude over root two), a constant (exactly 0) and a spike, the peak, stuck and clipping at their edges |
| `test_status.c` | every status bit, the reset cause mapping, the dropped flag clearing, the identity and sleep checks |
| `test_sensor_state.c` | one failed read gives no zero line and no `SENSOR_MISSING` (the next line has `WINDOW_DROPPED`), five in a row give zero lines on the window rhythm with it, the first complete window clears it, a sensor absent at start-up counts as lost. A quick failure then success keeps the window, a quick failure twice discards it, a slow failure is not retried, five failed ticks in a row mean lost and a rescued tick resets the run and a lost sensor that returns clears the flag through the same `Node_Tick` that `main.c` uses. Failing ticks one in nine give the first `NO_DATA` line within two periods and then one per period, a complete window clears it, the hand-over between `NO_DATA` and `SENSOR_MISSING` both ways, `SEQ` without gaps, never more than two periods between lines |
| `test_ping.c` | CR LF and LF endings, split input, garbage, over-long input, no number, numbers over 65535, the receive ring |
| `test_uptime.c` | seconds counting across a simulated tick wrap |

---

## Emulation

`sim/` runs the real firmware ELF on an emulated STM32F411 in Renode with a scripted MPU6050, captures
USART1 and checks every line with its own CRC. Run it with `make sim-blackpill` from the repository root. See
[sim/README.md](sim/README.md) for the scenarios, the models and the findings.

What it proves: the compiled firmware gets through clock set-up and HAL init on the emulated part, sends a
correctly checksummed line every window, sets each status bit for the fault that should set it, keeps `SEQ`
without gaps, answers pings and ignores garbage, stops refreshing the watchdog when ticks stop (a run where the watchdog does not bite fails), does not let a line hold up the next read (shown against an instant UART model, so not the real 14 ms on the wire) and resets again and again when the crystal never starts. It also
found one design gap (silence when one read in ten fails, never five in a row), now closed by the in-tick retry and `NO_DATA`. A mutant that leaves the lost flag set after the sensor returns is caught by the LED on PC13.

What it does not prove: anything about the real clock, the I2C bus electrics, the real watchdog timeout, UART
receive under noise or real execution time. The models are simplified (the PLL is not run, the CPU speed is
set low, a failed I2C read costs a timeout) and the reset flags are injected by the harness. The next section
lists what is left for a board.

---

## Bench list

Checks to make on the first board, in order:

1. **Crystal and clock.** The node starts and sends a line. Put a scope on a
   spare pin or read `SystemCoreClock` to confirm 96 MHz.
2. **Tick period.** TIM2 at 10.000 ms on a pin and the delay from the tick to
   the I2C read, with and without a line being sent.
3. **Identity.** Read `g_imu_id` in a debugger (or watch for `ID_MISMATCH`). A
   genuine part reads 0x68. Note what a clone reads (0x70, 0x71, 0x72 and 0x98
   are all seen on "MPU6050" breakouts) before deciding whether to accept it.
4. **Sensor filter.** With a signal generator or a shaker at 60 Hz, see which
   bin it lands in (expected 40 Hz) and how large it is.
5. **I2C.** Pull the sensor cable: the node should send zero lines with
   `SENSOR_MISSING` and recover when it is plugged back in. Time a failed read.
6. **Watchdog.** Hold the crystal off or stop TIM2 in a debugger and confirm the
   reset after about 4 s and `RESET_WATCHDOG` on the next line. Measure the real
   timeout.
7. **Ping under noise.** Send `PING:42` while the sensor is failing and while
   the line is noisy and time the pong.
8. **Stack.** Fill the stack with a pattern and check how much is used with
   float printing.
9. **Brown-out level.** Read `BOR_LEV` in the option bytes with the ST-Link
   tool. Programme it to level 3 (about 2.7 V), dip the supply to between 2.0 V
   and 2.7 V and see whether the next line carries `RESET_BROWNOUT`. Without
   that step the bit reports nothing.

---

## What only a board can prove

These are untested on hardware:

- **Clock set-up.** The PLL values, flash latency and the 100 Hz TIM2 period and the delay of each read after its tick.
- **I2C timing and recovery.** The 100 kHz timing, the bus recovery pulses, the
  re-initialisation after five failures and the 20 ms timeouts. Also how long
  a hung-bus pass really takes.
- **IWDG timing.** The real LSI frequency and so the real timeout and the
  margin over the longest pass.
- **UART receive under noise.** Overrun and framing error recovery and that a
  ping is answered inside 500 ms while the sensor is failing.
- **Reset flags.** That a watchdog reset reads as `RESET_WATCHDOG` and a cold
  start does not read as a brown-out.
- **Stack depth** with float printing and the real cost of the window work.

---

---

## MPU6050 wiring

```text
MPU6050 Pin    Black Pill Pin    Notes
-----------    --------------    -----
VCC            3.3V              The F411 is 3.3V; do NOT connect to 5V
GND            GND
SCL            PB6               100 ohm series resistor recommended
SDA            PB7               100 ohm series resistor recommended
AD0            GND               Sets I2C address to 0x68
INT            Not connected     Interrupt not used - timer-driven sampling
```

The carrier board already has 4.7 kohm pull-ups to 3.3V on SCL and SDA. If you
wire a bare breakout instead, check that it has its own or add them.

---

## Flashing

### Via ST-Link V2

1. Connect ST-Link to the Black Pill 4-pin SWD header:
   - SWDIO -> A13
   - SWDCLK -> A14
   - GND -> GND
   - 3.3V -> 3.3V (only if not powered separately)
2. Run `pio run -t upload`.

### Via DFU (USB without ST-Link)

1. Hold **BOOT0** button, press and release **NRST**, then release **BOOT0**.
2. The Black Pill enumerates as a DFU device.
3. Use `dfu-util`:

   ```bash
   dfu-util -a 0 -s 0x08000000:leave -D .pio/build/blackpill_f411ce/firmware.bin
   ```

4. Or use STM32CubeProgrammer with the DFU connection type.

---

## Verifying output

Connect a USB-to-serial adapter to PA9 (TX) and GND. Open a terminal at
115200 8N1. You should see one line every 1.28 seconds:

```text
VIB:0.02,-0.01,1.00,MAG:1.00,FFT_PEAK:0.8Hz,RMS:0.004,0.005,0.006,PK:0.021,ST:0,SEQ:0,UP:1,MT:0,RF:0,BR:0*XXXX
```

(`XXXX` stands for the checksum, which depends on the digits.) Send
`PING:5` followed by a line feed from the terminal and you should get
`PONG:5*` and a checksum back.

The mean is removed before the FFT, so a stationary board shows noise and the
reported peak can sit in any bin. Tap the board or run it against a known
vibration source to see a clear peak.
