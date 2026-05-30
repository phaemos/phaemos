// I use #pragma once for consistency with every other header in this folder.
#pragma once

#include <stdint.h>

// initVL53L0X must run before readVL53L0X; it configures timing and I2C.
void initVL53L0X();

// readVL53L0X returns distance in millimetres.
// I return uint16_t because VL53L0X range is 0-8190 mm - a uint16_t fits
// that without waste and matches the register width of the sensor.
// Returns 0 on timeout or ranging error.
uint16_t readVL53L0X();
