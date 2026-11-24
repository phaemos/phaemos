#include "health.h"

#include "../config.h"

namespace {

struct Entry {
    HealthState state;
    uint32_t    since;
    uint8_t     misses;
    // the last three failed probes, for the flap rule
    uint32_t    failTimes[3];
    uint8_t     failCount;
    uint8_t     failIdx;
    bool        flapping;
    uint32_t    flapSince;
};

Entry s_table[SK_COUNT];

const char* const KEY_NAMES[SK_COUNT] = {
    "bme280", "mpu6050", "ina219", "mlx90614", "vl53l0x", "as5600", "ds18b20",
    "mq2", "ldr", "fc28", "max4466", "nano_link", "stm32_link", "supply",
    "nano_bme280", "nano_supply", "stm32_mpu6050",
    "expander", "aux_rail", "feed1_rail", "feed2_rail", "feed3_rail", "sens_rail", "strip_rail",
    "enable_rail"
};

}  // namespace

const char* healthKeyName(SensorKey key) {
    return key < SK_COUNT ? KEY_NAMES[key] : "unknown";
}

const char* healthStateName(HealthState state) {
    switch (state) {
        case HS_OK:           return "ok";
        case HS_MISSING:      return "missing";
        case HS_OUT_OF_RANGE: return "out_of_range";
        case HS_WARMING_UP:   return "warming_up";
        case HS_LINE_LOW:     return "line_low";
        case HS_SILENT:       return "silent";
        case HS_UNPLUGGED:    return "unplugged";
        case HS_STUCK:        return "stuck";
        case HS_GARBAGE:      return "garbage";
        case HS_ONE_WAY:      return "one_way";
        case HS_INTERMITTENT: return "intermittent";
        case HS_STALE:        return "stale";
    }
    return "unknown";
}

void healthInit() {
    for (uint8_t i = 0; i < SK_COUNT; i++) {
        s_table[i].state  = HS_OK;
        s_table[i].since  = 0;
        s_table[i].misses = 0;
        s_table[i].failCount = 0;
        s_table[i].failIdx   = 0;
        s_table[i].flapping  = false;
        s_table[i].flapSince = 0;
    }
}

HealthState healthState(SensorKey key) {
    if (key >= SK_COUNT) return HS_OK;
    // the flap overlay only speaks when the sensor's own state has nothing to say.
    if (s_table[key].state == HS_OK && s_table[key].flapping) return HS_INTERMITTENT;
    return s_table[key].state;
}

uint32_t healthSince(SensorKey key) {
    if (key >= SK_COUNT) return 0;
    if (s_table[key].state == HS_OK && s_table[key].flapping) return s_table[key].flapSince;
    return s_table[key].since;
}

bool healthAnyFault() {
    for (uint8_t i = 0; i < SK_COUNT; i++) {
        if (healthState((SensorKey)i) != HS_OK) return true;
    }
    return false;
}

bool healthSet(SensorKey key, HealthState state, uint32_t nowMs) {
    if (key >= SK_COUNT || s_table[key].state == state) return false;
    s_table[key].state = state;
    s_table[key].since = nowMs;
    return true;
}

bool healthObserveAbsent(SensorKey key, bool absent, uint32_t nowMs) {
    if (key >= SK_COUNT) return false;
    Entry& e = s_table[key];
    // forget failures that are older than the window. this keeps a stale entry from ever being
    // compared again, so the 49.7 day millis() alias cannot make three old failures look recent.
    while (e.failCount > 0 &&
           (uint32_t)(nowMs - e.failTimes[(e.failIdx + 3 - e.failCount) % 3]) > HEALTH_FLAP_WINDOW_MS) {
        e.failCount--;
    }
    if (absent) {
        e.failTimes[e.failIdx] = nowMs;
        e.failIdx = (uint8_t)((e.failIdx + 1) % 3);
        if (e.failCount < 3) e.failCount++;
    }
    // three failures inside the window, judged on every call so it also expires.
    bool flap = e.failCount >= 3 &&
                (uint32_t)(nowMs - e.failTimes[e.failIdx]) <= HEALTH_FLAP_WINDOW_MS;
    if (flap && !e.flapping) e.flapSince = nowMs;
    e.flapping = flap;

    if (!absent) {
        e.misses = 0;
        return e.state == HS_MISSING;
    }
    // saturate so a long outage cannot wrap the counter back to zero.
    if (e.misses < 255) e.misses++;
    if (e.misses >= HEALTH_MISSING_CONFIRM) healthSet(key, HS_MISSING, nowMs);
    return e.state == HS_MISSING;
}

