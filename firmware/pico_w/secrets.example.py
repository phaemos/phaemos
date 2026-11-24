# firmware/pico_w/secrets.example.py
# copy this file to secrets.py, replace every CHANGE_ME with the real value and
# copy secrets.py to the node. Never commit secrets.py. The node refuses to run
# while any value still says CHANGE_ME.

WIFI_SSID    = "CHANGE_ME"   # your Wi-Fi network name
WIFI_PASS    = "CHANGE_ME"   # your Wi-Fi password
API_BASE_URL = "https://CHANGE_ME"   # for example https://api.example.org
DEVICE_ID    = "CHANGE_ME"   # the device id registered on the dashboard
API_KEY      = "CHANGE_ME"   # the device key shown once on the dashboard

# bench use only. Uncomment to post over plain http:// (no encryption).
# ALLOW_PLAIN_HTTP = True
