// use #pragma once consistently with every sensor header in this project.
#pragma once

// initAS5600 checks the sensor is on the bus and primes the angle baseline.
// returns true when the sensor answered, false when it is missing so the caller can skip it.
bool initAS5600();

// sampleAS5600 reads the angle and adds the movement since the last sample.
// call it every AS5600_SAMPLE_MS from loop() so fast shafts do not alias.
void sampleAS5600();

// readAS5600 reports the angle and the average RPM since the previous call.
// angle - shaft position in degrees (0.0 - 360.0)
// rpm   - rotational speed in revolutions per minute (negative for reverse)
// returns false when no good sample arrived in the window, so the values are not usable.
bool readAS5600(float* angle, float* rpm);
