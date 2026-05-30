// I include config.h to get FC28_PIN and WATER_THRESHOLD so threshold
// tuning only requires editing config.h, not hunting through sensor files.
#include "../config.h"
#include "fc28.h"
#include <Arduino.h>

void readFC28(float* moisture_level, bool* water_detected) {
    // FC28_PIN is GPIO36 (VP), an input-only ADC1 channel on the ESP32.
    // I cast to float immediately so callers can scale without an explicit cast.
    int raw = analogRead(FC28_PIN);
    *moisture_level = (float)raw;

    // I test raw < WATER_THRESHOLD rather than > because the FC28 is a
    // resistive sensor - lower resistance (more water) means lower ADC value.
    // WATER_THRESHOLD is defined in config.h so it can be tuned per deployment.
    *water_detected = (raw < WATER_THRESHOLD);
}
