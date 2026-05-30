// I include config.h first to get AS5600_ADDR, I2C_SDA, and I2C_SCL without
// hard-coding the values in this file.
#include "../config.h"
#include "as5600.h"
#include <Wire.h>
#include <Arduino.h>

// AS5600 raw angle registers - high byte at 0x0C, low byte at 0x0D.
// I define them here rather than in config.h because they are hardware
// constants from the AS5600 datasheet, not project-specific pin assignments.
#define AS5600_REG_ANGLE_HIGH  0x0C
#define AS5600_REG_ANGLE_LOW   0x0D

// I keep the previous angle and timestamp at file scope so RPM can be
// calculated across successive calls without an extra parameter.
static float    s_prevAngle    = 0.0F;
static uint32_t s_prevTime     = 0;
static bool     s_firstRead    = true;

// readRawAngle sends a register address and reads back two bytes, which is
// the standard I2C pattern for the AS5600.
static uint16_t readRawAngle() {
    Wire.beginTransmission(AS5600_ADDR);
    Wire.write(AS5600_REG_ANGLE_HIGH);
    Wire.endTransmission(false); // I use repeated-start (false) to keep the bus alive

    Wire.requestFrom((uint8_t)AS5600_ADDR, (uint8_t)2);
    uint8_t hi = Wire.available() ? Wire.read() : 0;
    uint8_t lo = Wire.available() ? Wire.read() : 0;

    // I mask hi to 4 bits because the top 4 bits of register 0x0C are unused
    // per the AS5600 datasheet, and leaving them in would corrupt the angle.
    return ((uint16_t)(hi & 0x0F) << 8) | lo;
}

void initAS5600() {
    // I do a quick probe to make sure the sensor is on the bus before
    // the main loop starts relying on its data.
    Wire.beginTransmission(AS5600_ADDR);
    uint8_t err = Wire.endTransmission();
    if (err != 0) {
        Serial.print("[AS5600] ERROR: I2C error ");
        Serial.println(err);
        return;
    }

    // Prime the baseline so the first RPM calculation has a reference.
    uint16_t raw  = readRawAngle();
    s_prevAngle   = (raw / 4096.0F) * 360.0F;
    s_prevTime    = millis();
    s_firstRead   = false;

    Serial.println("[AS5600] init OK");
}

void readAS5600(float* angle, float* rpm) {
    uint32_t now  = millis();
    uint16_t raw  = readRawAngle();
    float    deg  = (raw / 4096.0F) * 360.0F; // map 0-4095 to 0-360 degrees

    *angle = deg;

    if (s_firstRead) {
        // I skip RPM on the very first call because there is no previous
        // sample to diff against - returning 0 is safer than garbage.
        *rpm       = 0.0F;
        s_firstRead = false;
    } else {
        float dtSec = (now - s_prevTime) / 1000.0F;

        if (dtSec > 0.0F) {
            // I compute the shortest angular delta to handle wrap-around
            // at the 0/360 boundary correctly.
            float delta = deg - s_prevAngle;
            if (delta >  180.0F) delta -= 360.0F;
            if (delta < -180.0F) delta += 360.0F;

            // Convert degrees/second to RPM: (deg/s) / 360 * 60.
            *rpm = (delta / dtSec) / 360.0F * 60.0F;
        } else {
            *rpm = 0.0F;
        }
    }

    s_prevAngle = deg;
    s_prevTime  = now;
}
