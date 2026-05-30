// I include Arduino.h explicitly because this is a .cpp compilation unit and
// the Arduino IDE does not inject it here automatically.
#include <Arduino.h>

#include "../config.h"
#include "relay.h"

// I store the pin numbers in an array indexed by RelayChannel so triggerRelay
// can use the enum directly as an array index - no switch/case needed.
static const uint8_t RELAY_PINS[4] = {
    RELAY_CH1_PIN,
    RELAY_CH2_PIN,
    RELAY_CH3_PIN,
    RELAY_CH4_PIN
};

void initRelay() {
    for (uint8_t i = 0; i < 4; i++) {
        pinMode(RELAY_PINS[i], OUTPUT);
        // I write HIGH on init because the relay module is active-low - HIGH
        // keeps the coil de-energised so loads are off at startup, preventing
        // accidental activation of downstream equipment during boot.
        digitalWrite(RELAY_PINS[i], HIGH);
    }
}

void triggerRelay(RelayChannel ch, bool on) {
    if ((uint8_t)ch >= 4) {
        // I guard against out-of-range enum casts so a corrupt value cannot
        // drive an arbitrary GPIO.
        return;
    }
    // I invert the logic here because the module is active-low:
    // writing LOW energises the coil (relay ON), HIGH de-energises it (relay OFF).
    digitalWrite(RELAY_PINS[(uint8_t)ch], on ? LOW : HIGH);
}
