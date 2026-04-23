// ============================================================
// config.h - PHAEMOS ESP32 Configuration
// Copy this file and fill in your own values.
// DO NOT commit credentials to Git.
// ============================================================

#pragma once

// Wi-Fi
#define WIFI_SSID        "YourNetworkName"
#define WIFI_PASSWORD    "YourNetworkPassword"

// API
// Telemetry ingest endpoint exposed by the FastAPI backend.
#define API_URL          "http://your-backend-url/api/v1/telemetry"
// Generated when creating a device in the admin/API.
#define DEVICE_API_KEY   "your-device-api-key-from-admin-panel"
// UUID of the matching device record in the backend.
#define DEVICE_ID        "your-device-uuid"

// Pins
#define DHT_PIN          4     // GPIO4
#define LDR_PIN          34    // ADC1 channel (GPIO34)
#define MPU6050_SDA      21    // I2C SDA
#define MPU6050_SCL      22    // I2C SCL

// Timing
#define POLL_INTERVAL_MS 5000  // 5 seconds between readings
