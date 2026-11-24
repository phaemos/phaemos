// include Arduino.h explicitly because this is a .cpp file - the Arduino
// build system injects it automatically only in .ino files.
#include <Arduino.h>

#include "../config.h"
#include "buzzer.h"

#define BUZZER_FREQ_HZ 2000

void initBuzzer() {
    // set the pin mode here rather than in the sketch so the buzzer module
    // owns its own initialisation and setup() stays uncluttered.
    pinMode(BUZZER_PIN, OUTPUT);
    // ensure the pin starts LOW so the buzzer does not emit noise during
    // the rest of the boot sequence before any pattern is played.
    digitalWrite(BUZZER_PIN, LOW);
}

void beep(uint16_t ms) {
    // 2 kHz cuts through ambient noise without being painfully shrill in an
    // enclosed cabinet. the NPN stage energises on HIGH so tone() drives it directly.
    tone(BUZZER_PIN, BUZZER_FREQ_HZ);
    delay(ms);
    noTone(BUZZER_PIN);
    digitalWrite(BUZZER_PIN, LOW);
}

// each pattern is a list of alternating tone and silence lengths in milliseconds,
// starting with a tone and ended by a zero. a table keeps the timing out of the
// loop so beepPattern never has to wait.
static const uint16_t STEPS_NORMAL[]   = { 100, 0 };
static const uint16_t STEPS_WARNING[]  = { 200, 150, 200, 0 };
static const uint16_t STEPS_CRITICAL[] = { 100, 80, 100, 80, 100, 300, 100, 80, 100, 80, 100, 0 };

static const uint16_t* s_steps = nullptr;
static uint8_t         s_index = 0;
static uint32_t        s_stepStart = 0;
static BuzzerPattern   s_playing   = PATTERN_NORMAL;

// even indexes are tones and odd indexes are gaps.
static void startStep() {
    if ((s_index & 1) == 0) {
        tone(BUZZER_PIN, BUZZER_FREQ_HZ);
    } else {
        noTone(BUZZER_PIN);
    }
    s_stepStart = millis();
}

bool beepPattern(BuzzerPattern p) {
    const uint16_t* steps = nullptr;
    switch (p) {
        case PATTERN_NORMAL:   steps = STEPS_NORMAL;   break;
        case PATTERN_WARNING:  steps = STEPS_WARNING;  break;
        case PATTERN_CRITICAL: steps = STEPS_CRITICAL; break;
        default:
            // do nothing for unknown patterns rather than assert or halt
            // so a stale enum value does not crash the firmware.
            return false;
    }

    if (s_steps != nullptr) {
        // drop the request while a pattern plays, so a repeating alert cannot
        // restart itself on every pass. only a critical request cuts in on a lesser pattern.
        if (!(p == PATTERN_CRITICAL && s_playing != PATTERN_CRITICAL)) return false;
        noTone(BUZZER_PIN);
    }

    s_steps   = steps;
    s_playing = p;
    s_index   = 0;
    startStep();
    return true;
}

void buzzerUpdate() {
    if (s_steps == nullptr) return;
    if (millis() - s_stepStart < s_steps[s_index]) return;

    s_index++;
    if (s_steps[s_index] == 0) {
        // pattern finished - release the pin and go idle.
        noTone(BUZZER_PIN);
        digitalWrite(BUZZER_PIN, LOW);
        s_steps = nullptr;
        return;
    }
    startStep();
}
