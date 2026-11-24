// use #pragma once for the same reason as every other header in this folder.
#pragma once

#include <stdint.h>

// i2cPresent - true when a device acknowledges its address. call it before each
// read so a device that dropped off the bus is noticed instead of the driver
// returning a garbage value.
bool i2cPresent(uint8_t addr);

// i2cReadReg8 reads one register for an identity check. false when the device does not
// answer, so the caller treats a failed read like an absent device.
bool i2cReadReg8(uint8_t addr, uint8_t reg, uint8_t* value);

// i2cReadBytes reads up to 16 consecutive registers, for the raw data words of a pressure sensor.
bool i2cReadBytes(uint8_t addr, uint8_t reg, uint8_t* out, uint8_t n);

// i2cReadReg16 reads a 16-bit register, high byte first, as the INA219 sends it.
bool i2cReadReg16(uint8_t addr, uint8_t reg, uint16_t* value);
