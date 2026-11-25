// relay_proof.cpp - see relay_proof.h. no Arduino calls, so the host test builds it as it is.
#include "relay_proof.h"

void RelayProofTracker::command(uint8_t ch, bool on, uint32_t nowMs, RailReading before) {
    if (ch >= kChannels) return;
    Channel &c = ch_[ch];
    if (!on) {
        c = Channel{};
        return;
    }
    // unconfirmed from the moment it is commanded. it becomes confirmed only from a reading
    c.proof = RELAY_UNCONFIRMED;
    c.waiting = before.valid;
    c.sinceMs = nowMs;
    c.beforeMa = before.ma;
}

void RelayProofTracker::tick(uint8_t ch, uint32_t nowMs, RailReading now) {
    if (ch >= kChannels) return;
    Channel &c = ch_[ch];
    // unsigned difference, so a timer wrap between the two readings does not matter
    if (!c.waiting || (uint32_t)(nowMs - c.sinceMs) < RELAY_PULL_IN_MS) return;
    c.waiting = false;
    c.proof = now.valid && now.ma - c.beforeMa >= RELAY_COIL_MIN_RISE_MA ? RELAY_CONFIRMED : RELAY_UNCONFIRMED;
}

RelayProof RelayProofTracker::proof(uint8_t ch) const {
    return ch < kChannels ? ch_[ch].proof : RELAY_OFF;
}

bool RelayProofTracker::waiting(uint8_t ch) const {
    return ch < kChannels && ch_[ch].waiting;
}

uint8_t RelayProofTracker::unconfirmedMask() const {
    uint8_t mask = 0;
    for (uint8_t i = 0; i < kChannels; i++) {
        if (ch_[i].proof == RELAY_UNCONFIRMED) mask |= (uint8_t)(1u << i);
    }
    return mask;
}
