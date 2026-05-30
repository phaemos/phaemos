// I include config.h first so DS18B20_PIN and DS18B20_RESOLUTION are
// available before OneWire or DallasTemperature headers are parsed.
#include "../config.h"
#include "ds18b20.h"
#include <OneWire.h>
#include <DallasTemperature.h>

// I build OneWire on the pin from config.h so the wiring can change in one place.
static OneWire           oneWire(DS18B20_PIN);
static DallasTemperature sensors(&oneWire);

void initDS18B20() {
    sensors.begin();

    // I set resolution here rather than leaving it at the library default (9-bit)
    // because 12-bit resolution gives 0.0625 degC steps which is adequate for
    // Phaemos thermal monitoring without excessive conversion time (~750 ms).
    sensors.setResolution(DS18B20_RESOLUTION);

    // I use non-blocking mode (waitForConversion = false) so the main loop
    // does not stall for 750 ms waiting for a 12-bit conversion to finish.
    sensors.setWaitForConversion(false);

    // Kick off the first conversion so the next readDS18B20() call has data.
    sensors.requestTemperatures();

    Serial.println("[DS18B20] init OK");
}

float readDS18B20() {
    // I request a fresh conversion before reading so the value is never
    // older than one telemetry interval.
    sensors.requestTemperatures();

    // getTempCByIndex(0) returns DEVICE_DISCONNECTED_C (-127) on error,
    // which matches the documented return value for this function.
    float t = sensors.getTempCByIndex(0);
    if (t == DEVICE_DISCONNECTED_C) {
        Serial.println("[DS18B20] ERROR: read failed");
        return -127.0F;
    }
    return t;
}
