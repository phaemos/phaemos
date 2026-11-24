// use #pragma once to match the style of every other header in this folder.
#pragma once

// initMQ2 configures the digital pin mode. skipWarmup is true only after a warm reset that came
// after the warm-up had completed, because the heater is still hot then. a warm reset inside the
// first 180 s must not skip the rest of the warm-up.
void initMQ2(bool skipWarmup);

// mq2WarmingUp is true until MQ2_WARMUP_MS has passed since a power-on. the end is latched.
bool mq2WarmingUp();

// mq2Fault is true after the warm-up when the analogue reading is near zero, which means a dead
// 5 V rail or a missing module whatever the digital line says.
bool mq2Fault();

// mq2Disagree is true when the digital output alarms but the analogue level reads clean air.
bool mq2Disagree();

// readMQ2 reads both paths of the sensor in one call.
// gas_level   - raw ADC value mapped to 0-1023 (relative gas concentration)
// gas_alert   - true when either path alarms after the warm-up: the digital comparator output is
//               LOW or the analogue level is over GAS_ANALOGUE_ALARM_COUNTS. forced false while the
//               heater warms up and when the analogue reading is near zero (a fault)
// raw_counts  - the raw ADC reading, for the judgement
// digital_low - the digital line
void readMQ2(float* gas_level, bool* gas_alert, int* raw_counts, bool* digital_low);
