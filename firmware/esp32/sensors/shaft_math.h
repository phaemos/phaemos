// shaft_math.h - the rpm arithmetic for the AS5600, free of Arduino types so the host test can
// include it. the shaft is sampled on a fast tick and the movement between samples is summed.
// the rpm divides by the time the samples actually cover and not by the wall time of the
// window, so a loop that was blocked for a while cannot make the rpm read low.
#pragma once

#include <stdint.h>

#include "../config.h"

struct ShaftWindow {
    float    prevDeg;
    bool     havePrev;
    uint32_t prevMs;
    float    totalDeg;      // signed movement over the covered time
    uint32_t coveredMs;     // time between trusted sample pairs
    uint32_t windowStartMs;
    uint16_t goodSamples;
};

inline void shaftReset(ShaftWindow* w, uint32_t nowMs) {
    w->totalDeg = 0.0f;
    w->coveredMs = 0;
    w->goodSamples = 0;
    w->windowStartMs = nowMs;
}

inline void shaftInit(ShaftWindow* w, uint32_t nowMs) {
    w->prevDeg = 0.0f;
    w->havePrev = false;
    w->prevMs = nowMs;
    shaftReset(w, nowMs);
}

// shaftNoteSample adds one angle sample. a gap past AS5600_MAX_GAP_MS is not counted, neither
// its movement nor its time, because the shaft could have turned more than half a turn in it.
inline void shaftNoteSample(ShaftWindow* w, float deg, uint32_t nowMs) {
    if (w->havePrev) {
        uint32_t dt = (uint32_t)(nowMs - w->prevMs);
        if (dt > 0 && dt <= AS5600_MAX_GAP_MS) {
            float delta = deg - w->prevDeg;
            if (delta >  180.0f) delta -= 360.0f;
            if (delta < -180.0f) delta += 360.0f;
            w->totalDeg  += delta;
            w->coveredMs += dt;
        }
    }
    w->prevDeg  = deg;
    w->prevMs   = nowMs;
    w->havePrev = true;
    w->goodSamples++;
}

// shaftResult returns false when the samples cover too little of the window to give an rpm.
// it always starts the next window.
inline bool shaftResult(ShaftWindow* w, uint32_t nowMs, float* rpm) {
    uint32_t windowMs = (uint32_t)(nowMs - w->windowStartMs);
    bool ok = w->goodSamples > 0 && windowMs > 0 &&
              (uint64_t)w->coveredMs * 100u >= (uint64_t)windowMs * AS5600_MIN_COVERAGE_PCT &&
              w->coveredMs > 0;
    *rpm = ok ? (w->totalDeg / ((float)w->coveredMs / 1000.0f)) / 360.0f * 60.0f : 0.0f;
    shaftReset(w, nowMs);
    return ok;
}
