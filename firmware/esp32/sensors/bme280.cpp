// I include config.h first so every macro (BME280_ADDR, I2C_SDA, etc.) is
// visible before any library header tries to use them.
#include "../config.h"
#include "bme280.h"
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>

// I keep the sensor object at file scope because it must persist between
// calls to initBME280() and readBME280().
static Adafruit_BME280 bme;

void initBME280() {
    // I try the address from config.h first, then fall back to 0x77 because
    // some BME280 breakout boards ship with the alternate address soldered.
    bool ok = bme.begin(BME280_ADDR);
    if (!ok) {
        ok = bme.begin(0x77);
    }

    if (!ok) {
        // I print to Serial here rather than halting execution so the rest of
        // the system can still run and report errors over telemetry.
        Serial.println("[BME280] ERROR: sensor not found at 0x76 or 0x77");
    } else {
        Serial.println("[BME280] init OK");
    }
}

void readBME280(BME280Reading* r) {
    // I pass the pointer fields directly to the Adafruit methods to avoid
    // an extra copy of the float values on the stack.
    r->temperature = bme.readTemperature();
    r->humidity    = bme.readHumidity();
    r->pressure    = bme.readPressure() / 100.0F; // Pa to hPa
}
