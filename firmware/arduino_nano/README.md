# Arduino Nano Secondary Node

This node reads a BME280 (temperature, humidity, pressure), an LDR (light),
and an FC-28 moisture sensor, then emits one CSV line every 2 seconds over
Serial at 9600 baud.

Example output:
```
TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0
```

---

## Wiring

### BME280 (I2C)

| BME280 Pin | Nano Pin | Notes                              |
|------------|----------|------------------------------------|
| VCC        | 3.3V     | BME280 is 3.3V; do NOT use 5V      |
| GND        | GND      |                                    |
| SCL        | A5       | I2C clock - shared bus             |
| SDA        | A4       | I2C data - shared bus              |
| SDO        | GND      | Sets I2C address to 0x76 (default) |
| CSB        | 3.3V     | Selects I2C mode (not SPI)         |

> The firmware tries 0x76 first and falls back to 0x77 automatically.
> SDO tied HIGH sets address 0x77.

### LDR (Light Sensor) - A0

Wire the LDR as a voltage divider between 5V and GND with a 10 kohm resistor:

```
5V ---[LDR]--- A0 ---[10k]--- GND
```

Higher light = lower resistance = higher voltage = higher ADC reading (0-1023).

### FC-28 Moisture Sensor - A1

| FC-28 Pin | Nano Pin | Notes                                 |
|-----------|----------|---------------------------------------|
| VCC       | 5V       | Use the Nano's 5V pin                 |
| GND       | GND      |                                       |
| AO        | A1       | Analog output - used by this firmware |
| DO        | Not used | Digital output - threshold not used   |

Lower ADC value = wetter soil. Values below 500 trigger `WATER:1` in output.

---

## Connecting to ESP32

The Nano outputs at 5V logic. The ESP32 UART RX is 3.3V tolerant - a level
shifter is required to avoid damaging the ESP32.

### Simple resistor divider level shifter (TX only)

```
Nano TX (5V) ---[10k]--- ESP32 RX ---[20k]--- GND
```

This creates a 3.33V level from 5V, within ESP32's 3.3V input tolerance.

### Wiring

| Nano Pin | ESP32 Pin | Notes                                       |
|----------|-----------|---------------------------------------------|
| TX (D1)  | Any RX    | Through level shifter as above              |
| GND      | GND       | Common ground is required                   |
| RX (D0)  | Any TX    | Only needed if ESP32 sends commands to Nano |

> The Nano's serial TX (D1) is also used by the USB-to-serial chip for
> programming. Disconnect the ESP32 RX wire when flashing the Nano via USB.

---

## Arduino IDE Setup

### Board Selection

- Board: **Arduino Nano**
- Processor: **ATmega328P** (or ATmega328P (Old Bootloader) for older clones)
- Port: Select the correct COM port / /dev/ttyUSBx

### Library Installation

Install via the Arduino Library Manager (Sketch > Include Library > Manage Libraries):

| Library               | Version  | Notes                           |
|-----------------------|----------|---------------------------------|
| Adafruit BME280       | >= 2.2.2 | Requires Adafruit Unified Sensor |
| Adafruit Unified Sensor | >= 1.1.9 | Dependency of BME280 lib       |

### Flashing

1. Open `nano_node/nano_node.ino` in Arduino IDE.
2. Select the correct board and port.
3. Click **Upload** (Ctrl+U).
4. Open **Serial Monitor** at 9600 baud to verify output.

---

## Troubleshooting

| Symptom                        | Cause                              | Fix                                |
|--------------------------------|------------------------------------|------------------------------------|
| `TEMP:-1,HUM:-1,PRES:-1`       | BME280 not found on I2C bus        | Check wiring, try swapping SDO to 3.3V (address 0x77) |
| `LIGHT:0` always               | LDR wiring error                   | Check voltage divider polarity     |
| `MOIST:0` always               | FC-28 VCC not connected            | Connect FC-28 VCC to Nano 5V pin   |
| No output on Serial Monitor    | Wrong baud rate or board reset     | Set monitor to 9600 baud           |
