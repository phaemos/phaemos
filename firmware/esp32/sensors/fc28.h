// I use #pragma once to match the style of every other header in this folder.
#pragma once

// readFC28 fills both output parameters in one call because they are always
// needed together - a separate water_detected function would just re-read the ADC.
// moisture_level - raw ADC value (0-4095); lower = wetter for resistive sensors
// water_detected - true when the ADC value falls below WATER_THRESHOLD,
//                  meaning conductivity is high enough to confirm water presence
void readFC28(float* moisture_level, bool* water_detected);
