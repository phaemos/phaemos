# Nano Node Sketch

The main Arduino sketch for the auxiliary sensor node.

| File | Purpose |
|---|---|
| nano_node.ino | Main loop - reads sensors every cycle and sends structured JSON over UART to ESP32 |
| sensors.h | Declarations for all sensor read functions |
| sensors.cpp | Sensor initialisation and read implementations |

The Nano sends data at 9600 baud over UART (D0/D1) to the ESP32's UART1 (GPIO16/17).
A 3.3V-5V logic level shifter is required between the Nano (5V logic) and ESP32 (3.3V logic).
See `../../../wiring/nano_pinout.md` for full pin assignments.
