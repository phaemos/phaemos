// I include config.h to get LDR_V2_PIN and MAX4466_PIN so the GPIO numbers
// live in one place and are not scattered through sensor implementation files.
#include "../config.h"
#include "ldr.h"
#include <Arduino.h>

float readLDR() {
    // I read LDR_V2_PIN (GPIO33) which is ADC1_CH5 on the ESP32.
    // The ESP32 ADC returns 0-4095 for a 12-bit read; I keep that scale
    // so the backend can apply its own lux calibration curve.
    return (float)analogRead(LDR_V2_PIN);
}

float readMAX4466() {
    // I read MAX4466_PIN (GPIO32) which is ADC1_CH4.
    // The MAX4466 output swings around Vcc/2, so a single analogRead gives
    // an instantaneous amplitude sample - averaging should happen in the caller
    // if an RMS value is needed.
    return (float)analogRead(MAX4466_PIN);
}
