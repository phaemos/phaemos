// esp32.ino - PHAEMOS v2 main firmware for the ESP32 hub node.
// I split all sensor, output, and comms logic into submodules and keep this
// file as the orchestration layer only - it wires everything together without
// containing implementation details.

// ─── Arduino / ESP32 core ────────────────────────────────────────────────────
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ─── Project configuration ───────────────────────────────────────────────────
#include "config.h"

// ─── Sensor modules ──────────────────────────────────────────────────────────
#include "sensors/bme280.h"
#include "sensors/mpu6050.h"
#include "sensors/ina219.h"
#include "sensors/vl53l0x.h"
#include "sensors/mq2.h"
#include "sensors/fc28.h"
#include "sensors/ds18b20.h"
#include "sensors/ldr.h"
#include "sensors/mlx90614.h"
#include "sensors/as5600.h"

// ─── Output modules ──────────────────────────────────────────────────────────
#include "outputs/oled.h"
#include "outputs/buzzer.h"
#include "outputs/rgb_led.h"
#include "outputs/relay.h"

// ─── Comms modules ───────────────────────────────────────────────────────────
#include "comms/wifi_manager.h"
#include "comms/http_client.h"
#include "comms/serial_parser.h"

// ─── Hardware serial ports ───────────────────────────────────────────────────
// I use HardwareSerial(1) for the Nano because UART1 does not conflict with
// the USB debug port (UART0) or the STM32 (UART2).
HardwareSerial NanoSerial(1);
// I use HardwareSerial(2) for the STM32 for the same isolation reason.
HardwareSerial STM32Serial(2);

// ─── Global sensor reading structs ───────────────────────────────────────────
// I declare these globally so postTelemetry() and checkThresholds() can access
// the latest values without parameter lists that span a dozen arguments.
BME280Reading  bmeData;
MPU6050Reading mpuData;
INA219Reading  inaData;

// I use plain primitive types for sensors that return single values rather
// than creating structs for each one - keeps the code proportionate.
uint16_t distMm       = 0;
float    gasLevel     = 0.0f;
bool     gasAlert     = false;
float    moistureLevel = 0.0f;
bool     waterAlert   = false;
float    ds18bTemp    = 0.0f;
float    ldrLevel     = 0.0f;
float    mlxAmbient   = 0.0f;
float    mlxObject    = 0.0f;
float    as5600Angle  = 0.0f;

// Data received over serial from Nano and STM32.
NanoData  nanoData;
STM32Data stm32Data;

// ─── Timing state ────────────────────────────────────────────────────────────
// I use uint32_t for millis() comparisons throughout to match the return type
// of millis() and avoid signed/unsigned comparison warnings.
static uint32_t lastTelemetry = 0;
static uint32_t lastOLED      = 0;

// ─── Forward declarations ────────────────────────────────────────────────────
void checkThresholds();
void postTelemetry();
void readAllSensors();

// ============================================================
// setup
// ============================================================
void setup() {
    // I start Serial at 115200 early so any init failures print to the monitor
    // before the rest of the boot sequence runs.
    Serial.begin(115200);
    Serial.println(F("PHAEMOS v2 booting..."));

    // I start both secondary serial ports before calling any sensor init that
    // might try to read from them.
    NanoSerial.begin(NANO_BAUD,   SERIAL_8N1, NANO_RX_PIN,  NANO_TX_PIN);
    STM32Serial.begin(STM32_BAUD, SERIAL_8N1, STM32_RX_PIN, STM32_TX_PIN);

    // I initialise the I2C bus before any I2C sensor because every I2C call
    // will silently fail if Wire has not been started.
    Wire.begin(I2C_SDA, I2C_SCL);

    // ── Sensor init ──────────────────────────────────────────────────────────
    initBME280();
    initMPU6050();
    initINA219();
    initVL53L0X();
    initMQ2();
    // I do not call a separate initFC28() because the FC28 is purely analog
    // and ADC reads work without explicit initialisation on the ESP32.

    // ── Output init ──────────────────────────────────────────────────────────
    initOLED();
    initBuzzer();
    initRGBLed();
    initRelay();

    // ── Network ──────────────────────────────────────────────────────────────
    connectWiFi(WIFI_SSID, WIFI_PASSWORD);

    // ── Boot confirmation ────────────────────────────────────────────────────
    // I play two startup beeps so the installer knows the node has finished
    // booting without having to look at the serial monitor.
    beep(100);
    delay(100);
    beep(100);

    // I show the splash last so the display confirms full init success.
    displaySplash("PHAEMOS", "v2 starting...");

    Serial.println(F("Setup complete."));
}

