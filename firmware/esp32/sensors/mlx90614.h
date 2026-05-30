// I use #pragma once to keep the header guard minimal and readable.
#pragma once

// initMLX90614 must be called once in setup() before any readMLX90614() call.
void initMLX90614();

// readMLX90614 returns the object (target) temperature in degrees Celsius.
// I return a float directly rather than a struct because this sensor has
// only one measurement of interest for the Phaemos use case.
float readMLX90614();
