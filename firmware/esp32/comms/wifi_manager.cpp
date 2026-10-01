// include Arduino.h before WiFi.h because some Arduino WiFi builds rely on
// the core macros defined in Arduino.h at parse time.
#include <Arduino.h>
#include <WiFi.h>

#include "../config.h"
#include "wifi_manager.h"

// store the last credentials in static variables so reconnectWiFi() can
// call connectWiFi() without the sketch having to manage credential strings.
// static storage lasts for the full firmware lifetime and is not stack-allocated.
static const char* s_ssid = nullptr;
static const char* s_pass = nullptr;

void connectWiFi(const char* ssid, const char* pass) {
    // save the credentials on every call so reconnectWiFi always has the
    // most recently used pair, even if the sketch rotates credentials.
    s_ssid = ssid;
    s_pass = pass;

    Serial.print(F("WiFi connecting to "));
    Serial.println(ssid);

    WiFi.begin(ssid, pass);

    uint32_t start = millis();
    // poll every 500 ms rather than a tight loop to give the TCP/IP stack
    // processing time and to avoid starving the watchdog timer.
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start >= WIFI_TIMEOUT_MS) {
            Serial.println(F("WIFI FAILED"));
            return;
        }
        delay(500);
        Serial.print(F("."));
    }

    Serial.println();
    Serial.print(F("WiFi connected - IP: "));
    Serial.println(WiFi.localIP());
}

void reconnectWiFi() {
    // guard against a null pointer here in case reconnectWiFi is somehow
    // called before connectWiFi has ever been called.
    if (s_ssid == nullptr || s_pass == nullptr) {
        Serial.println(F("reconnectWiFi: no credentials stored"));
        return;
    }
    // disconnect first to clear any stale association state on the ESP32
    // radio before attempting a fresh join.
    WiFi.disconnect(true);
    delay(100);
    connectWiFi(s_ssid, s_pass);
}
