// I include config.h to get MQ2_ANALOG_PIN, MQ2_DIGITAL_PIN, and
// GAS_WARNING_LEVEL without hard-coding magic numbers here.
#include "../config.h"
#include "mq2.h"
#include <Arduino.h>

void initMQ2() {
    // I configure the digital pin as INPUT_PULLUP because the MQ-2 module's
    // comparator output is open-collector - it needs a pull-up to read HIGH
    // when gas is below threshold.
    pinMode(MQ2_DIGITAL_PIN, INPUT_PULLUP);

    // MQ2_ANALOG_PIN (GPIO34) is input-only on ESP32, so no pinMode needed.
    Serial.println("[MQ2] init OK");
}

void readMQ2(float* gas_level, bool* gas_alert) {
    // I read the 12-bit ESP32 ADC (0-4095) and map it to 0-1023 so the
    // gas_level value matches the 10-bit scale used in Phaemos telemetry
    // for consistency with the Arduino Uno nodes.
    int raw = analogRead(MQ2_ANALOG_PIN);
    *gas_level = map(raw, 0, 4095, 0, 1023);

    // I treat a LOW digital output as an alert because the MQ-2 comparator
    // pulls the DO pin LOW when the gas concentration exceeds the pot setpoint.
    *gas_alert = (digitalRead(MQ2_DIGITAL_PIN) == LOW);
}