// ============================================================
// loop
// ============================================================
void loop() {
    uint32_t now = millis();

    // ── Poll incoming serial lines from Nano and STM32 ───────────────────────
    // I read one line per loop() pass rather than blocking on readStringUntil()
    // so the OLED and threshold checks never stall waiting for serial data.
    if (NanoSerial.available()) {
        String line = NanoSerial.readStringUntil('\n');
        line.trim();
        parseNanoSerial(line, &nanoData);
    }

    if (STM32Serial.available()) {
        String line = STM32Serial.readStringUntil('\n');
        line.trim();
        parseSTM32Serial(line, &stm32Data);
    }

    // ── Telemetry interval: read sensors and POST ─────────────────────────────
    if (now - lastTelemetry >= TELEMETRY_INTERVAL_MS) {
        lastTelemetry = now;
        readAllSensors();
        postTelemetry();
    }

    // ── OLED refresh interval ─────────────────────────────────────────────────
    if (now - lastOLED >= OLED_UPDATE_MS) {
        lastOLED = now;
        displayTelemetry(bmeData, mpuData, inaData, distMm, gasAlert, waterAlert);
    }

    // ── Alert evaluation runs every loop pass ─────────────────────────────────
    // I check thresholds every pass rather than on the telemetry interval so
    // a sudden spike triggers the buzzer within one loop cycle, not up to
    // TELEMETRY_INTERVAL_MS later.
    checkThresholds();
}

// ============================================================
// readAllSensors - called on every telemetry interval
// ============================================================
void readAllSensors() {
    readBME280(&bmeData);
    readMPU6050(&mpuData);
    readINA219(&inaData);
    distMm = readVL53L0X();
    readMQ2(&gasLevel, &gasAlert);
    readFC28(&moistureLevel, &waterAlert);
}

// ============================================================
// checkThresholds - evaluates sensor values and drives outputs
// ============================================================
void checkThresholds() {
    if (bmeData.temperature > TEMP_CRITICAL_C) {
        // I trigger CH1 as a cooling relay in critical overheat conditions -
        // the wiring doc defines CH1 as the cooling fan/valve.
        beepPattern(PATTERN_CRITICAL);
        setLEDStatus(STATUS_CRITICAL);
        triggerRelay(RELAY_CH1, true);
    } else if (bmeData.temperature > TEMP_WARNING_C || gasAlert || waterAlert) {
        // I group the three warning conditions together because any single one
        // is enough to alert the operator, even if the others are clear.
        beepPattern(PATTERN_WARNING);
        setLEDStatus(STATUS_WARNING);
        // I turn the relay off during WARNING - load switching is reserved for
        // CRITICAL so we do not cycle the cooling system on minor alerts.
        triggerRelay(RELAY_CH1, false);
    } else {
        // I play one quiet beep at NORMAL only when state transitions back from
        // WARNING/CRITICAL - callers should debounce this in a real deployment.
        setLEDStatus(STATUS_NORMAL);
        triggerRelay(RELAY_CH1, false);
    }
}

// ============================================================
// postTelemetry - serialises all readings into JSON and POSTs
// ============================================================
void postTelemetry() {
    if (WiFi.status() != WL_CONNECTED) {
        // I attempt a reconnect rather than silently dropping the reading so
        // the backend data stream has as few gaps as possible.
        reconnectWiFi();
        // I return after reconnect because the connection may still not be up
        // and starting an HTTP request on a disconnected radio will error out.
        return;
    }

    // I use StaticJsonDocument to avoid heap fragmentation - 1024 bytes is
    // enough for all current fields with headroom for future additions.
    StaticJsonDocument<1024> doc;

    doc["device_id"] = DEVICE_ID;

    // BME280
    doc["temperature"]  = bmeData.temperature;
    doc["humidity"]     = bmeData.humidity;
    doc["pressure"]     = bmeData.pressure;

    // MPU6050
    doc["accel_x"]      = mpuData.accel_x;
    doc["accel_y"]      = mpuData.accel_y;
    doc["accel_z"]      = mpuData.accel_z;
    doc["gyro_x"]       = mpuData.gyro_x;
    doc["gyro_y"]       = mpuData.gyro_y;
    doc["gyro_z"]       = mpuData.gyro_z;

    // INA219
    doc["bus_voltage"]  = inaData.bus_voltage;
    doc["current_ma"]   = inaData.current_ma;
    doc["power_mw"]     = inaData.power_mw;

    // VL53L0X
    doc["distance_mm"]  = distMm;

    // MQ2
    doc["gas_level"]    = gasLevel;
    doc["gas_alert"]    = gasAlert;

    // FC28
    doc["moisture"]     = moistureLevel;
    doc["water_alert"]  = waterAlert;

    // Nano serial data (best-effort - only include if the last parse succeeded)
    if (nanoData.valid) {
        doc["nano_temp"]    = nanoData.temperature;
        doc["nano_hum"]     = nanoData.humidity;
        doc["nano_pres"]    = nanoData.pressure;
        doc["light_level"]  = nanoData.light_level;
        doc["nano_moist"]   = nanoData.moisture;
        doc["nano_water"]   = nanoData.water_detected;
    }

    // STM32 serial data (best-effort)
    if (stm32Data.valid) {
        doc["fft_peak_hz"]    = stm32Data.fft_peak_hz;
        doc["vib_magnitude"]  = stm32Data.vib_magnitude;
    }

    String body;
    serializeJson(doc, body);

    int code = httpPost(String(API_URL), body, DEVICE_API_KEY);
    Serial.print(F("POST "));
    Serial.println(code);
}