void recoveryInit(Recovery* r) {
    r->ready     = false;
    r->tried     = false;
    r->lastTryMs = 0;
    r->badPasses = 0;
}

void recoveryNoteLost(Recovery* r) {
    r->ready     = false;
    r->badPasses = 0;
}

bool recoveryNoteContent(Recovery* r, bool bad, uint8_t limit) {
    if (!bad) {
        r->badPasses = 0;
        return false;
    }
    if (r->badPasses < 255) r->badPasses++;
    if (r->badPasses >= limit) {
        r->ready     = false;
        r->badPasses = 0;
        return true;
    }
    return false;
}

bool recoveryMayTry(const Recovery* r, uint32_t nowMs, uint32_t minIntervalMs) {
    if (r->ready) return false;
    return !r->tried || (uint32_t)(nowMs - r->lastTryMs) >= minIntervalMs;
}

void recoveryNoteTry(Recovery* r, bool ok, uint32_t nowMs) {
    r->tried     = true;
    r->lastTryMs = nowMs;
    r->ready     = ok;
    r->badPasses = 0;
}

void linkReset(LinkWatch* w, uint32_t nowMs) {
    w->startMs     = nowMs;
    w->graceOver   = false;
    w->lowLatched  = false;
    w->lastByteMs  = nowMs;
    w->lastValidMs = nowMs;
    w->lowSinceMs  = 0;
    w->lowSamples  = 0;
    w->lowRun      = false;
    w->haveValid   = false;
}

void linkNoteLevel(LinkWatch* w, bool high, uint32_t nowMs) {
    if (high) {
        w->lowRun     = false;
        w->lowSamples = 0;
        return;
    }
    if (!w->lowRun) {
        w->lowRun     = true;
        w->lowSinceMs = nowMs;
        w->lowSamples = 0;
    }
    if (w->lowSamples < 65535) w->lowSamples++;
}

void linkNoteByte(LinkWatch* w, uint32_t nowMs) {
    w->lastByteMs = nowMs;
    // a byte ends any low run, so a line that carries data is never called low.
    w->lowRun     = false;
    w->lowSamples = 0;
}

void linkNoteValid(LinkWatch* w, uint32_t nowMs) {
    w->lastValidMs = nowMs;
    w->haveValid   = true;
}

HealthState linkState(LinkWatch* w, uint32_t nowMs, uint32_t lowMs,
                      uint16_t minSamples, uint32_t silentMs) {
    // unsigned subtraction keeps these correct across a millis() rollover.
    // give the link its full silent window since boot before saying anything about it. once
    // the window has passed the flag stays set, so a millis() alias 49.7 days on cannot
    // reopen it and make a dead low line read ok for 15 s.
    if (!w->graceOver) {
        if ((uint32_t)(nowMs - w->startMs) < silentMs) return HS_OK;
        w->graceOver = true;
    }
    // a declared line_low holds for as long as the low run does. a byte or a high sample ends the run.
    if (w->lowLatched) {
        if (w->lowRun) return HS_LINE_LOW;
        w->lowLatched = false;
    }
    if (w->lowRun && w->lowSamples >= minSamples &&
        (uint32_t)(nowMs - w->lowSinceMs) >= lowMs &&
        (uint32_t)(nowMs - w->lastByteMs) >= lowMs) {
        w->lowLatched = true;
        return HS_LINE_LOW;
    }
    if ((uint32_t)(nowMs - w->lastValidMs) >= silentMs) return HS_SILENT;
    return HS_OK;
}
