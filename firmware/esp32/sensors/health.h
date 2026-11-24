// health.h - one small table of sensor states for the whole hub.
// the read functions update it and the telemetry post reads it. it uses no Arduino
// types, so the same code builds on the host for the test in test_host/.
#pragma once

#include <stdint.h>

// the keys are fixed because the backend matches on these exact names.
enum SensorKey : uint8_t {
    SK_BME280 = 0,
    SK_MPU6050,
    SK_INA219,
    SK_MLX90614,
    SK_VL53L0X,
    SK_AS5600,
    SK_DS18B20,
    SK_MQ2,
    SK_LDR,
    SK_FC28,
    SK_MAX4466,
    SK_NANO_LINK,
    SK_STM32_LINK,
    SK_SUPPLY,
    // parts on the satellite boards, reported from their status bits.
    SK_NANO_BME280,
    SK_NANO_SUPPLY,
    SK_STM32_MPU6050,
    // the revised board's port expander and the seven rail inputs it reads. they are never set on
    // the present board, so they never appear in its faults map.
    SK_EXPANDER,
    SK_RAIL_AUX,
    SK_RAIL_FEED1,
    SK_RAIL_FEED2,
    SK_RAIL_FEED3,
    SK_RAIL_SENS,
    SK_RAIL_STRIP,
    SK_RAIL_ENABLE,
    SK_COUNT
};

// the states are fixed for the same reason. HS_OK is never posted.
enum HealthState : uint8_t {
    HS_OK = 0,
    HS_MISSING,
    HS_OUT_OF_RANGE,
    HS_WARMING_UP,
    HS_LINE_LOW,
    HS_SILENT,
    HS_UNPLUGGED,
    HS_STUCK,
    HS_GARBAGE,
    HS_ONE_WAY,
    HS_INTERMITTENT,
    // the node cannot say: nothing fresh has been read. the backend already accepts `stale`
    HS_STALE
};

const char* healthKeyName(SensorKey key);
// returns "ok" for HS_OK. callers leave that out of the faults map.
const char* healthStateName(HealthState state);

// healthInit puts every sensor in HS_OK with a since time of zero.
void healthInit();

HealthState healthState(SensorKey key);
// milliseconds since boot at which the sensor entered its current state.
uint32_t healthSince(SensorKey key);
// true when at least one sensor is in a fault state.
bool healthAnyFault();

// healthSet moves a sensor to a state and returns true when that was a change. the since
// time only moves on a change, so a fault that lasts keeps its start.
bool healthSet(SensorKey key, HealthState state, uint32_t nowMs);

// healthObserveAbsent records one probe. an absent result only becomes HS_MISSING after
// HEALTH_MISSING_CONFIRM in a row. any present result clears the run. it never clears
// HS_MISSING itself, because the caller has to set the sensor up again first. returns true
// when the sensor is now in HS_MISSING.
// three failed probes inside HEALTH_FLAP_WINDOW_MS that never reach three in a row make
// healthState() report HS_INTERMITTENT while the sensor's own state is HS_OK, so readings
// that come and go always come with a reason. call it on every probe, present or not,
// because the flap window is judged on each call.
bool healthObserveAbsent(SensorKey key, bool absent, uint32_t nowMs);

// ─── recovery of a sensor after a loss ───────────────────────────────────────
// one per I2C or 1-wire sensor. a sensor needs its set-up again after any lost probe.
// it also needs it when its content shows it has reset. tries are rate limited so a part that flaps
// cannot hold the loop with repeated set-up calls.
struct Recovery {
    bool     ready;       // set-up has worked and nothing has been lost since
    bool     tried;       // a set-up has been attempted at least once
    uint32_t lastTryMs;
    uint8_t  badPasses;   // passes in a row with bad content
};

void recoveryInit(Recovery* r);
// a probe failed, so whatever the sensor held is gone.
void recoveryNoteLost(Recovery* r);
// one pass of content. returns true when bad content has lasted `limit` passes, which also
// clears ready so the next probe runs the set-up. a good pass clears the run.
bool recoveryNoteContent(Recovery* r, bool bad, uint8_t limit);
// true when a set-up is wanted now and the last try was long enough ago.
bool recoveryMayTry(const Recovery* r, uint32_t nowMs, uint32_t minIntervalMs);
void recoveryNoteTry(Recovery* r, bool ok, uint32_t nowMs);

// ─── receive line watch for the two serial links ─────────────────────────────
// a rest-low line (cable out or far end unpowered) and a rest-high line that never
// carries a valid line need different advice, so the watch keeps both.
struct LinkWatch {
    uint32_t startMs;        // when the watch began, so silence is counted from boot
    bool     lowLatched;     // line_low was declared and the line has not moved since, so an alias of millis() cannot clear it
    bool     graceOver;      // the start-up window has passed. it stays set, so the 49.7 day millis() alias cannot reopen it
    uint32_t lastByteMs;     // last byte that was not noise
    uint32_t lastValidMs;    // last line that parsed
    uint32_t lowSinceMs;     // first low sample of the current run
    uint16_t lowSamples;     // low samples in the current run
    bool     lowRun;
    bool     haveValid;
};

void linkReset(LinkWatch* w, uint32_t nowMs);
// call it on a steady cadence (SERIAL_POLL_MS) with the level of the receive pin.
void linkNoteLevel(LinkWatch* w, bool high, uint32_t nowMs);
void linkNoteByte(LinkWatch* w, uint32_t nowMs);
void linkNoteValid(LinkWatch* w, uint32_t nowMs);
// nothing is reported (HS_OK) until the link has had silentMs since linkReset to produce a
// line, so a normal restart never raises a link fault. after that: HS_LINE_LOW when the line has rested low for lowMs with at least minSamples samples and
// no byte, HS_SILENT when no valid line has come for silentMs, otherwise HS_OK.
HealthState linkState(LinkWatch* w, uint32_t nowMs, uint32_t lowMs,
                      uint16_t minSamples, uint32_t silentMs);
