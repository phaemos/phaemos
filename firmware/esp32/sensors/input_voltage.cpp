#include <Arduino.h>

#include "../config.h"
#include "analog_checks.h"
#include "input_voltage.h"

void initInputVoltage() {
    // GPIO39 is input only and on ADC1, so it needs no pinMode and it does not clash with
    // Wi-Fi. 11 dB covers about 0 to 3 V, which holds the 1.05 V seen at 12 V with room
    // for a 15 V input (about 1.3 V).
    analogSetPinAttenuation(INPUT_VOLTAGE_PIN, ADC_11db);
}

float readInputVoltage() {
    // average a few reads because the ESP32 ADC is noisy. analogReadMilliVolts applies the
    // chip's factory calibration, which a raw count scaled by hand would not.
    uint32_t sum = 0;
    for (uint8_t i = 0; i < INPUT_VOLTAGE_SAMPLES; i++) {
        sum += analogReadMilliVolts(INPUT_VOLTAGE_PIN);
    }
    return inputVoltsFromPinMilliVolts((float)sum / (float)INPUT_VOLTAGE_SAMPLES);
}
