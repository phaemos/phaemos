// include config.h first to get AS5600_ADDR, I2C_SDA and I2C_SCL without
// hard-coding the values in this file.
#include "../config.h"
#include "as5600.h"
#include "shaft_math.h"
#include <Wire.h>
#include <Arduino.h>

// AS5600 raw angle registers - high byte at 0x0C, low byte at 0x0D.
// define them here rather than in config.h because they are hardware
// constants from the AS5600 datasheet, not project-specific pin assignments.
#define AS5600_REG_ANGLE_HIGH  0x0C

// the shaft is sampled often (sampleAS5600) and the unwrapped movement is summed, so RPM is the
// true average over the telemetry window. one sample per window would alias as soon as the
// shaft turns more than half a turn between samples. the arithmetic lives in shaft_math.h.
static ShaftWindow s_shaft;

// readRawAngle sends a register address and reads back two bytes, which is
// the standard I2C pattern for the AS5600. returns false when the bus fails.
static bool readRawAngle(uint16_t* raw) {
    Wire.beginTransmission(AS5600_ADDR);
    Wire.write(AS5600_REG_ANGLE_HIGH);
    if (Wire.endTransmission(false) != 0) return false; // repeated start keeps the bus alive

    if (Wire.requestFrom((uint8_t)AS5600_ADDR, (uint8_t)2) != 2) return false;
    uint8_t hi = Wire.read();
    uint8_t lo = Wire.read();

    // mask hi to 4 bits because the top 4 bits of register 0x0C are unused
    // per the AS5600 datasheet and leaving them in would corrupt the angle.
    *raw = ((uint16_t)(hi & 0x0F) << 8) | lo;
    return true;
}

bool initAS5600() {
    // do a quick probe to make sure the sensor is on the bus before
    // the main loop starts relying on its data.
    Wire.beginTransmission(AS5600_ADDR);
    uint8_t err = Wire.endTransmission();
    if (err != 0) {
        Serial.print("[AS5600] ERROR: I2C error ");
        Serial.println(err);
        return false;
    }

    shaftInit(&s_shaft, millis());
    uint16_t raw;
    if (readRawAngle(&raw)) {
        shaftNoteSample(&s_shaft, (raw / 4096.0F) * 360.0F, millis());
        shaftReset(&s_shaft, millis());
    }

    Serial.println("[AS5600] init OK");
    return true;
}

void sampleAS5600() {
    uint16_t raw;
    if (!readRawAngle(&raw)) {
        // forget the previous angle so a gap on the bus is not counted as movement.
        s_shaft.havePrev = false;
        return;
    }
    shaftNoteSample(&s_shaft, (raw / 4096.0F) * 360.0F, millis());
}

bool readAS5600(float* angle, float* rpm) {
    *angle = s_shaft.prevDeg;
    bool ok = s_shaft.havePrev;
    float r = 0.0f;
    bool covered = shaftResult(&s_shaft, millis(), &r);
    *rpm = r;
    return ok && covered;
}
