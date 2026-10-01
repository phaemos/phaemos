// ============================================================
// PHAEMOS - ESP32 Firmware
// Read DHT22, MPU6050 and LDR then POST JSON to the API
// ============================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "dht22.h"
#include "mpu6050.h"
// ota.ino is compiled alongside this file by the Arduino IDE - no #include needed.
// checkAndApplyOTA() is declared and defined in ota.ino.

void setup() {
  // use a higher baud rate to keep debug logging responsive while posting over Wi-Fi.
  Serial.begin(115200);

  // initialise each sensor subsystem once.
  initDHT();
  initMPU();

  // connect to Wi-Fi
  Serial.print("Connecting to Wi-Fi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi connected. IP: " + WiFi.localIP().toString());

  // check for a firmware update once on boot before starting the sensor loop.
  checkAndApplyOTA();
}

void loop() {
  // collect one frame of environment and vibration data.
  float temperature, humidity;
  float vx, vy, vz;

  // let the sensor helper functions fill these by reference.
  readDHT(temperature, humidity);
  readMPU(vx, vy, vz);

  // read the LDR on the analog pin.
  int rawLight  = analogRead(LDR_PIN);
  // keep this as a float to match the backend schema type.
  float lightLevel = (float)rawLight;

  // build the JSON payload.
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
    // create a short-lived HTTP client each cycle to keep state simple.
    HTTPClient http;
    http.begin(API_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", DEVICE_API_KEY);

    // POST the payload; the response code is 201 on success.
    int responseCode = http.POST(payload);
    Serial.print("POST response: ");
    Serial.println(responseCode);

    // always close the connection to release sockets and memory on the ESP32.
    http.end();
  } else {
    Serial.println("Wi-Fi disconnected - skipping POST");
  }

  // wait for the configured sensor polling interval.
  delay(POLL_INTERVAL_MS);
}
