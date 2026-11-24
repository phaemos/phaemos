# PHAEMOS ESP32 node (revised board): MCP23017 port table, final for the firmware

Second issue, 22 November 2026. Copied from the hardware machine after the schematic gate was re-run clean (ERC 0,
netlists match, pin audit of 24 signals with no problem). It replaces the first issue of the same day, in which
every rail input was a plain divider read active high. The hardware files are the source. If the two disagree, the
hardware wins. The layout is still interim and no board has been made.

## The chip

- U4, an MCP23017 on the I2C bus at address 0x20. A0, A1 and A2 (pins 15 to 17) are tied to ground.
- RESET (pin 18) is tied to +3V3, so the firmware cannot reset the chip by a pin.
- INTA (pin 20) is the net EXP_INT and reaches test pad TP33 only. INTB (pin 19) is not connected. No interrupt
  line reaches the module, so the driver must poll.
- Every pin is an input at reset with its pull-up off.
- GPA7 and GPB7 are output only (Microchip DS20001952D, Revision D: features list page 1, table 2-1 page 11,
  section 3.5.1 page 18). The firmware writes bit 7 of IODIRA and of IODIRB as 0.
- Input levels (the same sheet, table 1-1 page 4): VIL is 0.2 x VDD and VIH is 0.8 x VDD. Leakage is plus or
  minus 1 uA.
- Supply: an AMS1117-3.3, 3.235 to 3.365 V over its full range.

## How the rail inputs work

Six of the seven rail inputs go through an NPN transistor (BC337-40). The rail feeds the base through a resistor,
a 10 k resistor takes the base to ground, the collector is the expander pin and a 10 k resistor pulls the pin up to
+3V3. So the pin reads LOW when the rail is present and HIGH when it is absent. With the rail off these inputs read
high, which is "absent". The same holds at reset. The pin never sits above its supply.

"Present" means the rail is up. It does not mean the rail is in range. The node's voltage and current readings say
whether a rail is in range.

The thresholds and the low level are ESTIMATES (base-emitter 0.6 to 0.7 V, forced gain 100). No data sheet read so
far gives the transistor's figures at these currents. Bring-up measures each input's low level against 0.66 V and
each rail's switching points with a bench supply.

## Ports

| Port pin | Package pin | Net | Direction | Active | Input circuit | Reads low at | Reads high at | Undefined |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GPA0 | 21 | AUX_OK | in | low | R52 47 k 1 per cent, R53 10 k 1 per cent, Q12, pull-up R65 10 k | V5_AUX from 4.2 V | under 2.6 V | 2.6 to 4.2 V |
| GPA1 | 22 | FEED3_OK | in | low | R50 100 k 1 per cent, R51 10 k 1 per cent, Q11, pull-up R64 | feed from 8.1 V | under 5.0 V | 5.0 to 8.1 V |
| GPA2 | 23 | FEED2_OK | in | low | R48, R49, Q10, pull-up R63 | as FEED3 | as FEED3 | as FEED3 |
| GPA3 | 24 | FEED1_OK | in | low | R46, R47, Q9, pull-up R62 | as FEED3 | as FEED3 | as FEED3 |
| GPA4 | 25 | SPARE_A4, to J23 pin 6 | spare | none | none | | | |
| GPA5 | 26 | SPARE_A5, to J23 pin 5 | spare | none | none | | | |
| GPA6 | 27 | SPARE_A6, to J23 pin 4 | spare | none | none | | | |
| GPA7 | 28 | SPARE_A7, to J23 pin 3 | output only | none | none | | | |
| GPB0 | 1 | BUTTON | in | low | R58 10 k to 3V3, SW1 to ground, TP37 | pressed | released | |
| GPB1 | 2 | SENS_OK | in | HIGH | R56 1 k from V3_SENS, R57 100 k to ground, TP38 | under 0.65 V | from 2.72 V | between |
| GPB2 | 3 | STRIP_OK | in | low | R54 47 k 1 per cent, R55 10 k 1 per cent, D8 1N4148 clamp, Q13, pull-up R66, TP39 | as AUX | as AUX | as AUX |
| GPB3 | 4 | ENABLE_OK | in | low | R41 47 k 1 per cent, R42 10 k 1 per cent, Q14, pull-up R67, TP40 | as AUX | as AUX | as AUX |
| GPB4 | 5 | SPARE_B4, to J28 pin 1 | spare | none | none | | | |
| GPB5 | 6 | SPARE_B5, to J28 pin 2 | spare | none | none | | | |
| GPB6 | 7 | SPARE_B6, to J28 pin 3 | spare | none | none | | | |
| GPB7 | 8 | SPARE_B7, to J28 pin 4 | output only | none | none | | | |

For the transistor inputs, "reads low at" is the rail voltage from which the input reads low, which means the rail
is present. "Reads high at" is the rail voltage under which it reads high, which means absent. SENS_OK is the one
plain divider and is the other way round: high means present.

## Headers

- J23 has 6 pins: 3V3, GND, SPARE_A7, SPARE_A6, SPARE_A5, SPARE_A4.
- J28 has 5 pins: SPARE_B4, SPARE_B5, SPARE_B6, SPARE_B7, GND. It has no 3.3 V pin.

## Margins and what is still to come

- An off transistor's leakage of 10 uA at 125 C drops 0.10 V across the pull-up, against a VIH of 2.59 V at the
  supply's lowest.
- One change is still to come on the board and touches only the input circuits: a small signal diode from a
  transistor's base to ground on any input where a reversed or back-fed rail would put more than 4 V in reverse on
  the base. Polarity, thresholds and pins do not change.
