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

// ─── v2.0 additions - do not remove existing definitions above ─────────────────
// These were added in the v2 hardware spec update (May 2026) when the platform
// expanded from one ESP32 + Arduino Uno to four nodes with 11+ sensors.

// Wi-Fi timeout
// I cap the connection wait at 10 s so the node doesn't hang indefinitely on boot.
#define WIFI_TIMEOUT_MS         10000

// API path (the base URL above is the host; this is the ingest endpoint path)
#define API_TELEMETRY           "/api/v1/telemetry"
// I use a separate API_KEY for the v2 multi-node setup; DEVICE_API_KEY remains for OTA.
#define API_KEY                 "esp32-key-placeholder"

// ─── I2C bus (named aliases - same GPIO as MPU6050_SDA/SCL above) ─────────────
// I2C_SDA/SCL are the canonical bus names used by the v2 sensor modules.
// They point to the same physical pins as MPU6050_SDA/SCL defined above.
#define I2C_SDA                 21
#define I2C_SCL                 22

// ─── I2C device addresses ─────────────────────────────────────────────────────
// Every I2C sensor on the bus needs a unique address. These are hardware defaults.
#define BME280_ADDR             0x76
#define MPU6050_ADDR            0x68
#define INA219_ADDR             0x40
#define MLX90614_ADDR           0x5A
#define VL53L0X_ADDR            0x29
#define AS5600_ADDR             0x36
#define OLED_ADDR               0x3C
#define OLED_WIDTH              128
#define OLED_HEIGHT             64

// ─── Analog sensor pins (v2 wiring) ───────────────────────────────────────────
// Note: LDR_PIN above is GPIO34 from v1. In v2 the LDR moved to GPIO33 to
// free GPIO34 for the MQ-2. Use LDR_V2_PIN in new firmware modules.
#define LDR_V2_PIN              33
#define MQ2_ANALOG_PIN          34
#define MQ2_DIGITAL_PIN         35
#define MAX4466_PIN             32
#define FC28_PIN                36

// ─── DS18B20 OneWire ──────────────────────────────────────────────────────────
// GPIO4 was DHT_PIN in v1; DS18B20 replaces DHT22 on the same pin in v2.
#define DS18B20_PIN             4
#define DS18B20_RESOLUTION      12

// ─── Output pin definitions ───────────────────────────────────────────────────
// I keep outputs on high-drive GPIOs that are not shared with the I2C/ADC bus.
#define BUZZER_PIN              25
#define RGB_LED_PIN             26
#define RGB_LED_COUNT           30
#define RELAY_CH1_PIN           13
#define RELAY_CH2_PIN           12
#define RELAY_CH3_PIN           14
#define RELAY_CH4_PIN           27
#define LED_RED_PIN             15
#define LED_GREEN_PIN           2
#define LED_AMBER_PIN           0

// ─── Serial ports for Nano and STM32 ─────────────────────────────────────────
// I use UART1 for the Nano and UART2 for the STM32 to avoid conflicts with
// the debug serial port (UART0) used by Serial.begin(115200).
#define NANO_RX_PIN             16
#define NANO_TX_PIN             17
#define NANO_BAUD               9600
#define STM32_RX_PIN            18
#define STM32_TX_PIN            19
#define STM32_BAUD              115200

// ─── v2 timing constants ──────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS   5000
#define OLED_UPDATE_MS          1000
#define SERIAL_POLL_MS          100

// ─── Alert thresholds ─────────────────────────────────────────────────────────
// I set conservative thresholds here; real-world calibration should tighten them.
#define TEMP_WARNING_C          40.0
#define TEMP_CRITICAL_C         60.0
#define HUMIDITY_WARNING_PCT    80.0
#define PRESSURE_LOW_HPA        950.0
#define CURRENT_WARNING_MA      1500.0
#define GAS_WARNING_LEVEL       400.0
#define WATER_THRESHOLD         500
#define DISTANCE_ALERT_MM       50
#define SOUND_WARNING_LEVEL     600
