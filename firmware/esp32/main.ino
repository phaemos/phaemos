// ============================================================
// PHAEMOS - ESP32 Firmware
// I read DHT22, MPU6050 and LDR then POST JSON to the API
// ============================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "dht22.h"
#include "mpu6050.h"
// ota.ino is compiled alongside this file by the Arduino IDE — no #include needed.
// checkAndApplyOTA() is declared and defined in ota.ino.

void setup() {
  // I use a higher baud rate to keep debug logging responsive while posting over Wi-Fi.
  Serial.begin(115200);

  // I initialise each sensor subsystem once.
  initDHT();
  initMPU();

  // I connect to Wi-Fi
  Serial.print("Connecting to Wi-Fi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi connected. IP: " + WiFi.localIP().toString());

  // I check for a firmware update once on boot before starting the sensor loop.
  checkAndApplyOTA();
}

void loop() {
  // I collect one frame of environment and vibration data.
  float temperature, humidity;
  float vx, vy, vz;

  // I let the sensor helper functions fill these by reference.
  readDHT(temperature, humidity);
  readMPU(vx, vy, vz);

  // I read the LDR on the analog pin.
  int rawLight  = analogRead(LDR_PIN);
  // I keep this as a float to match the backend schema type.
  float lightLevel = (float)rawLight;

  // I build the JSON payload.
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
    // I create a short-lived HTTP client each cycle to keep state simple.
    HTTPClient http;
    http.begin(API_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", DEVICE_API_KEY);

    // I POST the payload; the response code is 201 on success.
    int responseCode = http.POST(payload);
    Serial.print("POST response: ");
    Serial.println(responseCode);

    // I always close the connection to release sockets and memory on the ESP32.
    http.end();
  } else {
    Serial.println("Wi-Fi disconnected - skipping POST");
  }

  // I wait for the configured sensor polling interval.
  delay(POLL_INTERVAL_MS);
}
