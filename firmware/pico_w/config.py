# firmware/pico_w/config.py
# I keep all credentials and endpoints in one file so flashing a new Pico
# only requires updating this single file before copying to the filesystem

WIFI_SSID    = "YourNetworkName"
WIFI_PASS    = "YourPassword"

API_BASE_URL  = "http://192.168.X.X:8000"
API_TELEMETRY = "/api/v1/telemetry"
DEVICE_ID     = "pico-ambient-01"
API_KEY       = "pico-key-placeholder"

I2C_SDA       = 4
I2C_SCL       = 5
LDR_PIN       = 26

TELEMETRY_INTERVAL = 5
