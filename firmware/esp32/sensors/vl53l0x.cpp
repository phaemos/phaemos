// include config.h first so VL53L0X_ADDR is available if the sensor ever
// needs to move from the Adafruit default.
#include "../config.h"
#include "vl53l0x.h"
#include <string.h>
#include <Wire.h>
#include <Adafruit_VL53L0X.h>

// declare the object static to keep its configuration state across calls.
static Adafruit_VL53L0X lox;

bool initVL53L0X() {
    if (!lox.begin()) {
        Serial.println("[VL53L0X] ERROR: sensor not found");
        return false;
    }
    // use long-range mode because Phaemos distance sensing applications
    // involve gaps wider than the default 1.2 m limit.
    lox.configSensor(Adafruit_VL53L0X::VL53L0X_SENSE_LONG_RANGE);
    Serial.println("[VL53L0X] init OK");
    return true;
}

Vl53Result readVL53L0X(uint16_t* mm) {
    VL53L0X_RangingMeasurementData_t measure;
    // zero the struct so an error return can never leave stale or uninitialised values.
    memset(&measure, 0, sizeof measure);
    VL53L0X_Error err = lox.rangingTest(&measure, false); // false = no debug output
    if (err != VL53L0X_ERROR_NONE) return VL53_ERROR;

    // range status 0 is valid. 5 is a hardware fail. the others (sigma, signal, minimum
    // range or phase) only mean there was no usable target.
    if (measure.RangeStatus == 5) return VL53_ERROR;
    if (measure.RangeStatus != 0) return VL53_NO_TARGET;

    *mm = measure.RangeMilliMeter;
    return measure.RangeMilliMeter > 0 ? VL53_OK : VL53_NO_TARGET;
}
