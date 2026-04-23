// ============================================================
// PHAEMOS - ESP32 Firmware
// Reads DHT22, MPU6050 and LDR then POSTs JSON to the API
// ============================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "dht22.h"
#include "mpu6050.h"

void setup() {
  // Higher baud keeps debug logging responsive while posting over Wi-Fi.
  Serial.begin(115200);

  // Initialize each sensor subsystem once.
  initDHT();
  initMPU();

  // Connect to Wi-Fi
  Serial.print("Connecting to Wi-Fi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi connected. IP: " + WiFi.localIP().toString());
}

void loop() {
  // One frame of environment + vibration data.
  float temperature, humidity;
  float vx, vy, vz;

  // Sensor helper functions fill these by reference.
  readDHT(temperature, humidity);
  readMPU(vx, vy, vz);

  // Read LDR on analog pin
  int rawLight  = analogRead(LDR_PIN);
  // Keep as float to match backend schema type.
  float lightLevel = (float)rawLight;

  // Build JSON payload
  // 256 bytes is enough for this flat payload and avoids heap fragmentation.
  StaticJsonDocument<256> doc;
  doc["device_id"]   = DEVICE_ID;
  doc["temperature"] = temperature;
  doc["humidity"]    = humidity;
  doc["vibration_x"] = vx;
  doc["vibration_y"] = vy;
  doc["vibration_z"] = vz;
  doc["light_level"] = lightLevel;

  String payload;
  serializeJson(doc, payload);

  if (WiFi.status() == WL_CONNECTED) {
    // Create a short-lived HTTP client each cycle to keep state simple.
    HTTPClient http;
    http.begin(API_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", DEVICE_API_KEY);

    // POST returns HTTP status code (e.g., 201 on success).
    int responseCode = http.POST(payload);
    Serial.print("POST response: ");
    Serial.println(responseCode);

    // Always close connection to release sockets/memory on ESP32.
    http.end();
  } else {
    Serial.println("Wi-Fi disconnected - skipping POST");
  }

  // Sensor polling interval.
  delay(POLL_INTERVAL_MS);
}
