// include Arduino.h explicitly because this is a .cpp compilation unit.
#include <Arduino.h>

#include "../config.h"
#include "status_led.h"

// red and amber run from 3.3 V through a resistor to the pin, so LOW lights
// them. green sits behind an NPN stage, so HIGH lights it.
static void setRed(bool on)   { digitalWrite(LED_RED_PIN,   on ? LOW : HIGH); }
static void setAmber(bool on) { digitalWrite(LED_AMBER_PIN, on ? LOW : HIGH); }
static void setGreen(bool on) { digitalWrite(LED_GREEN_PIN, on ? HIGH : LOW); }

void initStatusLeds() {
    pinMode(LED_RED_PIN, OUTPUT);
    pinMode(LED_AMBER_PIN, OUTPUT);
    pinMode(LED_GREEN_PIN, OUTPUT);
    // switch all three off before anything else so no LED lights by accident.
    setRed(false);
    setAmber(false);
    setGreen(false);
}

void setPanelStatus(LEDStatus s) {
    // set every LED on each call so only one is ever lit.
    setGreen(s == STATUS_NORMAL);
    // a fault lights amber too because the panel has no fourth LED. the display
    // and serial log say FAULT in words.
    setAmber(s == STATUS_WARNING || s == STATUS_FAULT);
    setRed(s == STATUS_CRITICAL);
}

const char* statusWord(LEDStatus s) {
    switch (s) {
        case STATUS_NORMAL:   return "NORMAL";
        case STATUS_WARNING:  return "WARNING";
        case STATUS_CRITICAL: return "CRITICAL";
        case STATUS_FAULT:    return "FAULT";
        default:              return "UNKNOWN";
    }
}
