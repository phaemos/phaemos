# Black Pill emulation test

We run the real compiled Black Pill firmware (`firmware.elf` from PlatformIO, unchanged) on an emulated
STM32F411 in [Renode](https://renode.io) 1.17. A scripted MPU6050 sits on the emulated I2C bus. The harness
reads what the firmware sends on USART1, checks every line with its own CRC and line parser and drives the
sensor, the ping input and the fault conditions. No hardware is needed and no firmware source is changed.

This is evidence about the firmware logic. It is not evidence about the board (see the end).

## Running it

From the repository root:

```bash
make sim-blackpill
```

That runs `pio run` and then every scenario. The exit code is non-zero if any scenario fails. A scenario that could not run
counts as a failure too (`NOT RUN`), unless it is named on the command line with
`--optional N`. A `FINDING` does not fail the run and a scenario left out by the command line
(the 128 s one without `--long`) is listed as `SKIPPED`.

Options, passed with `ARGS` from this folder:

```bash
cd firmware/stm32_blackpill/sim
make run ARGS="--only 5 -v"      # one scenario by number, with every check printed
make run ARGS="--long"           # also the 128 s scenario (about 3 minutes)
make run ARGS="--jobs 2"         # fewer Renode processes at once (default 4)
make negative-control            # broken firmware that the harness must fail
```

Needs PlatformIO, Python 3 (standard library only) and Renode. The default path is
`~/Applications/Renode.app/Contents/MacOS/macos_run.command`. Override it with `make run RENODE=/path`.
Build output and the generated Renode scripts go to `sim/build/`, which `.gitignore` already covers.

Simulated time is not real time. A scenario takes from 15 s to a few minutes of wall time (the 128 s one about 3 minutes) and each runs in its own
Renode process, several at once. The CPU is set to 8 MIPS (`--mips`). That is far slower than the real 96 MHz,
so the code runs in the emulator at a pace that keeps the run short and the 10 ms tick still holds (MT stays
0 in the healthy scenario). It also means every timing that depends on how fast the CPU runs is not
representative (see below).

## What is in this folder

| File | Purpose |
|------|---------|
| `run_sim.py` | The runner: starts Renode per scenario, drives it through the monitor, captures USART1 over a socket, checks it |
| `blackpill.repl` | The board: STM32F411CEU6 built from the Renode STM32F4 peripheral models |
| `blackpill.resc` | Loads the board, the sensor model and the ELF. Defines the reset macro the watchdog needs |
| `mpu6050_sim.cs` | The scripted MPU6050 (C#, compiled by Renode when it starts) |
| `Makefile` | `run`, `firmware` and `negative-control` |

## How the board is modelled

Renode ships no F411 platform, so `blackpill.repl` lists what the firmware touches and reuses the F4 models
from `platforms/cpus/stm32f4.repl`: the Cortex-M4 and NVIC, the F4 RCC, flash controller and PWR, TIM2, the IWDG,
GPIO ports A to C, USART1 and the I2C1 model. Memory is the F411's 512 KB flash and 128 KB SRAM. The bit-band
alias of the peripheral space is mapped because the HAL switches the PLL through it. The SysTick source is
96 MHz and TIM2 is fed 96 MHz. Those two numbers are set in the board file, not derived from what the firmware
programs into the RCC.

The firmware gets through clock set-up and HAL init on the first try. The RCC model reports the crystal and
the PLL ready at once, so the wait loops pass. The harness reads the registers back (scenario 1) to show the
firmware wrote the values we intend, but the emulator does not run a PLL, so that shows what the firmware
asked for and not that a real PLL would lock.

Renode's logging of unhandled register accesses during boot lists 16 distinct accesses. All are harmless bits
the models do not implement: the flash prefetch and cache enables, the GPIO output type bits for the I2C
pins, the I2C ACK and SWRST bits and a CCR field. Nothing the firmware depends on is missing.

## The simulated sensor

There is no MPU6050 model in this Renode release and its Python peripherals are memory-mapped only (they
cannot sit on an I2C bus). So `mpu6050_sim.cs` is a C# peripheral that Renode compiles when it starts. It
implements the I2C slave interface on the `STM32F1_I2C` model (the F4 I2C block has the same registers and the
F4 HAL runs against it).

It is a register model, not a list of canned replies: `WHO_AM_I` (0x75), `PWR_MGMT_1` (0x6B, power-up value
0x40), `CONFIG`, `GYRO_CONFIG`, `ACCEL_CONFIG` and the six accelerometer registers, with the register pointer
incrementing on reads. The axis block is latched when the X high byte is read. A sleeping part keeps returning
its last sample. A part that is plugged in again starts as after a power-up: asleep, registers at their reset
values and zero data.

The harness sets a sine (frequency, amplitude and offset per axis, in raw counts, one sample per read), a
constant, a frozen value, a wrong WHO_AM_I, the sleep bit, one or a run of all-zero reads and unplug or plug.
The firmware counts an all-zero triple as a failed read, so that is how a single failed read is injected.

Unplugging moves the part to another address and resets the controller, because the Renode I2C model keeps its
current slave between transfers and would otherwise keep answering. The firmware then sees the peripheral stop
responding and recovers it as it would after a bus fault.

## Scenarios

The summary table at the end of a run lists each one as `PASS`, `FAIL`, `FINDING` or `NOT RUN`. `FINDING`
means the real firmware ran and showed behaviour we consider a design fault. We did not change the firmware to
hide it.

| # | Scenario | What it checks |
|---|----------|----------------|
| 1 | Boot, clock and register read-back | A line arrives after clock set-up and HAL init. PLL, bus prescalers, TIM2 PSC and ARR, IWDG reload, USART1 BRR and ACCEL_CONFIG read back as intended. Unhandled register accesses are listed |
| 2 | Healthy sensor, 10 Hz sine on Z | One line every 1.28 s of simulated time, CRC good on every line, SEQ without gaps from 0, UP advancing, FFT_PEAK within one bin of 10 Hz, RMS z near amplitude over root two, PK near the amplitude, MT RF BR zero |
| 3 | Sensor absent at boot, then appears | Zero lines with SENSOR_MISSING on the normal rhythm, then a good line with ST 0 after the sensor appears |
| 4 | Sensor lost mid-run, then returns | Zero lines on the rhythm while lost, SENSOR_MISSING clears on the first complete window, readings are the signal again. The LED on PC13 blinks every 0.5 s while lost and goes back to one toggle per window afterwards, which only happens if the lost flag cleared |
| 5 | One failed tick (both attempts) | No zero line and no SENSOR_MISSING, WINDOW_DROPPED on the next line only, SEQ without a gap, RF counts the two failed attempts |
| 6 | Frozen data | SENSOR_STUCK and nothing else, RMS 0, FFT_PEAK 0.0, clears when the data moves |
| 7 | Full-scale data | CLIPPING on a signal that goes past +2 g, not on a 31000 count peak and at exactly 32767 |
| 8 | WHO_AM_I wrong | ID_MISMATCH on every line while sampling carries on |
| 9 | Sleep bit set mid-run | A stuck window is reported, the firmware finds the sleep bit, rewrites the configuration and the part wakes |
| 10 | Ping and pong | Garbage and malformed pings get no reply. `PING:42` gets `PONG:42*881F`, within 500 ms of simulated time. 0 and 65535 work, CR LF works, a split ping works, an over-long line is skipped, a pong does not move SEQ |
| 11 | Watchdog resets a hung node | The harness stops TIM2 (a hang). The firmware stops refreshing the IWDG after a second without ticks and Renode's IWDG must reset the machine within 8 s of the hang. If it does not the scenario FAILS. SEQ and UP restart |
| 12 | RESET_WATCHDOG after the reset | As 11, with the reset flag injected (see below). The first line of the new boot carries RESET_WATCHDOG and the next one holds it |
| 13 | One read in ten fails: retried | A quick failure is retried in the same tick, so windows keep completing on the 1.28 s rhythm with no zero line, no NO_DATA and no WINDOW_DROPPED. RF still counts the failed reads |
| 14 | 2 per cent of reads fail at random | 60 s with each read attempt failing at random: most windows complete, NO_DATA is rare, never silent for more than two periods, RF shows the failure rate, the 10 Hz peak is intact |
| 15 | Both attempts fail, one tick in nine: NO_DATA | Failures the single retry cannot rescue: the first NO_DATA line within two periods of the last good line, then one per period with zeros, WINDOW_DROPPED, no SENSOR_MISSING, RF counting. A complete window clears it |
| 16 | No tick lost around a line | The sensor model times every read-to-read gap in 7 s: none over 11 ms or under 9 ms, so the loop does not wait on a line. MT is 0 on every line. The model's UART has no wire time, so this does not show the real 14 ms |
| 17 | Crystal never starts: watchdog resets | A read hook holds HSERDY low. The node cannot start the clock, so the watchdog (started before the clock set-up) resets the chip about every 4 s and no line is sent. When the crystal comes back the node boots and sends lines |
| 18 | Pings close together and during a line | Two pings 0.5 ms apart, a burst of six and forty pings around a line: every pong is whole, in order and none twice and the data lines are untouched. It checks the end to end path. The overlap itself is in the host test, because the model's UART takes no wire time |
| 19 | Periodic WHO_AM_I check | Needs 128 s of simulated time. Run with `--long`. A default run lists it as SKIPPED |

Line timing is measured in every scenario with a poll every 0.05 s of simulated time, so each arrival is good
to that step. Gaps in scenario 2 measured 1.25 to 1.30 s against the 1.28 s expected and the limit is the
step plus a little.

## Findings

**Closed: a mildly flaky bus lost most windows.** With 2 per cent of read attempts failing at random, the first
version completed only about 7.5 per cent of its windows, because one failure discarded the window. The in-tick
retry fixes it at the read: a tick now fails only when both attempts fail, so about 95 per cent of windows
complete. In 60 s of simulated time scenario 14 gave 44 data lines and 1 NO_DATA line out of 45, with RF at 138 and a longest gap of 2.50 s. The same scenario on the no-retry mutant gave 7 data lines and 35 NO_DATA lines out of 42.

**Closed: silence with one read in ten failing.** The first version of the lost-sensor rule left the node
silent here. The retry rescues it (scenario 13) and when failures are bad enough to defeat the retry the
`NO_DATA` bit covers it (scenario 15): no window for two periods while the sensor is not lost gives one zero line
per period. The node is never silent for more than two window periods.

**A failed tick delays the next line (scenario 5).** The line after a failed tick arrives a full window
after the failure, so it can be up to about two window periods after the previous line. In the run the lines
came at 1.30 s, 3.20 s and 4.50 s, a gap of 1.9 s. The hub's 15 s silence limit allows that.

**The emulation missed a bug once.** The call that clears the lost flag was missing from `main.c` and nothing
showed it because data lines still went out. Scenario 4 now reads the LED on PC13: the slow blink must stop and
the per-window heartbeat must return. The negative control has a mutant that removes the call.

## What is a model artefact

- The I2C model cannot answer with a NACK or an error: a missing device simply times out (20 ms, never retried).
  A quick failure is modelled in the sensor instead, as an all-zero triple that returns at once, which the
  firmware counts as a failed read and retries the same way as a bus error. The retry decision on a real
  bus error is covered by the host test, not by this model.
- A failed read costs a 20 ms timeout in the I2C model, which costs ticks. After a sensor loss the MT, RF and
  BR counters therefore climb far faster than they would on a board, where a missing device is refused at once.
  The counters are not checked against numbers in those scenarios.
- The UART model takes no wire time: a byte leaves as soon as the transmit interrupt runs, so a 160 byte line
  costs a few ms of emulated CPU and not the 14 ms it takes at 115200 baud. The CPU runs at 8 MIPS, so the window
  work, the recovery time and the pong latency (0.12 s in the run) are not representative. Because the transfer
  is over so fast, the emulation cannot make two messages overlap on the wire. A transfer in flight is covered by
  the host test `test_host/test_uart.c`, which steps the transmitter byte by byte. Scenario 16's mutant adds a
  14 ms `HAL_Delay` after the send to stand in for the wire time of a blocking transmit.
- The emulated TIM2 ticks about 1 per cent fast: the read-to-read gaps in scenario 16 measure 9.89 to 9.91 ms against 10 ms. The line spacing is still within the checks. Scenario 16 therefore tests that nothing delays a tick, not the absolute period.
- The RCC model sets neither IWDGRSTF nor the other reset flags. Scenario 12 injects them (below).
- The IWDG model uses the nominal 32 kHz LSI, so its 4.0 s is the nominal figure, not the 2.7 to 7.5 s the
  real part's LSI spread allows.

Scenario 12 sets the reset flag with a Renode read hook on RCC_CSR, installed in the reset macro, so it is
active only from the first reset. The hook does what silicon does: sets IWDGRSTF and clears the power-on flags.
That proves the firmware reads the flag, reports it, holds it and does not report a brown-out. It does not prove
that the hardware sets the flag. The default value the model gives (power-on, pin and brown-out reset
flags set) shows the firmware does not report a brown-out on a cold start, because every other scenario's
first line has ST 0.

## Negative control

`make negative-control` copies the firmware sources to a temporary folder outside the repository, applies a
deliberate fault, builds it with PlatformIO and requires that the harness fails. Every scenario has at least one
mutant that must make it fail and the run reports any scenario that has none.

| Fault | Scenario that must fail |
|-------|-------------------------|
| PLL N changed from 192 to 191 | 1 |
| CRC start value 0x0000 instead of 0xFFFF | 2 |
| RMS keeps the mean | 2 |
| No zero line while the sensor is lost | 3 and 4 |
| The lost flag is never cleared | 4 (the LED keeps blinking slowly) |
| One failed read counts as lost | 5 |
| Stuck windows never detected | 6 |
| Clipping limit raised so it never triggers | 7 |
| WHO_AM_I never reported as a mismatch | 8 |
| The sleep check on a stuck window removed | 9 |
| A pong answers with the wrong number | 10 and 18 |
| Watchdog refreshed for ever | 11 and 12 |
| Watchdog reset flag ignored | 12 |
| The retry never happens | 13 and 14 |
| NO_DATA never set | 15 |
| Line sent with a blocking 14 ms transmit | 16 |
| Watchdog started after the clock set-up | 17 |
| The identity check never repeats | 19 |

Three more mutants are checked by the host test `test_uart.c`, not by Renode, because the emulated UART cannot show
them: a pong written over a message in flight (S2), a data line skipped because a zero line is still on the wire
(the 1 in 128 phase, S1) and an overrun that does not restart receive (S4). Each makes `test_uart.c` fail.

## What the emulation cannot show

It proves the firmware logic: the real compiled code reads the right registers, builds the exact line, gets
the checksum right, handles the lost-sensor rule, answers pings and exercises the watchdog refresh rule.

Only a board can show:

- the PLL locking, the flash wait states and the real 96 MHz timing
- the I2C bus electrical behaviour, a stuck line and the bus recovery pulses (this I2C model has no wires)
- the real IWDG timeout (the LSI spread) and the debug freeze
- UART receive under noise and the overrun and framing recovery (the model has no errors to inject here)
- real execution time, stack use and the window work against the 10 ms tick
- that the silicon sets the reset flags
