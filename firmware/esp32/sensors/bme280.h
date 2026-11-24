// use #pragma once instead of an #ifndef guard because it is simpler and
// universally supported by every compiler this project targets.
#pragma once

#include <stdint.h>

// BME280Reading holds all three measurements in one struct so callers
// never have to manage three separate variables per sensor poll.
struct BME280Reading {
    float temperature; // degrees Celsius
    float humidity;    // percent relative humidity, NAN on a BMP280 which has no humidity element
    float pressure;    // hPa
};

// Forward-declare these as plain C-style functions so any .cpp file can
// call them without pulling in C++ class headers they do not need.
// returns true when the sensor answered, false when it is missing so the caller can skip it.
bool initBME280();

// bme280Address returns the I2C address the chip answered on (0x76 or 0x77),
// so the caller can probe the right one before each read.
uint8_t bme280Address();
void readBME280(BME280Reading* r);
