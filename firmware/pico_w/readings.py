# firmware/pico_w/readings.py
# pure helpers that turn raw sensor values into display text and the POST body.
#
# kept apart from main.py so they can be tested on a desktop Python, because
# main.py starts the hardware and loops forever as soon as it is imported.

import config

# shown on the OLED in place of a humidity value the sensor cannot provide
HUMIDITY_PLACEHOLDER = "--"


def convert_reading(t_raw, p_raw, h_raw):
    """Convert driver integers to (temp_c, humidity_pct, pressure_hpa).

    humidity_pct is None when h_raw is None (a BMP280).
    """
    temp_c       = t_raw / 100.0
    humidity_pct = None if h_raw is None else h_raw / 1024.0
    # divide by 25600 (256 * 100) to convert from 1/256 Pa to hPa directly.
    pressure_hpa = p_raw / 25600.0
    return temp_c, humidity_pct, pressure_hpa


def format_number(value, decimals=1, suffix=""):
    """Return a number as text (the placeholder when the sensor gave none)."""
    if value is None:
        return HUMIDITY_PLACEHOLDER
    return "{:.{}f}{}".format(value, decimals, suffix)


def format_humidity(humidity, decimals=1):
    """Return humidity as text with a percent sign (the placeholder when absent)."""
    return format_number(humidity, decimals, "%")


def display_lines(temp, humidity, pressure, light):
    """Return the three OLED text lines below the header.

    any value may be None, because a sensor that failed to read has no number.
    It shows as the placeholder."""
    return (
        "T:{}C H:{}".format(format_number(temp), format_humidity(humidity)),
        "P:{}hPa".format(format_number(pressure)),
        "L:{}".format(HUMIDITY_PLACEHOLDER if light is None else light),
    )


def log_line(status, temp, humidity, pressure, light):
    """Return the console line printed after a successful POST."""
    return "POST OK ({}) - T:{}C H:{} P:{}hPa L:{}".format(
        status, format_number(temp), format_humidity(humidity),
        format_number(pressure), HUMIDITY_PLACEHOLDER if light is None else light)


def build_payload(temp, humidity, pressure, light, device_id=None):
    """Build the JSON payload dict for the telemetry POST.

    a key is left out when its value is None because the API treats a missing
    field as not reported, whereas a made-up number would be stored."""
    payload = {
        "device_id": config.DEVICE_ID if device_id is None else device_id,
        "node_type": "pico_w",
    }
    if temp is not None:
        payload["temperature"] = round(temp, 2)
    if pressure is not None:
        payload["pressure"] = round(pressure, 2)
    if light is not None:
        payload["light_level"] = light
    if humidity is not None:
        payload["humidity"] = round(humidity, 2)
    return payload
