#include <Wire.h>

#include "i2c_probe.h"

bool i2cPresent(uint8_t addr) {
    // an address-only transfer is the cheapest check there is. zero means
    // the device acknowledged.
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

bool i2cReadReg8(uint8_t addr, uint8_t reg, uint8_t* value) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(addr, (uint8_t)1) != 1) return false;
    *value = Wire.read();
    return true;
}

bool i2cReadReg16(uint8_t addr, uint8_t reg, uint16_t* value) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(addr, (uint8_t)2) != 2) return false;
    uint8_t hi = Wire.read();
    uint8_t lo = Wire.read();
    *value = ((uint16_t)hi << 8) | lo;
    return true;
}

bool i2cReadBytes(uint8_t addr, uint8_t reg, uint8_t* out, uint8_t n) {
    if (n == 0 || n > 16) return false;
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(addr, n) != n) return false;
    for (uint8_t i = 0; i < n; i++) out[i] = Wire.read();
    return true;
}
