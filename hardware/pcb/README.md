# PCB Design Guide - Proteus ISIS and ARES

This guide covers the planned PCB design workflow for Phaemos using Proteus ISIS (schematic capture) and Proteus ARES (PCB layout). PCB work is scheduled for Phase 2 and Phase 3.

---

## Section 1: Phase 2 - Schematic Capture in Proteus ISIS

Follow these steps to create the schematic for the ESP32 Primary Node:

1. Open Proteus ISIS and create a new project. Set the schematic sheet size to A3.
2. Search the component library for "ESP32" or use a downloaded ESP32 DevKit V1 symbol (available from Proteus community libraries or Labcenter's online library).
3. Place the ESP32 DevKit V1 module in the centre of the sheet. Label all power and ground pins with power symbols (VCC, +3V3, GND).
4. Place each sensor breakout as a block component. If a specific breakout library part is not available, use a generic SIL connector with matching pin count and annotate with the sensor name and I2C address.
5. Wire the I2C bus: draw a single SDA wire and a single SCL wire connecting all I2C devices to GPIO21 and GPIO22 on the ESP32. Add net labels SDA and SCL rather than routing individual wires to keep the schematic readable.
6. Add pull-up resistors: place two 4.7k resistors between SDA and +3V3, and SCL and +3V3. Use the resistor symbol from the standard library.
7. Wire the power rails: draw +12V, +5V, and +3V3 net labels for the power distribution network. Place the LM2596 buck converter symbol and AMS1117 regulator symbol and wire them in the 12V -> 5V -> 3.3V chain.
8. Add decoupling capacitors: place a 100nF ceramic cap between VCC and GND for each IC, positioned close to the IC on the schematic. Add 10uF electrolytics at the LM2596 output and AMS1117 output.
9. Add flyback diodes: place a 1N5819 symbol across each relay coil terminal (cathode toward the positive supply). Label each diode with its purpose.
10. Add JST-PH 2-pin connectors for all external connections: power input, relay outputs, sensor cables. This makes the final PCB assembly clean and repeatable.
11. Run the Electrical Rules Check (ERC) from the Tools menu. Resolve all errors before proceeding. Unconnected pin warnings on unused ESP32 GPIOs can be suppressed with no-connect markers.

---

## Section 2: Phase 3 - PCB Layout in Proteus ARES

Once the schematic is complete and the ERC passes, transfer to layout:

1. From ISIS, go to Tools -> Netlist to ARES. This transfers the netlist and component footprints to the ARES PCB editor.
2. Set the board outline in ARES to fit your chosen IP65 enclosure. A Hammond 1554B (120mm x 65mm) or equivalent ABS enclosure works well. Set the board boundary on the Board Edge layer.
3. Place the ESP32 DevKit V1 module first, as it is the largest component and defines the orientation of the board. Position it so the USB port and boot/reset buttons are accessible when the board is mounted in the enclosure.
4. Route the power planes next: create a 5V pour on the inner layer (if using 4-layer) or route thick power traces (minimum 1mm for 1A, 2mm for 2A) on a 2-layer board. Pour a GND plane on the bottom copper layer covering the full board area.
5. Route the I2C bus (SDA and SCL) with matched trace lengths. Keep these traces away from the relay switching circuitry and the MQ-2 heater circuit. Target trace width of 0.3mm is fine for I2C at low speed.
6. Keep analog sensor signals (LDR, FC-28, MQ-2 AO, MAX4466) physically separated from digital switching traces (relay control, WS2812B data, PWM buzzer). Route analog signals on one side of the board and digital outputs on the other if possible.
7. Add the GND copper pour on the top layer (hatched or solid, with 0.5mm clearance to all traces). Stitch the top and bottom GND pours together with via stitching every 10-15mm.
8. Run the Design Rule Check (DRC) from the Tools menu. Resolve all clearance violations and unrouted connections before exporting.
9. Export Gerber files: File -> Export Gerbers. Export all required layers: F.Cu, B.Cu, F.SilkS, B.SilkS, F.Mask, B.Mask, Edge.Cuts, and the drill file. Zip the files for upload to the PCB manufacturer.

---

## Section 3: Ordering PCBs

**Recommended manufacturers:**

- **JLCPCB** (jlcpcb.com) - most cost-effective for prototype quantities. 5 boards of a standard 2-layer design typically costs 2-5 USD plus shipping. Economy shipping to the UK is 5-8 GBP and takes around 3-4 weeks. DHL shipping is 15-20 GBP and arrives in 5-7 business days.
- **PCBWay** (pcbway.com) - slightly higher base price but better customer support and more finish options. 5 boards costs approximately 5-10 USD plus shipping.

**Estimated cost for 5 boards (2-layer, ENIG finish, green solder mask):**
- Board cost: approximately 5-10 GBP
- Shipping (DHL to UK): approximately 8-12 GBP
- Total: approximately 13-22 GBP per order of 5 boards

**Typical turnaround:**
- Manufacturing: 2-3 business days
- Shipping to UK (DHL/FedEx): 4-7 business days
- Total from order to delivery: approximately 7-10 business days

Upload the zipped Gerber files to the manufacturer's online quote tool. Verify the board preview before placing the order. Check that the edge cuts layer correctly defines the board outline and that the drill file shows holes in the expected locations.
