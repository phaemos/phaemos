# Nano Node Sketch

The main Arduino sketch for the auxiliary sensor node.

| File | Purpose |
|---|---|
| nano_node.ino | Main loop: reads the sensors every cycle, sends one checksummed line over UART to the ESP32, answers a ping, reads the reset cause and runs the optional watchdog |
| sensors.h | Declarations for the sensor reads, the supply measurement and the status bits |
| sensors.cpp | BME280 and BMP280 driver with the fault checks (control registers read back, frozen data, range), LDR and moisture reads and the supply measurement |
| linkframe.h | The CRC-16/CCITT-FALSE and hex helpers, free of any Arduino header so the emulation can compile and test them on a host |
| platformio.ini | Build settings: both Nano bootloaders, an environment with the watchdog on and one with the band gap calibrated |

The Nano sends data at 9600 baud over UART (D0/D1) to the ESP32's UART1 (GPIO16/17).
The carrier board has two circuits for the link (a bare jumper-wire build needs the same two): a non-inverting BSS138
level shifter into the Nano's D0 with 100 R in series and 10 k to 5 V and a 10 k over 20 k divider out of D1 that gives
3.33 V at the hub for a high.
See `../../../hardware/wiring/nano_pinout.md` for full pin assignments.

The line format is:

```text
TEMP:25.1,HUM:50.7,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:0,SEQ:12,UP:26,VCC:4980*F6B1
```

The first six keys are as before and -1 means a reading is absent. A BMP280 sends `HUM:-1`. `ST` is a status
bit mask, `SEQ` counts lines since boot, `UP` is seconds since boot and `VCC` is the supply in millivolts. The
line ends in `*` and four hex digits of CRC-16/CCITT-FALSE over everything before the star, then CR LF. The status
bits, the ping, the reset cause, the watchdog flag and its bootloader warning are in `../README.md`.

On a checksummed line `ST` alone says whether the three sensor values are usable. A real -1.0 C prints as `TEMP:-1.0`
and is a reading. The `-1` form for a value that is not usable comes with a sensor bit set in `ST`.

The hub sends `PING:<n>` and a line feed. The node answers `PONG:<n>*CCCC` and CR LF, for example
`PONG:1234*EBBB`.

Build with `pio run` in this folder. `pio run -e nanoatmega328new_wdt` builds with `NANO_WATCHDOG` on for a board
with the new bootloader and `pio run -e nanoatmega328new_cal` builds with `BANDGAP_CALIBRATED` on, which tightens the
SUPPLY_RANGE limits from 4000 and 6000 mV to 4500 and 5500 mV once the band gap is calibrated. See `../README.md`.
