// I use #pragma once to stay consistent with the rest of the sensor headers.
#pragma once

// readLDR reads the LDR (light-dependent resistor) on LDR_V2_PIN (GPIO33).
// Returns a raw ADC value in the range 0-4095.
// I return float rather than int so callers can apply calibration multipliers
// without an explicit cast.
float readLDR();

// readMAX4466 reads the MAX4466 microphone amplifier on MAX4466_PIN (GPIO32).
// Returns the raw ADC value in the range 0-4095.
// I co-locate this function with the LDR because both are analog-only sensors
// that share the same read pattern and need no init sequence.
float readMAX4466();
