// I include config.h first so VL53L0X_ADDR is available if we ever need
// to move it from the Adafruit default.
#include "../config.h"
#include "vl53l0x.h"
#include <Wire.h>
#include <Adafruit_VL53L0X.h>

// I declare the object static to keep its configuration state across calls.
static Adafruit_VL53L0X lox;

void initVL53L0X() {
    if (!lox.begin()) {
        Serial.println("[VL53L0X] ERROR: sensor not found");
        return;
    }
    // I use long-range mode because Phaemos distance sensing applications
    // involve gaps wider than the default 1.2 m limit.
    lox.configSensor(Adafruit_VL53L0X::VL53L0X_SENSE_LONG_RANGE);
    Serial.println("[VL53L0X] init OK");
}

uint16_t readVL53L0X() {
    VL53L0X_RangingMeasurementData_t measure;
    lox.rangingTest(&measure, false); // false = no debug output

    // I check the phase failure flag before trusting the range value
    // because the sensor sets it when the target is out of range.
    if (measure.RangeStatus == 4) {
        // Status 4 is a phase failure / timeout - return 0 to signal invalid.
        return 0;
    }

    return measure.RangeMilliMeter;
}
