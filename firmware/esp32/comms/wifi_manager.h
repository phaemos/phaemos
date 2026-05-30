// I use #pragma once for the same reason as every other header in this project.
#pragma once

// connectWiFi - joins the given SSID and blocks until connected or until
// WIFI_TIMEOUT_MS elapses. Prints IP on success, "WIFI FAILED" on timeout.
void connectWiFi(const char* ssid, const char* pass);

// reconnectWiFi - re-uses the credentials from the last connectWiFi call so
// the caller does not need to store them. Useful in loop() recovery paths.
void reconnectWiFi();
