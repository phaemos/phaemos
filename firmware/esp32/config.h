// ============================================================
// config.h - PHAEMOS ESP32 Configuration
// Copy this file and fill in your own values.
// DO NOT commit credentials to Git.
// ============================================================

// `#pragma once` is a non-standard but universally supported guard that prevents this header
// being included more than once per compilation unit — safer than manual #ifndef guards.
#pragma once

// Wi-Fi
#define WIFI_SSID        "YourNetworkName"
#define WIFI_PASSWORD    "YourNetworkPassword"

// API
// Base URL of the backend (no trailing slash) — used by OTA to build endpoint paths.
#define API_BASE_URL     "http://your-backend-url"
// Telemetry ingest endpoint exposed by the FastAPI backend.
#define API_URL          "http://your-backend-url/api/v1/telemetry"
// Generated when creating a device in the admin/API.
// Sent in the `X-API-Key` header so the backend can authenticate which device is posting data.
#define DEVICE_API_KEY   "your-device-api-key-from-admin-panel"
// UUID of the matching device record in the backend.
// Included in the JSON body so the backend knows which device row to associate the reading with.
#define DEVICE_ID        "your-device-uuid"

// Pins
#define DHT_PIN          4     // GPIO4
// GPIO34 is input-only and has no internal pull-up, making it ideal for ADC (analogue) reads.
#define LDR_PIN          34    // ADC1 channel (GPIO34)
#define MPU6050_SDA      21    // I2C SDA
#define MPU6050_SCL      22    // I2C SCL

// Timing
// Delay in milliseconds between sensor reads; 5000 ms = 5 s gives a balance between data density and battery/bandwidth.
#define POLL_INTERVAL_MS 5000  // 5 seconds between readings
