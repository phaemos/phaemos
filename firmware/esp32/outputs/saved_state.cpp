#include "saved_state.h"

#include <string.h>

namespace {

// FNV-1a over the bytes before the checksum field
uint32_t checksum(const SavedState* s) {
    const uint8_t* p = (const uint8_t*)s;
    uint32_t h = 2166136261u;
    for (unsigned i = 0; i < sizeof(SavedState) - sizeof(uint32_t); i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

}  // namespace

void ssSeal(SavedState* s) {
    s->magic = SAVED_STATE_MAGIC;
    s->reserved[0] = s->reserved[1] = s->reserved[2] = 0;
    s->check = checksum(s);
}

void ssReset(SavedState* s) {
    memset(s, 0, sizeof *s);
    ssSeal(s);
}

bool ssValid(const SavedState* s) {
    if (s->magic != SAVED_STATE_MAGIC || s->check != checksum(s)) return false;
    return s->relayMask <= 0x0F && s->linksSeen <= 3 && s->setupMarker <= SETUP_COUNT &&
           s->latchMask <= 7 && s->gasWarmedUp <= 1;
}

bool ssWarmResetReason(int r) {
    return r == 3 || r == 4 || r == 5 || r == 6 || r == 7;
}

bool ssTaskWatchdogReason(int r) {
    return r == 6;
}

RestoreVerdict ssRestoreVerdict(int espResetReason, const SavedState* s) {
    if (!ssWarmResetReason(espResetReason) || !ssValid(s)) return RV_NONE;
    if (s->unconfirmed >= RESTORE_MAX_UNCONFIRMED) return RV_REFUSE;
    return RV_RESTORE;
}

void ssNoteBoot(SavedState* s) {
    if (s->unconfirmed < 255) s->unconfirmed++;
    ssSeal(s);
}

void ssNoteConfirmed(SavedState* s) {
    if (s->unconfirmed == 0) return;
    s->unconfirmed = 0;
    ssSeal(s);
}

void ssStoreJudge(SavedState* s, const TempJudge* j) {
    for (uint8_t i = 0; i < TS_COUNT; i++) s->critCount[i] = j->count[i];
    s->latchMask = tjLatchMask(j);
}

void ssLoadJudge(const SavedState* s, TempJudge* j) {
    tjRestore(j, s->critCount, s->latchMask);
}

RestoreStep ssRestoreStep(bool pending, bool goodReading, uint32_t nowMs, uint32_t deadlineMs) {
    if (!pending) return RESTORE_NONE;
    if (goodReading) return RESTORE_CONFIRMED;
    // signed difference, so the deadline still works across a millis() rollover
    if ((int32_t)(nowMs - deadlineMs) >= 0) return RESTORE_DROP;
    return RESTORE_WAIT;
}

SetupVerdict ssSetupBootCheck(SavedState* s, int espResetReason) {
    SetupVerdict v;
    memset(&v, 0, sizeof v);
    if (!ssWarmResetReason(espResetReason) || !ssValid(s)) return v;
    if (s->setupMarker != 0) {
        uint8_t id = (uint8_t)(s->setupMarker - 1);
        // only a task watchdog reset is what a stalled set-up ends in. a panic in another task
        // or a software reset that happened to land inside a set-up is not the sensor's fault
        if (ssTaskWatchdogReason(espResetReason)) {
            if (s->strikes[id] < 255) s->strikes[id]++;
            v.skipThisBoot[id] = true;
        }
        s->setupMarker = 0;
        ssSeal(s);
    }
    for (uint8_t i = 0; i < SETUP_COUNT; i++) v.excluded[i] = s->strikes[i] >= SETUP_MAX_STRIKES;
    return v;
}

void ssSetupBegin(SavedState* s, SetupId id) {
    s->setupMarker = (uint8_t)(id + 1);
    ssSeal(s);
}

void ssSetupEnd(SavedState* s) {
    s->setupMarker = 0;
    ssSeal(s);
}

bool ssSetupExcluded(const SavedState* s, SetupId id) {
    return s->strikes[id] >= SETUP_MAX_STRIKES;
}

bool ssStrikeForgiveDue(uint32_t doneMs, uint32_t nowMs, uint32_t forgiveMs) {
    return (uint32_t)(nowMs - doneMs) >= forgiveMs;
}

bool ssForgive(SavedState* s, SetupId id) {
    if (s->strikes[id] == 0) return false;
    s->strikes[id] = 0;
    ssSeal(s);
    return true;
}

void ssNoteGasWarmed(SavedState* s) {
    if (s->gasWarmedUp) return;
    s->gasWarmedUp = 1;
    ssSeal(s);
}
