// ============================================================
// PHAEMOS OTA - Over-The-Air firmware update check.
// called once from the post task (comms/post_task.cpp) after Wi-Fi connects.
// if the server has a newer firmware version, download it
// and flash it automatically, then reboot.
// ============================================================

// the check is compiled only when OTA_ENABLED is 1 in config.h. the update comes
// over plain HTTP and is not signed, so it is off by default.
#include <WiFi.h>
#include <HTTPUpdate.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include "config.h"

#if OTA_ENABLED

// FIRMWARE_VERSION comes from config.h so the version lives in one place.
// it must be a dotted number such as 1.2.3 for the comparison below to work.

// parse the leading dotted number into up to four parts.
static void parseVersion(const char* text, uint32_t out[4]) {
  for (int i = 0; i < 4; i++) out[i] = 0;
  int part = 0;
  for (const char* c = text; *c && part < 4; c++) {
    if (*c >= '0' && *c <= '9') out[part] = out[part] * 10 + (*c - '0');
    else if (*c == '.') part++;
    else break;
  }
}

// true only when the server version is strictly newer. a mere difference is
// not enough because an older server build would otherwise downgrade the node.
static bool isNewerVersion(const char* server, const char* current) {
  uint32_t a[4], b[4];
  parseVersion(server, a);
  parseVersion(current, b);
  for (int i = 0; i < 4; i++) {
    if (a[i] != b[i]) return a[i] > b[i];
  }
  return false;
}

// use this callback to log OTA flash progress to serial.
void _otaProgressCb(int cur, int total) {
  Serial.printf("OTA progress: %d / %d bytes\n", cur, total);
}

// a firmware download can run for far longer than the watchdog timeout, so a task that is on
// the watchdog is taken off it for the whole check and put back on every way out. the check
// runs in the post task, which is not on the task watchdog (the main loop supervises it and
// the post task suspends that supervision for the download), so this does nothing there. it
// stays for any caller that is watched.
struct OtaWatchdogPause {
  bool paused;
  OtaWatchdogPause() : paused(esp_task_wdt_status(NULL) == ESP_OK) {
    if (paused) esp_task_wdt_delete(NULL);
  }
  ~OtaWatchdogPause() {
    if (paused) esp_task_wdt_add(NULL);
  }
};

void checkAndApplyOTA() {
  OtaWatchdogPause watchdogPause;
  Serial.println("[OTA] Checking for firmware update...");

  HTTPClient http;
  // ask the backend what the latest available firmware version is.
  http.begin(String(API_BASE_URL) + "/api/v1/firmware/latest");
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_RESPONSE_TIMEOUT_MS);
  http.addHeader("X-API-Key", DEVICE_API_KEY);

  int code = http.GET();
  if (code != 200) {
    Serial.printf("[OTA] /firmware/latest returned %d - skipping\n", code);
    http.end();
    return;
  }

  // parse the JSON response to extract the version string.
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, http.getString());
  http.end();
  if (err) {
    Serial.println("[OTA] Could not read the version response - skipping");
    return;
  }

  const char* serverVersion = doc["version"];
  if (!serverVersion) {
    Serial.println("[OTA] No version field in response - skipping");
    return;
  }

  // update only when the server version is strictly newer.
  if (!isNewerVersion(serverVersion, FIRMWARE_VERSION)) {
    Serial.printf("[OTA] Firmware is up to date (server %s, current %s).\n",
                  serverVersion, FIRMWARE_VERSION);
    return;
  }

  Serial.printf("[OTA] New version available: %s (current: %s) - updating\n",
                serverVersion, FIRMWARE_VERSION);

  // rely on HTTPUpdate to handle the download, CRC check, flash write and rollback
  // on failure - this is the recommended ESP32 OTA mechanism.
  httpUpdate.onProgress(_otaProgressCb);

  WiFiClient wifiClient;
  // point the updater at the download endpoint.
  String downloadUrl = String(API_BASE_URL) + "/api/v1/firmware/download";

  // pass the API key as a custom header so the server can authenticate the device.
  // the request callback is used because this core version has no setExtraHeaders().
  t_httpUpdate_return ret = httpUpdate.update(wifiClient, downloadUrl, "",
      [](HTTPClient* client) { client->addHeader("X-API-Key", DEVICE_API_KEY); });

  switch (ret) {
    case HTTP_UPDATE_FAILED:
      Serial.printf("[OTA] Update failed: %s\n", httpUpdate.getLastErrorString().c_str());
      break;
    case HTTP_UPDATE_NO_UPDATES:
      Serial.println("[OTA] Server said no update available.");
      break;
    case HTTP_UPDATE_OK:
      // the device reboots automatically after a successful flash - this line is never reached.
      Serial.println("[OTA] Update successful - rebooting");
      break;
  }
}

#endif  // OTA_ENABLED
