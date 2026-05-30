// I use #pragma once to match the style of every other header in this folder.
#pragma once

// initMQ2 configures the digital pin mode so the alert logic works correctly.
void initMQ2();

// readMQ2 fills both output parameters in one call to avoid the overhead of
// two separate function calls in the telemetry loop.
// gas_level  - raw ADC value mapped to 0-1023 (relative gas concentration)
// gas_alert  - true when the digital comparator output is LOW (threshold crossed)
void readMQ2(float* gas_level, bool* gas_alert);
