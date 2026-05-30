// I use #pragma once for the same reason as every other header in this project.
#pragma once

// I include WString.h (pulled in by Arduino.h) here indirectly through String
// so callers can use Arduino String without a separate include.
#include <Arduino.h>

// httpPost - sends a JSON payload to the given URL with an X-API-Key header.
// Returns the HTTP response code (200, 201, etc.) on success,
// or -1 if WiFi is not connected at call time.
// Always calls http.end() internally to free the connection handle.
int httpPost(const String& url, const String& payload, const char* apiKey);
