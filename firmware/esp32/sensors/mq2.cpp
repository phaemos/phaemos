// include config.h to get MQ2_ANALOG_PIN and MQ2_DIGITAL_PIN
// without hard-coding magic numbers here.
#include "../config.h"
#include "mq2.h"
#include "analog_checks.h"
#include <Arduino.h>
#include <esp_system.h>

// the end of warm-up is latched once so the alarm cannot be muted again when
// millis() rolls over after about 49 days.
static bool s_warmupDone = false;
static bool s_fault      = false;
static bool s_disagree   = false;

void initMQ2(bool skipWarmup) {
    // the board pulls the digital line up to 3.3 V through its level shifter.
    // GPIO35 has no internal pull resistors on the ESP32, so plain INPUT is correct.
    pinMode(MQ2_DIGITAL_PIN, INPUT);

    // MQ2_ANALOG_PIN (GPIO34) is input-only on ESP32, so no pinMode needed.

    // the heater only stays hot across a reset that did not cut power AND came after the warm-up
    // had completed. a warm reset inside the first 180 s must not skip the rest of it, so the
    // caller passes skipWarmup only when the saved state says the warm-up had finished.
    if (skipWarmup) {
        s_warmupDone = true;
        Serial.println("[MQ2] init OK - reset without a power cycle after the warm-up, the heater is still hot");
    } else {
        Serial.print("[MQ2] init OK - gas alarm ignored for the first ");
        Serial.print(MQ2_WARMUP_MS / 1000UL);
        Serial.println(" s while the heater warms up");
    }
}

bool mq2WarmingUp() {
    if (!s_warmupDone && millis() >= MQ2_WARMUP_MS) {
        s_warmupDone = true;
        Serial.println("[MQ2] warm-up finished - gas alarm is now active");
    }
    return !s_warmupDone;
}

bool mq2Fault() {
    return s_fault;
}

bool mq2Disagree() {
    return s_disagree;
}

void readMQ2(float* gas_level, bool* gas_alert, int* raw_counts, bool* digital_low) {
    // read the 12-bit ESP32 ADC (0-4095) and map it to 0-1023 so the
    // gas_level value matches the 10-bit scale used in Phaemos telemetry
    // for consistency with the Arduino Uno nodes.
    int raw = analogRead(MQ2_ANALOG_PIN);
    *gas_level = map(raw, 0, 4095, 0, 1023);
    *raw_counts = raw;

    // a LOW digital output is an alert because the MQ-2 comparator pulls the DO pin LOW when
    // the gas concentration exceeds the pot setpoint.
    bool low = (digitalRead(MQ2_DIGITAL_PIN) == LOW);
    *digital_low = low;
    *gas_alert = false;

    // the heater reads as gas until it has warmed, so hold the alarm back.
    if (mq2WarmingUp()) {
        s_fault    = false;
        s_disagree = false;
        return;
    }

    // after the warm-up the two paths are judged together (see gasJudge)
    GasJudgement g = gasJudge(raw, low);
    *gas_alert = g.alarm;
    if (g.fault && !s_fault) {
        Serial.println("[MQ2] FAULT: analogue reading near zero - the module is unplugged "
                       "or its 5 V rail is dead, so the gas alarm is not available");
    } else if (!g.fault && s_fault) {
        Serial.println("[MQ2] fault cleared");
    }
    if (g.disagree && !s_disagree) {
        Serial.println("[MQ2] the digital output alarms but the analogue level reads clean air - "
                       "the two paths disagree, the alarm stays raised");
    }
    s_fault    = g.fault;
    s_disagree = g.disagree;
}
