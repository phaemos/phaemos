// use #pragma once for the same reason as every other header here.
#pragma once

// initDS18B20 must be called in setup() to start the OneWire bus and set
// the sensor resolution defined in config.h.
// returns true when the sensor answered, false when it is missing so the caller can skip it.
// quiet suppresses the not-found log, for the repeated search while a probe is missing.
bool initDS18B20(bool quiet = false);

// readDS18B20 returns temperature in degrees Celsius.
// returns -127.0 on error, which is the DallasTemperature sentinel for
// a failed read - callers can check for this value before using the result.
float readDS18B20();
