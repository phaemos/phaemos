// use #pragma once for consistency with every other header in this folder.
#pragma once

#include <stdint.h>

// initVL53L0X must run before readVL53L0X; it configures timing and I2C.
// returns true when the sensor answered, false when it is missing so the caller can skip it.
bool initVL53L0X();

// the outcome of one ranging. an error return from the driver is a fault of the part
// (it needs its set-up again) and a failed range status is only a reading left out.
enum Vl53Result {
    VL53_OK,
    VL53_NO_TARGET,
    VL53_ERROR
};

// readVL53L0X fills the distance in millimetres when the result is VL53_OK.
// uint16_t fits the range of 0-8190 mm and matches the register width of the sensor.
Vl53Result readVL53L0X(uint16_t* mm);
