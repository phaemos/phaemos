// use #pragma once so the compiler ignores this header on subsequent includes
// without requiring a matching #endif at the bottom of the file.
#pragma once

// define BuzzerPattern as a named enum so call sites read as plain English
// instead of magic integers - easier to review and less error-prone.
enum BuzzerPattern {
    PATTERN_NORMAL   = 0, // single quiet beep - all clear
    PATTERN_WARNING  = 1, // two short beeps - threshold crossed
    PATTERN_CRITICAL = 2  // three rapid repeated beeps - immediate action needed
};

// initBuzzer - call once in setup() to configure BUZZER_PIN as an output.
void initBuzzer();

#include <stdint.h>

// beep - emits a single tone on BUZZER_PIN for the given duration in milliseconds.
// this blocks, so only use it during boot.
// expose this as a primitive so other modules can build custom sequences.
void beep(uint16_t ms);

// beepPattern - starts one of the three predefined alert patterns without
// blocking. returns true when the pattern started and false when it was dropped.
// a request made while a pattern is playing is dropped, except that CRITICAL
// pre-empts a lesser pattern.
bool beepPattern(BuzzerPattern p);

// buzzerUpdate - call on every loop() pass to advance the running pattern.
void buzzerUpdate();
