// include Arduino.h explicitly because this is a .cpp compilation unit and
// the Arduino IDE does not inject it here automatically.
#include <Arduino.h>

#include "../config.h"
#include "relay.h"

// store the pin numbers in an array indexed by RelayChannel so triggerRelay
// can use the enum directly as an array index - no switch/case needed.
static const uint8_t RELAY_PINS[4] = {
    RELAY_CH1_PIN,
    RELAY_CH2_PIN,
    RELAY_CH3_PIN,
    RELAY_CH4_PIN
};

// the commanded state, kept so a warm reset can put the relays back.
static uint8_t s_mask = 0;

// GPIO14 is relay 3 in the present-board image. it is not touched until the board has been
// recognised, because on the revised board it is the sensor supply switch.
static bool s_gpio14Allowed = false;

static bool pinAllowed(uint8_t pin) {
    return pin != 14 || s_gpio14Allowed;
}

void initRelay() {
    s_mask = 0;
    for (uint8_t i = 0; i < 4; i++) {
        if (!pinAllowed(RELAY_PINS[i])) continue;
        pinMode(RELAY_PINS[i], OUTPUT);
        // write LOW on init because each pin drives an NPN stage - LOW keeps
        // the coil de-energised so loads are off at startup, preventing
        // accidental activation of downstream equipment during boot.
        digitalWrite(RELAY_PINS[i], LOW);
    }
}

void triggerRelay(RelayChannel ch, bool on) {
    if ((uint8_t)ch >= 4) {
        // guard against out-of-range enum casts so a corrupt value cannot
        // drive an arbitrary GPIO.
        return;
    }
    if (!pinAllowed(RELAY_PINS[(uint8_t)ch])) return;
    // the NPN stage is active high: HIGH energises the coil (relay ON),
    // LOW de-energises it (relay OFF).
    digitalWrite(RELAY_PINS[(uint8_t)ch], on ? HIGH : LOW);
    if (on) s_mask |= (uint8_t)(1u << (uint8_t)ch);
    else    s_mask &= (uint8_t)~(1u << (uint8_t)ch);
}

void relayAllowGpio14(bool allow) {
    s_gpio14Allowed = allow;
    if (!allow) return;
    for (uint8_t i = 0; i < 4; i++) {
        if (RELAY_PINS[i] != 14) continue;
        pinMode(RELAY_PINS[i], OUTPUT);
        digitalWrite(RELAY_PINS[i], LOW);
    }
}

uint8_t relayStateMask() {
    return s_mask;
}

void relayRestore(uint8_t mask) {
    for (uint8_t i = 0; i < 4; i++) {
        if (mask & (1u << i)) triggerRelay((RelayChannel)i, true);
    }
}
