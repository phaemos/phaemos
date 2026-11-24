// secrets.example.h - copy this file to secrets.h (same folder) and fill it in. secrets.h is never
// tracked: the repository's .gitignore has a line for it. then build with USE_COMPILED_SECRETS=1
// (-DUSE_COMPILED_SECRETS=1). the default is to provision a hub over its serial console instead,
// which compiles in no secret at all (see "Provisioning a hub" in README.md).
//
// a build that still has one of these placeholder values fails to compile and names it.
#pragma once

#define WIFI_SSID        "YourNetworkName"
#define WIFI_PASSWORD    "YourNetworkPassword"
// the telemetry endpoint. https:// unless the bench flag ALLOW_PLAIN_HTTP is set.
#define API_URL          "https://your-backend-url/api/v1/telemetry"
// generated when the device is created in the admin panel. sent in the X-API-Key header.
#define DEVICE_API_KEY   "your-device-api-key-from-admin-panel"
// the matching device record's id.
#define DEVICE_ID        "your-device-uuid"
// only the update code reads this and that code is off (OTA_ENABLED is 0).
#define API_BASE_URL     "https://your-backend-url"
