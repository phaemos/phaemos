# firmware/pico_w/main.py
# Raspberry Pi Pico 2W ambient node - main entry point.
#
# Reads BME280 (temperature, humidity, pressure) and LDR (light level),
# displays readings on an SSD1306 OLED, and POSTs telemetry to the Phaemos
# API over Wi-Fi every TELEMETRY_INTERVAL seconds.

import time
import json
from machine import Pin, I2C, ADC

import config
import wifi_connect
import bme280 as bme280_mod
import ssd1306
import http_post


# ---- Hardware setup --------------------------------------------------------

# I2C bus shared by BME280 and SSD1306.
# I use software-flexible I2C rather than hardware I2C0/I2C1 here because
# config.py specifies the pin numbers and MicroPython's machine.I2C can use
# any GPIO pair when freq is set explicitly.
i2c = I2C(0, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL), freq=400_000)

# I initialise BME280 first so any sensor fault is visible on the REPL before
# the display is ready, making wiring errors easier to diagnose.
sensor = bme280_mod.BME280(i2c)

# SSD1306 128x64 OLED on the same I2C bus as BME280.
# I2C address 0x3C is the default for most common SSD1306 breakout boards.
oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)

# LDR connected to GP26 (ADC0).  I use ADC directly rather than gpio.Pin
# because the ADC class handles the pin mode configuration automatically.
ldr_adc = ADC(Pin(config.LDR_PIN))

# ---- Wi-Fi connection -------------------------------------------------------

# I connect at startup rather than lazily because the OLED shows "PHAEMOS"
# immediately and users expect the node to be online before the first reading.
try:
    wifi_connect.connect_wifi(config.WIFI_SSID, config.WIFI_PASS)
except RuntimeError as e:
    # I print the error and continue rather than halting so sensor data still
    # appears on the OLED and UART even when the network is unavailable.
    print("WARNING: Wi-Fi failed -", e)


# ---- Helpers ----------------------------------------------------------------

def read_sensor():
    """Read BME280 and return (temp_c, humidity_pct, pressure_hpa)."""
    t_raw, p_raw, h_raw = sensor.read_compensated_data()
    temp_c       = t_raw / 100.0
    humidity_pct = h_raw / 1024.0
    # I divide by 25600 (256 * 100) to convert from 1/256 Pa to hPa directly.
    pressure_hpa = p_raw / 25600.0
    return temp_c, humidity_pct, pressure_hpa


def read_light():
    """Read LDR ADC and return a 0-65535 integer (16-bit Pico ADC).

    I return the raw 16-bit ADC value rather than a lux estimate because
    lux conversion requires knowing the specific LDR's gamma coefficient and
    the voltage divider resistor, which varies by hardware build.  The
    upstream API stores raw ADC for calibration flexibility.
    """
    return ldr_adc.read_u16()


def update_oled(temp, humidity, pressure, light):
    """Refresh the OLED with the latest sensor readings.

    OLED layout (each line is 8px tall; 8 lines fit on 64px display):
      Line 0 (y=0):  "PHAEMOS"            - node identifier / header
      Line 1 (y=10): "T:xx.xC H:xx.x%"   - temperature and humidity
      Line 2 (y=20): "P:xxxxhPa"          - pressure
      Line 3 (y=30): "L:xxxxx"            - raw light ADC value

    I leave lines 4-7 blank for future use (e.g. Wi-Fi status, post result).
    """
    oled.fill(0)
    oled.text("PHAEMOS", 0, 0)
    oled.text("T:{:.1f}C H:{:.1f}%".format(temp, humidity), 0, 10)
    oled.text("P:{:.1f}hPa".format(pressure), 0, 20)
    oled.text("L:{}".format(light), 0, 30)
    oled.show()


def build_payload(temp, humidity, pressure, light):
    """Build the JSON payload dict for the telemetry POST."""
    return {
        "device_id":   config.DEVICE_ID,
        "node_type":   "pico_w",
        "temperature": round(temp, 2),
        "humidity":    round(humidity, 2),
        "pressure":    round(pressure, 2),
        "light_level": light,
    }


# ---- Main loop -------------------------------------------------------------

# I use ticks_ms / ticks_diff for timing rather than subtracting absolute
# millis values because the Pico's 32-bit millisecond timer overflows back to
# 0 after ~49 days.  Simple subtraction (now - last) produces a large positive
# number at the overflow boundary, causing a ~49-day skip.  ticks_diff()
# handles the wrap correctly by using signed 32-bit arithmetic modulo the
# timer period, so the interval fires correctly even across a rollover.
last_post_ticks = time.ticks_ms()

while True:
    # Read sensors
    temp, humidity, pressure = read_sensor()
    light = read_light()

    # Update OLED every iteration (fast - no Wi-Fi involved)
    update_oled(temp, humidity, pressure, light)

    # POST telemetry every TELEMETRY_INTERVAL seconds
    now = time.ticks_ms()
    # I use ticks_diff(now, last_post_ticks) and compare to interval_ms rather
    # than comparing ticks directly because ticks_diff() performs the correct
    # modular subtraction described above.
    interval_ms = config.TELEMETRY_INTERVAL * 1000
    if time.ticks_diff(now, last_post_ticks) >= interval_ms:
        last_post_ticks = now

        payload = build_payload(temp, humidity, pressure, light)
        url = config.API_BASE_URL + config.API_TELEMETRY
        status = http_post.post_telemetry(url, payload, config.API_KEY)

        if status == 200 or status == 201:
            print("POST OK ({}) - T:{:.1f}C H:{:.1f}% P:{:.1f}hPa L:{}".format(
                status, temp, humidity, pressure, light))
        else:
            print("POST failed (status={}) - will retry next interval".format(status))

    # I sleep 1 second between OLED refreshes rather than running flat-out to
    # reduce RP2040 power draw and I2C bus activity.  The 1s sleep is much
    # shorter than TELEMETRY_INTERVAL so it does not significantly delay posts.
    time.sleep(1)
