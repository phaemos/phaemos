// include config.h to get LDR_V2_PIN and MAX4466_PIN so the GPIO numbers
// live in one place and are not scattered through sensor implementation files.
#include "../config.h"
#include "ldr.h"
#include <Arduino.h>

float readLDR() {
    // read LDR_V2_PIN (GPIO33) which is ADC1_CH5 on the ESP32.
    // the ESP32 ADC returns 0-4095 for a 12-bit read; keep that scale
    // so the backend can apply its own lux calibration curve.
    return (float)analogRead(LDR_V2_PIN);
}

float readMAX4466(float* meanCounts) {
    // read MAX4466_PIN (GPIO32) which is ADC1_CH4.
    // the MAX4466 output swings around Vcc/2, so one sample is meaningless on
    // its own. track the peak-to-peak swing over 20 ms instead, which spans a
    // full cycle down to 50 Hz and rises with loudness.
    int lo = 4095;
    int hi = 0;
    uint32_t sum = 0;
    uint32_t n   = 0;
    uint32_t start = millis();
    while (millis() - start < 20) {
        int v = analogRead(MAX4466_PIN);
        if (v < lo) lo = v;
        if (v > hi) hi = v;
        sum += v;
        n++;
    }
    // the mean is the DC level, which tells a working module (near half supply) from an
    // unplugged one (0 V) when the room is quiet.
    if (meanCounts) *meanCounts = n ? (float)sum / (float)n : 0.0f;
    return (float)(hi - lo);
}
