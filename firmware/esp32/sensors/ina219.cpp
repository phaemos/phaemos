// I include config.h before the Adafruit header so INA219_ADDR is already
// defined if the library ever needs it at include-time.
#include "../config.h"
#include "ina219.h"
#include <Wire.h>
#include <Adafruit_INA219.h>

// I pass the I2C address from config.h to the constructor so that changing
// the hardware address only requires editing one file.
static Adafruit_INA219 ina219(INA219_ADDR);

void initINA219() {
    if (!ina219.begin()) {
        Serial.println("[INA219] ERROR: sensor not found");
        return;
    }
    // I leave calibration at the Adafruit default (32V / 2A) because the
    // Phaemos power rail never exceeds those limits.
    Serial.println("[INA219] init OK");
}

void readINA219(INA219Reading* r) {
    r->bus_voltage = ina219.getBusVoltage_V();
    r->current_ma  = ina219.getCurrent_mA();
    // I derive power here rather than calling getPower_mW() because the
    // Adafruit method can return stale register values if the shunt overflows.
    r->power_mw    = r->bus_voltage * r->current_ma;
}
