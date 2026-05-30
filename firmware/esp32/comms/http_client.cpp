// I include HTTPClient before the local headers so the ESP32 Arduino core
// types are fully resolved when the local declarations are parsed.
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>

#include "http_client.h"

int httpPost(const String& url, const String& payload, const char* apiKey) {
    // I check WiFi status up front and return -1 immediately rather than
    // letting HTTPClient throw an assertion or behave unpredictably on a
    // disconnected radio.
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println(F("httpPost: WiFi not connected"));
        return -1;
    }

    HTTPClient http;
    // I use http.begin(url) (single-argument form) because the backend uses
    // plain HTTP - if HTTPS is ever needed, the url itself will carry https://
    // and a second certificate-bundle argument will be added here.
    http.begin(url);

    // I set Content-Type to application/json so the FastAPI backend can parse
    // the body without a content-negotiation round-trip.
    http.addHeader(F("Content-Type"), F("application/json"));

    // I use X-API-Key rather than Authorization: Bearer because the backend
    // was designed around API key authentication for device-to-server traffic.
    http.addHeader(F("X-API-Key"), apiKey);

    int code = http.POST(payload);

    if (code < 0) {
        Serial.print(F("httpPost error: "));
        Serial.println(http.errorToString(code));
    }

    // I always call http.end() to release the underlying TCP connection back
    // to the connection pool - not calling it leaks sockets under load.
    http.end();

    return code;
}
