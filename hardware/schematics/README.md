# Schematics

The schematics for the four PHAEMOS nodes are drawn in KiCad, together with each board's layout. See [`../pcb/`](../pcb/) for the boards and their status.

> [!IMPORTANT]
> Every schematic is finished and passes the electrical rules check. We publish the KiCad files once the boards have been made and tested.

## Simulation

The circuits were simulated in LTspice before ordering: the power input, reverse protection, level shifters, drivers and sensor supplies of all four boards, with the real parts' figures where the makers publish them. The simulations found one real fault on the ESP32 board, which was fixed and checked again.

The Proteus project files in this folder (`.pdsprj`) are empty placeholders from an earlier plan. Our Proteus has no usable model of the ESP32 or the RP2350, so LTspice was used for every board.

For pin assignments and wiring details for each node, see [`../wiring/`](../wiring/).
