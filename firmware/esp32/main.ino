// ============================================================
// PulseWatch - ESP32 Firmware
// Reads DHT22, MPU6050 and LDR then POSTs JSON to the API
// ============================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "dht22.h"
#include "mpu6050.h"

void setup() {
  Serial.begin(115200);

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
  float temperature, humidity;
  float vx, vy, vz;

  readDHT(temperature, humidity);
  readMPU(vx, vy, vz);

  // Read LDR on analog pin
  int rawLight  = analogRead(LDR_PIN);
  float lightLevel = (float)rawLight;

  // Build JSON payload
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
    HTTPClient http;
    http.begin(API_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", DEVICE_API_KEY);

    int responseCode = http.POST(payload);
    Serial.print("POST response: ");
    Serial.println(responseCode);

    http.end();
  } else {
    Serial.println("Wi-Fi disconnected - skipping POST");
  }

  delay(POLL_INTERVAL_MS);
}
