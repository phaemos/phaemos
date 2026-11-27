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

// what is known about each relay beyond its command, plus the rail meter that can show it
static RelayProofTracker s_proofs;
static bool (*s_railRead)(int32_t *ma) = nullptr;

static RailReading readRail() {
    int32_t ma = 0;
    if (s_railRead == nullptr || !s_railRead(&ma)) return RailReading{false, 0};
    return RailReading{true, ma};
}

// GPIO14 is relay 3 in the present-board image. it is not touched until the board has been
// recognised, because on the revised board it is the sensor supply switch.
static bool s_gpio14Allowed = false;

static bool pinAllowed(uint8_t pin) {
    return pin != 14 || s_gpio14Allowed;
}

void initRelay() {
    s_mask = 0;
    s_proofs = RelayProofTracker();
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
    uint8_t bit = (uint8_t)(1u << (uint8_t)ch);
    bool was = (s_mask & bit) != 0;
    if (on == was) {
        // the same command again on a later pass: the moment to read the rail once the coil has had time
        if (s_proofs.waiting((uint8_t)ch)) {
            s_proofs.tick((uint8_t)ch, millis(), readRail());
            if (s_proofs.proof((uint8_t)ch) == RELAY_CONFIRMED) {
                Serial.printf("relay %u switched on, confirmed by the rail current\n", (unsigned)ch + 1);
            } else {
                Serial.printf("relay %u commanded on, not confirmed: the rail did not rise by a coil's worth\n", (unsigned)ch + 1);
            }
        }
        digitalWrite(RELAY_PINS[(uint8_t)ch], on ? HIGH : LOW);
        return;
    }
    // the rail is read just before the change, so the rise after it is the coil's
    RailReading before = on ? readRail() : RailReading{false, 0};
    // the NPN stage is active high: HIGH energises the coil (relay ON),
    // LOW de-energises it (relay OFF).
    digitalWrite(RELAY_PINS[(uint8_t)ch], on ? HIGH : LOW);
    if (on) s_mask |= bit;
    else    s_mask &= (uint8_t)~bit;
    s_proofs.command((uint8_t)ch, on, millis(), before);
    if (on && !before.valid) {
        Serial.printf("relay %u commanded on, not confirmed: this board has no rail current reading\n", (unsigned)ch + 1);
    }
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

void relaySetRailReader(bool (*read)(int32_t *ma)) {
    s_railRead = read;
}

RelayProof relayProof(RelayChannel ch) {
    return s_proofs.proof((uint8_t)ch);
}

uint8_t relayUnconfirmedMask() {
    return s_proofs.unconfirmedMask();
}

void relayRestore(uint8_t mask) {
    for (uint8_t i = 0; i < 4; i++) {
        if (mask & (1u << i)) triggerRelay((RelayChannel)i, true);
    }
}
