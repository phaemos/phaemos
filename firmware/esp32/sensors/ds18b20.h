// I use #pragma once for the same reason as every other header here.
#pragma once

// initDS18B20 must be called in setup() to start the OneWire bus and set
// the sensor resolution defined in config.h.
void initDS18B20();

// readDS18B20 returns temperature in degrees Celsius.
// Returns -127.0 on error, which is the DallasTemperature sentinel for
// a failed read - callers can check for this value before using the result.
float readDS18B20();
