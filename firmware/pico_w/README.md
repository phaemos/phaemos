# Raspberry Pi Pico 2W - Ambient Node

This node reads BME280 (temperature, humidity, pressure), an LDR (light),
displays readings on an SSD1306 OLED, and POSTs telemetry to the Phaemos API
over Wi-Fi every 5 seconds.

---

## Installing MicroPython on the Pico 2W

1. Download the Pico 2W MicroPython UF2 from:
   https://micropython.org/download/RPI_PICO2_W/

   > Use the **Pico 2W** build, not the original Pico W build - the RP2350
   > chip requires its own firmware image.

2. Hold the **BOOTSEL** button on the Pico 2W, then connect it to your
   computer via USB while holding the button.

3. The Pico appears as a USB mass storage device named **RPI-RP2**.

4. Drag the downloaded `.uf2` file onto the **RPI-RP2** drive.

5. The Pico automatically reboots into MicroPython.  The RPI-RP2 drive
   disappears - this is normal.

---

## Updating config.py

Before copying files, open `config.py` and fill in your real values:

```python
WIFI_SSID    = "MyActualNetworkName"
WIFI_PASS    = "MyActualPassword"
API_BASE_URL  = "http://192.168.1.50:8000"   # IP of your Phaemos server
DEVICE_ID     = "pico-ambient-01"             # Unique ID for this node
API_KEY       = "your-actual-api-key"
```

Do NOT commit real credentials to version control.

---

## Copying Files to the Pico

### Using Thonny (recommended for beginners)

1. Open Thonny IDE (https://thonny.org/).
2. Go to **Tools > Options > Interpreter**, select **MicroPython (Raspberry Pi Pico)**.
3. Connect the Pico via USB.
4. In the Files panel (View > Files), navigate to this folder on your PC.
5. Right-click each `.py` file and choose **Upload to /**.
6. Copy in this order: `config.py`, `bme280.py`, `ssd1306.py`,
   `wifi_connect.py`, `http_post.py`, `main.py`.

### Using rshell (command line)

```bash
pip install rshell
rshell --port /dev/ttyACM0   # adjust port for your OS

# Inside rshell:
cp firmware/pico_w/config.py       /pyboard/
cp firmware/pico_w/bme280.py       /pyboard/
cp firmware/pico_w/ssd1306.py      /pyboard/
cp firmware/pico_w/wifi_connect.py /pyboard/
cp firmware/pico_w/http_post.py    /pyboard/
cp firmware/pico_w/main.py         /pyboard/
```

### Using mpremote (official MicroPython tool)

```bash
pip install mpremote
mpremote cp firmware/pico_w/config.py       :config.py
mpremote cp firmware/pico_w/bme280.py       :bme280.py
mpremote cp firmware/pico_w/ssd1306.py      :ssd1306.py
mpremote cp firmware/pico_w/wifi_connect.py :wifi_connect.py
mpremote cp firmware/pico_w/http_post.py    :http_post.py
mpremote cp firmware/pico_w/main.py         :main.py
```

---

## Wiring

All devices share the I2C bus on GP4 (SDA) and GP5 (SCL).

### BME280 Temperature/Humidity/Pressure

| BME280 Pin | Pico 2W Pin | Notes                             |
|------------|-------------|-----------------------------------|
| VCC        | 3.3V (Pin 36) | 3.3V only - do NOT use VBUS (5V) |
| GND        | GND (Pin 38)  |                                 |
| SCL        | GP5 (Pin 7)   | I2C0 SCL                        |
| SDA        | GP4 (Pin 6)   | I2C0 SDA                        |
| SDO        | GND           | Sets I2C address to 0x76        |
| CSB        | 3.3V          | Selects I2C mode (not SPI)      |

### SSD1306 OLED Display

| SSD1306 Pin | Pico 2W Pin   | Notes                         |
|-------------|---------------|-------------------------------|
| VCC         | 3.3V (Pin 36) | Shares power rail with BME280 |
| GND         | GND (Pin 38)  |                               |
| SCL         | GP5 (Pin 7)   | Shared I2C bus with BME280    |
| SDA         | GP4 (Pin 6)   | Shared I2C bus with BME280    |

> BME280 (0x76) and SSD1306 (0x3C) have different I2C addresses so they
> coexist on the same bus without conflict.

### LDR Light Sensor

Wire the LDR as a voltage divider with a 10 kohm resistor:

```
3.3V ---[LDR]--- GP26 (ADC0, Pin 31) ---[10k]--- GND
```

Higher light = lower LDR resistance = higher voltage = higher ADC reading.

| Connection | Pico 2W Pin     |
|------------|-----------------|
| Top of LDR | 3.3V (Pin 36)   |
| Bottom of LDR / ADC | GP26 (Pin 31) |
| 10k to GND | GND (Pin 33)    |

---

## Verifying Output in Thonny

1. Open Thonny and connect to the Pico.
2. Click the **Shell** tab at the bottom.
3. Press **Ctrl+D** to soft-reset and run `main.py`.
4. You should see:

```
Wi-Fi connected. IP: 192.168.1.42
POST OK (201) - T:24.3C H:61.2% P:1012.8hPa L:34816
POST OK (201) - T:24.3C H:61.2% P:1012.8hPa L:35200
```

5. If you see `POST failed (status=-1)`, check that the Phaemos API server
   is running and `API_BASE_URL` in config.py is correct.

6. If you see `Wi-Fi failed`, verify SSID and password in config.py and
   that the Pico 2W is within range of the access point.
