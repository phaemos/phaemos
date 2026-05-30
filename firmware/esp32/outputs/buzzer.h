// I use #pragma once so the compiler ignores this header on subsequent includes
// without requiring a matching #endif at the bottom of the file.
#pragma once

// I define BuzzerPattern as a named enum so call sites read as plain English
// instead of magic integers - easier to review and less error-prone.
enum BuzzerPattern {
    PATTERN_NORMAL   = 0, // single quiet beep - all clear
    PATTERN_WARNING  = 1, // two short beeps - threshold crossed
    PATTERN_CRITICAL = 2  // three rapid repeated beeps - immediate action needed
};

// initBuzzer - call once in setup() to configure BUZZER_PIN as an output.
void initBuzzer();

// beep - emits a single tone on BUZZER_PIN for the given duration in milliseconds.
// I expose this as a primitive so other modules can build custom sequences.
void beep(uint16_t ms);

// beepPattern - plays one of the three predefined alert patterns.
void beepPattern(BuzzerPattern p);
