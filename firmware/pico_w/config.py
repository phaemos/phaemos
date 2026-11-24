# firmware/pico_w/config.py
# defaults and placeholders only. Real values live in secrets.py on the node
# (copy secrets.example.py and fill it in), which is kept out of version control;
# the node refuses to start while any required value is still a placeholder.

try:
    import secrets as _secrets
except ImportError:
    _secrets = None

# a value that begins with this text is a placeholder and not a real setting
PLACEHOLDER = "CHANGE_ME"


def _setting(name, default):
    # read from secrets.py when it exists and defines the name. CPython also has
    # a standard-library module called secrets, which defines none of these
    # names, so falling back to the default keeps a desktop test run safe.
    if _secrets is None:
        return default
    return getattr(_secrets, name, default)


# ---- values that must come from secrets.py -------------------------------

WIFI_SSID     = _setting("WIFI_SSID", PLACEHOLDER)
WIFI_PASS     = _setting("WIFI_PASS", PLACEHOLDER)
# https:// address of the API, for example https://api.example.org
API_BASE_URL  = _setting("API_BASE_URL", "https://" + PLACEHOLDER)
DEVICE_ID     = _setting("DEVICE_ID", PLACEHOLDER)
API_KEY       = _setting("API_KEY", PLACEHOLDER)

# bench use only: lets the node post over plain http://, which sends the key and
# every reading across the network unencrypted. The node says so on its serial
# output. Leave it False on any node that leaves the bench.
ALLOW_PLAIN_HTTP = _setting("ALLOW_PLAIN_HTTP", False)

# ---- settings that are not secret ----------------------------------------

API_TELEMETRY = "/api/v1/telemetry"

# file holding the root certificate the API's certificate chain ends at
ROOT_CA_FILE  = "root_ca.pem"
# file holding the boot counter
BOOT_FILE     = "boot_count.txt"

I2C_SDA       = 4
I2C_SCL       = 5
# ADC pin for the LDR divider.  use 26 (GP26) on a Raspberry Pi Pico 2 W
# and 40 (GPIO40) on a Waveshare RP2350B-Plus-W.
LDR_PIN       = 26

# seconds between posts when all is well
TELEMETRY_INTERVAL = 5

# ---- time limits ---------------------------------------------------------
# the RP2040 watchdog counts at most about 8.3 s (8388 ms in MicroPython), so
# 8000 ms is the largest round figure that is valid. No single blocking call
# may take longer than that without the watchdog being fed in between.
WDT_TIMEOUT_MS = 8000
# one socket operation (connect, handshake step, send or read) gives up after
# this many seconds. Feeding happens between operations, so the worst gap is
# one operation plus the work around it.
SOCKET_TIMEOUT_S = 2
# a Wi-Fi join is polled every half second with a feed each time, so it can
# take longer than the watchdog period as a whole
WIFI_CONNECT_TIMEOUT_S = 20
# attempts at setting the clock by NTP before the first HTTPS post, with the
# time each one may wait for the server
NTP_ATTEMPTS = 3
NTP_TIMEOUT_S = 2

# ---- back-off ------------------------------------------------------------
# after a failed post the wait doubles from TELEMETRY_INTERVAL up to this cap
BACKOFF_CAP_S = 300
# a 401 or 403 means the key is wrong and will not fix itself, so wait far longer
AUTH_BACKOFF_START_S = 300
AUTH_BACKOFF_CAP_S = 3600
# the longest Retry-After the node will obey
RETRY_AFTER_MAX_S = 3600

# ---- clock ---------------------------------------------------------------
# a time from NTP below this (Unix seconds) is refused as wrong. It is the
# build date of this firmware, 1 November 2026. MicroPython has no build date,
# so keep it current: set it to a date on or just before the day you flash.
CLOCK_FLOOR_UNIX = 1793491200
# and a time above this (1 January 2100) is refused too
CLOCK_CEILING_UNIX = 4102444800
# the clock is set again this often
RESYNC_INTERVAL_S = 86400
# this many posts in a row that never completed make the node forget the clock
CLOCK_FAIL_LIMIT = 3

# ---- limits on the reply -------------------------------------------------
# total time allowed to read the reply, measured in ticks, fed throughout
POST_DEADLINE_MS = 12000

# the file holding the count of watchdog resets in a row
RESET_COUNT_FILE = "reset_count.txt"
