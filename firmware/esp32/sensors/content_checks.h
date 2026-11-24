// content_checks.h - pure decisions about what a sensor's registers say. header only and
// free of Arduino types, so the host test in test_host/ can include it unchanged.
#pragma once

#include <stdint.h>

#include "../config.h"
#include "health.h"

// MPU6050 PWR_MGMT_1 (0x6B) bit 6 is SLEEP. the set-up clears it and a reset sets it, so a
// set bit on a part that still answers with the right identity means it lost its set-up.
inline bool mpuSleepBitSet(uint8_t pwrMgmt1) { return (pwrMgmt1 & 0x40) != 0; }

// a reset MPU6050 reads zero on every axis. a working one always sees gravity on at least
// one axis, so exactly zero on all three is a reset and not a reading.
inline bool mpuAllZero(float x, float y, float z) { return x == 0.0f && y == 0.0f && z == 0.0f; }

// INA219 calibration register (0x05). it resets to zero and the set-up writes a non-zero
// value, so zero before a read means the chip lost its set-up. the configuration register
// cannot show this, because the range the sketch uses is the chip's reset default (0x399F).
inline bool inaLostSetup(uint16_t calibrationReg) { return calibrationReg == 0; }

// INA219 bus voltage register (0x02) bit 0 is OVF, the math overflow flag.
inline bool inaOverflow(uint16_t busVoltageReg) { return (busVoltageReg & 0x0001) != 0; }

// AS5600 STATUS register (0x0B): MH 0x08 too strong, ML 0x10 too weak, MD 0x20 detected.
// no magnet is a fault. a marginal gap (MH or ML with MD set) still gives a valid angle,
// so it is only noted.
inline HealthState as5600MagnetState(uint8_t status) {
    return (status & 0x20) ? HS_OK : HS_OUT_OF_RANGE;
}
inline bool as5600MagnetMarginal(uint8_t status) { return (status & 0x18) != 0; }

// BME280 and BMP280 ctrl_meas (0xF4). mode is bits 1 and 0. after a reset the register reads 0
// (sleep mode) and the data registers hold the reset word. the BME280 driver turns that into
// NAN, but the BMP280 driver compensates it into a plausible 26 degC, so the decision cannot
// rest on the reading. the set-up leaves normal mode (3), while a forced conversion shows as 1
// or 2 for a moment, so only 0 means the set-up is gone.
inline bool bmeLostSetup(uint8_t ctrlMeas) { return (ctrlMeas & 0x03) == 0; }

// DS18B20 power-on value. a part that has reset holds exactly 85.0 degC until its first
// conversion ends. a real 85.0 that follows a reading near it is a temperature.
inline bool ds18PowerOnValue(float t, float previous, bool havePrevious) {
    if (t != DS18_POWER_ON_C) return false;
    if (!havePrevious) return true;
    float d = previous - DS18_POWER_ON_C;
    if (d < 0) d = -d;
    return d > DS18_POWER_ON_NEAR_C;
}
