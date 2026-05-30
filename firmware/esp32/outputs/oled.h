// I use #pragma once to avoid double-inclusion without the noise of a manual
// #ifndef guard - every compiler this project targets supports it.
#pragma once

// I pull in the sensor structs here so callers only need one include to drive
// displayTelemetry - no risk of struct definitions getting out of sync.
#include "../sensors/bme280.h"
#include "../sensors/mpu6050.h"
#include "../sensors/ina219.h"

// initOLED - call once in setup() to start the SSD1306 over I2C.
void initOLED();

// displaySplash - shows a boot screen with title and subtitle centred on the
// display, then waits 2 s so the user can read it before telemetry starts.
void displaySplash(const char* title, const char* subtitle);

// displayTelemetry - redraws the full 4-line data screen on every OLED_UPDATE_MS
// tick. Passing all readings by value keeps this call site simple.
// dist is in mm (from VL53L0X), gas and water are boolean alert flags.
void displayTelemetry(BME280Reading bme, MPU6050Reading mpu, INA219Reading ina,
                      uint16_t dist, bool gas, bool water);
