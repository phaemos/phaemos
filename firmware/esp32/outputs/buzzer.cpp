// I include Arduino.h explicitly because this is a .cpp file - the Arduino
// build system injects it automatically only in .ino files.
#include <Arduino.h>

#include "../config.h"
#include "buzzer.h"

void initBuzzer() {
    // I set the pin mode here rather than in the sketch so the buzzer module
    // owns its own initialisation and setup() stays uncluttered.
    pinMode(BUZZER_PIN, OUTPUT);
    // I ensure the pin starts LOW so the buzzer does not emit noise during
    // the rest of the boot sequence before any pattern is played.
    digitalWrite(BUZZER_PIN, LOW);
}

void beep(uint16_t ms) {
    // I use 2000 Hz because it cuts through ambient noise without being
    // painfully shrill in an enclosed cabinet.
    tone(BUZZER_PIN, 2000);
    delay(ms);
    noTone(BUZZER_PIN);
}

void beepPattern(BuzzerPattern p) {
    switch (p) {
        case PATTERN_NORMAL:
            // I play one short beep for NORMAL so the operator gets audible
            // confirmation that the system has returned to a healthy state.
            beep(100);
            break;

        case PATTERN_WARNING:
            // I use two beeps with a 150 ms gap to distinguish WARNING from
            // the single-beep NORMAL and the rapid three-beep CRITICAL.
            beep(200);
            delay(150);
            beep(200);
            break;

        case PATTERN_CRITICAL:
            // I repeat the three-beep sequence twice so it cannot be missed
            // in a noisy environment.
            for (uint8_t rep = 0; rep < 2; rep++) {
                beep(100);
                delay(80);
                beep(100);
                delay(80);
                beep(100);
                // I pause between repetitions so the operator can count them.
                if (rep < 1) delay(300);
            }
            break;

        default:
            // I do nothing for unknown patterns rather than assert or halt
            // so a stale enum value does not crash the firmware.
            break;
    }
}
