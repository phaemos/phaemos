# firmware/pico_w/main.py
# Raspberry Pi Pico 2W ambient node - main entry point.
#
# reads BME280 or BMP280 (temperature, pressure and for the BME280 humidity) and LDR (light level),
# displays readings on an SSD1306 OLED and POSTs telemetry to the Phaemos
# API every TELEMETRY_INTERVAL seconds. This file is only the hardware seam:
# everything that decides what to do lives in node.py so it can be tested.
#
# the node refuses to run while secrets.py is missing or holds a placeholder,
# also refuses HTTPS mode until root_ca.pem holds a real certificate.

import gc
import json
import os
import time

import config
import node


def _read_text(path):
    with open(path) as f:
        return f.read()


def _write_text(path, text):
    # write to a temporary file and rename, so a power cut leaves the old
    # value or the new one and never half of each
    temp = path + ".tmp"
    with open(temp, "w") as f:
        f.write(text)
    os.rename(temp, path)


def _halt(problems):
    # a configuration problem will not fix itself, so stop and say what is
    # wrong on the serial output instead of rebooting in a loop. The watchdog
    # is not running yet, so this does not reset.
    while True:
        print("PHAEMOS node will not start:")
        for problem in problems:
            print(" -", problem)
        time.sleep(10)


class Hardware:
    """The real hardware behind the seam node.Node expects."""

    EPOCH_2000_TO_1970 = 946684800  # MicroPython's rp2 port counts from 2000

    def __init__(self, tls_context):
        from machine import Pin, I2C, ADC, WDT
        self._Pin, self._I2C = Pin, I2C
        self.wdt = WDT(timeout=config.WDT_TIMEOUT_MS)
        self.i2c = I2C(0, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL), freq=400_000)
        # the sensor and the display are created on first use and again after
        # a failure, so a loose wire at boot or later does not end the node
        self._bme = None
        self._oled = None
        self.ldr = ADC(Pin(config.LDR_PIN))
        self.wlan = None
        self.tls_context = tls_context
        self.floor = config.CLOCK_FLOOR_UNIX
        self.url = node.base_address(config.API_BASE_URL) + config.API_TELEMETRY

    # time
    def ticks_ms(self):
        return time.ticks_ms()

    def ticks_diff(self, a, b):
        return time.ticks_diff(a, b)

    def feed(self):
        self.wdt.feed()

    def sleep_ms(self, ms):
        # sleep in short slices so the watchdog is fed throughout
        while ms > 0:
            chunk = 250 if ms > 250 else ms
            time.sleep_ms(chunk)
            self.feed()
            ms -= chunk

    def reset(self):
        import machine
        machine.reset()

    # sensors and display
    def read_bme(self):
        import bme280 as bme280_mod
        import readings
        try:
            if self._bme is None:
                self._bme = bme280_mod.BME280(self.i2c)
            t_raw, p_raw, h_raw = self._bme.read_compensated_data()
        except Exception:
            self._bme = None
            raise
        return readings.convert_reading(t_raw, p_raw, h_raw)

    def read_ldr(self):
        # the raw 16-bit ADC value is returned rather than a lux estimate
        # because lux needs the specific LDR's gamma and the divider resistor.
        return self.ldr.read_u16()

    def show(self, lines):
        try:
            if self._oled is None:
                import ssd1306
                self._oled = ssd1306.SSD1306_I2C(128, 64, self.i2c, addr=0x3C)
            self._oled.fill(0)
            self._oled.text("PHAEMOS", 0, 0)
            for y, line in zip((10, 20, 30, 40, 50), lines):
                self._oled.text(line, 0, y)
            self._oled.show()
        except Exception:
            self._oled = None
            raise

    # network
    def wifi_connected(self):
        return self.wlan is not None and self.wlan.isconnected()

    def wifi_connect(self):
        import wifi_connect
        try:
            self.wlan = wifi_connect.connect_wifi(
                config.WIFI_SSID, config.WIFI_PASS, config.WIFI_CONNECT_TIMEOUT_S, self.feed)
            return True
        except RuntimeError as e:
            print("Wi-Fi failed -", e)
            return False

    def _clock_unix(self):
        t = int(time.time())
        if time.gmtime(0)[0] == 2000:
            t += self.EPOCH_2000_TO_1970
        return t

    def sync_clock(self):
        # ntptime.settime() resolves the server name first. That lookup
        # has no time-out of its own. A lookup that outlasts the watchdog ends
        # in a reset, which is safe: the reset counter then slows the retries.
        import ntptime
        try:
            ntptime.timeout = config.NTP_TIMEOUT_S
        except Exception:
            pass
        for _ in range(config.NTP_ATTEMPTS):
            self.feed()
            try:
                ntptime.settime()
            except Exception as e:
                print("NTP failed:", e)
                continue
            if node.clock_plausible(self._clock_unix(), self.floor, config.CLOCK_CEILING_UNIX):
                return True
            print("NTP answered a time that is not plausible: ignored")
        return False

    def unix_time(self):
        t = self._clock_unix()
        if not node.clock_plausible(t, self.floor, config.CLOCK_CEILING_UNIX):
            return None
        return t

    def save_boot(self, boot):
        try:
            _write_text(config.BOOT_FILE, str(boot))
            return True
        except Exception:
            return False

    def clear_reset_marker(self):
        try:
            _write_text(config.RESET_COUNT_FILE, "0")
        except Exception:
            pass

    def reset_reason(self):
        import machine
        cause = machine.reset_cause()
        if cause == getattr(machine, "WDT_RESET", -1):
            return "watchdog"
        if cause == getattr(machine, "PWRON_RESET", -1):
            return "poweron"
        return "other"

    def heap_free(self):
        gc.collect()
        return gc.mem_free()

    def post(self, body):
        import http_post
        gc.collect()  # TLS needs a large block of heap
        return http_post.post_json(
            self.url, json.dumps(body), config.API_KEY, self.tls_context,
            config.SOCKET_TIMEOUT_S, self.feed, deadline_ms=config.POST_DEADLINE_MS)


def main():
    problems = node.startup_problems(config, _read_text)
    if problems:
        _halt(problems)

    tls_context = None
    if config.API_BASE_URL.startswith("https://"):
        import http_post
        tls_context = http_post.make_tls_context(node.pem_to_ders(_read_text(config.ROOT_CA_FILE)))

    boot, persisted = node.next_boot(
        lambda: _read_text(config.BOOT_FILE),
        lambda text: _write_text(config.BOOT_FILE, text))
    import machine
    was_watchdog = machine.reset_cause() == getattr(machine, "WDT_RESET", -1)
    reset_count = node.next_reset_count(
        lambda: _read_text(config.RESET_COUNT_FILE),
        lambda text: _write_text(config.RESET_COUNT_FILE, text),
        was_watchdog)

    hw = Hardware(tls_context)  # starts the watchdog: feed from here on
    runner = node.Node(hw, config, boot, persisted, reset_count)
    runner.announce()
    while True:
        try:
            runner.step()
        except Exception as e:
            # a bug in one pass must not end the node: log it and carry on;
            # a pass that hangs is ended by the watchdog instead.
            print("loop error:", type(e).__name__, e)
        # one second between passes rather than running flat-out, to reduce
        # power draw and I2C traffic. It is much shorter than the interval.
        hw.sleep_ms(1000)


main()
