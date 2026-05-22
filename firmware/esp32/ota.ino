// ============================================================
// PHAEMOS OTA - Over-The-Air firmware update check.
// I am called once from setup() after Wi-Fi connects.
// If the server has a newer firmware version, I download
// and flash it automatically, then reboot.
// ============================================================

#include <HTTPUpdate.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"

// I hardcode the version string into this build of the firmware.
// It must match the version uploaded to the backend for comparisons to work.
#define FIRMWARE_VERSION "1.0.0"

// I use this callback to log OTA flash progress to serial.
void _otaProgressCb(int cur, int total) {
  Serial.printf("OTA progress: %d / %d bytes\n", cur, total);
}

void checkAndApplyOTA() {
  Serial.println("[OTA] Checking for firmware update...");

  HTTPClient http;
  // I ask the backend what the latest available firmware version is.
  http.begin(String(API_BASE_URL) + "/api/v1/firmware/latest");
  http.addHeader("X-API-Key", DEVICE_API_KEY);

  int code = http.GET();
  if (code != 200) {
    Serial.printf("[OTA] /firmware/latest returned %d - skipping\n", code);
    http.end();
    return;
  }

  // I parse the JSON response to extract the version string.
  StaticJsonDocument<256> doc;
  deserializeJson(doc, http.getString());
  http.end();

  const char* serverVersion = doc["version"];
  if (!serverVersion) {
    Serial.println("[OTA] No version field in response - skipping");
    return;
  }

  // I compare version strings; if they match I am already current.
  if (String(serverVersion) == String(FIRMWARE_VERSION)) {
    Serial.println("[OTA] Firmware is up to date.");
    return;
  }

  Serial.printf("[OTA] New version available: %s (current: %s) - updating\n",
                serverVersion, FIRMWARE_VERSION);

  // I rely on HTTPUpdate to handle the download, CRC check, flash write and rollback
  // on failure - this is the recommended ESP32 OTA mechanism.
  httpUpdate.onProgress(_otaProgressCb);

  WiFiClient wifiClient;
  // I point the updater at the download endpoint.
  String downloadUrl = String(API_BASE_URL) + "/api/v1/firmware/download";

  // I pass the API key as a custom header so the server can authenticate the device.
  httpUpdate.setExtraHeaders(("X-API-Key: " + String(DEVICE_API_KEY)).c_str());

  t_httpUpdate_return ret = httpUpdate.update(wifiClient, downloadUrl);

  switch (ret) {
    case HTTP_UPDATE_FAILED:
      Serial.printf("[OTA] Update failed: %s\n", httpUpdate.getLastErrorString().c_str());
      break;
    case HTTP_UPDATE_NO_UPDATES:
      Serial.println("[OTA] Server said no update available.");
      break;
    case HTTP_UPDATE_OK:
      // The device reboots automatically after a successful flash - this line is never reached.
      Serial.println("[OTA] Update successful - rebooting");
      break;
  }
}
