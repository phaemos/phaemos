// use #pragma once to stay consistent with the rest of the sensor headers.
#pragma once

// readLDR reads the LDR (light-dependent resistor) on LDR_V2_PIN (GPIO33).
// returns a raw ADC value in the range 0-4095.
// return float rather than int so callers can apply calibration multipliers
// without an explicit cast.
float readLDR();

// readMAX4466 reads the MAX4466 microphone amplifier on MAX4466_PIN (GPIO32).
// returns the peak-to-peak ADC swing over a 20 ms window (0-4095) because the output
// rides on a Vcc/2 offset and a single sample says nothing about loudness.
// Co-locate this function with the LDR because both are analog-only sensors
// that share the same read pattern and need no init sequence.
// when meanCounts is not null it receives the mean ADC count over the same window.
float readMAX4466(float* meanCounts = nullptr);
