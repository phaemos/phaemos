// I use #pragma once consistently with every sensor header in this project.
#pragma once

// initAS5600 sets up I2C and primes the angle baseline for RPM calculation.
void initAS5600();

// readAS5600 fills both angle and rpm in one call because RPM requires
// a previous angle sample, so keeping them together avoids a second I2C read.
// angle - shaft position in degrees (0.0 - 360.0)
// rpm   - rotational speed in revolutions per minute (can be negative for reverse)
void readAS5600(float* angle, float* rpm);
