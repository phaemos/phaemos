// saved_state.h - what survives a warm reset. the firmware keeps this in RTC memory that is
// not cleared by a watchdog, panic or software reset. the decisions here use no Arduino types,
// so the host test covers them.
//
// what it holds:
//   the per-source critical counts and latches and the commanded state of the four relays, so
//   the cooling relay is not left off for the length of a boot after a reset during an
//   over-temperature and a hub that resets after every second judgement still reaches three
//   the number of warm resets since a trusted temperature reading, whatever the relay was doing,
//   so a reset loop is seen as one (after RESTORE_MAX_UNCONFIRMED the hub stops restoring and
//   puts the cooling relay in its state for no information)
//   the sensor whose set-up is running and how many times a set-up has ended in a task watchdog
//   reset, so one sensor that stalls in its set-up costs one boot and not every boot. a strike
//   is forgiven once the sensor has completed a set-up and given good readings for a while
//   whether each link has delivered a checksummed line since power-up
//   whether the gas sensor's warm-up has completed since power-up
// what is not restored: anything after a cold power-up or a brown-out, when RTC memory is not
// trusted. the layout is versioned in the magic word, so a build with a different layout never
// reads an old record as valid.
#pragma once

#include <stdint.h>

#include "../config.h"
#include "temp_judge.h"

// bump this whenever SavedState changes. it is part of the magic word.
#define SAVED_STATE_LAYOUT 4
#define SAVED_STATE_MAGIC  (0x504D5300u | SAVED_STATE_LAYOUT)   // "PMS" and the layout

// the sensors whose set-up can stall
enum SetupId : uint8_t {
    SETUP_BME280 = 0,
    SETUP_MPU6050,
    SETUP_INA219,
    SETUP_VL53L0X,
    SETUP_MLX90614,
    SETUP_AS5600,
    SETUP_DS18B20,
    SETUP_COUNT
};

struct SavedState {
    uint32_t magic;
    uint8_t  relayMask;                 // bit n set means relay n+1 was commanded on
    uint8_t  linksSeen;                 // bit 0 Nano, bit 1 Black Pill
    uint8_t  unconfirmed;               // warm resets since a trusted temperature reading
    uint8_t  setupMarker;               // 0 or the SetupId of the set-up in progress plus 1
    uint8_t  strikes[SETUP_COUNT];      // set-ups that ended in a task watchdog reset
    uint8_t  critCount[TS_COUNT];       // per-source critical counts
    uint8_t  latchMask;                 // per-source critical latches
    uint8_t  gasWarmedUp;               // the MQ-2 warm-up has completed since power-up
    uint8_t  reserved[3];
    uint32_t check;
};

// writes the magic and the checksum.
void ssSeal(SavedState* s);
// true when the magic and the checksum are right and every field is in range.
bool ssValid(const SavedState* s);
// a zeroed, sealed record, for a cold start.
void ssReset(SavedState* s);

// esp_reset_reason() values (esp_system.h): SW 3, PANIC 4, INT_WDT 5, TASK_WDT 6, WDT 7 are
// warm. a power-on, brown-out, reset pin, deep sleep and unknown are not.
bool ssWarmResetReason(int espResetReason);
// the task watchdog is what a stalled set-up ends in
bool ssTaskWatchdogReason(int espResetReason);

enum RestoreVerdict : uint8_t {
    RV_NONE,      // a cold start or a damaged record: nothing to restore
    RV_RESTORE,   // a warm reset: put the relays and the counts back and hold them until a reading confirms them
    RV_REFUSE     // a reset loop: RESTORE_MAX_UNCONFIRMED warm resets without a trusted reading
};
RestoreVerdict ssRestoreVerdict(int espResetReason, const SavedState* s);
// a warm reset is being handled. counts it as one more without a trusted reading.
void ssNoteBoot(SavedState* s);
// a trusted temperature reading arrived. clears the count.
void ssNoteConfirmed(SavedState* s);
// the per-source state, as the judge holds it, goes into the record
void ssStoreJudge(SavedState* s, const TempJudge* j);
void ssLoadJudge(const SavedState* s, TempJudge* j);

// what to do with a restored cooling state on each judgement. a trusted reading hands it to the
// normal judgement (CONFIRMED). no trusted reading by the deadline drops it (DROP). until then
// it is held (WAIT).
enum RestoreStep : uint8_t {
    RESTORE_NONE,       // nothing was restored
    RESTORE_WAIT,
    RESTORE_CONFIRMED,
    RESTORE_DROP
};
RestoreStep ssRestoreStep(bool pending, bool goodReading, uint32_t nowMs, uint32_t deadlineMs);

// ─── set-up protection ───────────────────────────────────────────────────────
struct SetupVerdict {
    bool skipThisBoot[SETUP_COUNT];   // the set-up was running when the last task watchdog reset hit
    bool excluded[SETUP_COUNT];       // SETUP_MAX_STRIKES resets: out until the next power-up
};
// call once at boot. after a task watchdog reset with a valid record, the sensor named by the
// marker gets a strike and is skipped this boot. any other warm reset only clears the marker, so
// an unrelated panic or software reset that lands in a set-up costs nothing.
SetupVerdict ssSetupBootCheck(SavedState* s, int espResetReason);
// write the marker before a set-up call and clear it after.
void ssSetupBegin(SavedState* s, SetupId id);
void ssSetupEnd(SavedState* s);
bool ssSetupExcluded(const SavedState* s, SetupId id);
// a strike is forgiven when the set-up completed at doneMs and the sensor has given good readings
// since, for forgiveMs. the time is a difference, so the millis() wrap is safe.
bool ssStrikeForgiveDue(uint32_t doneMs, uint32_t nowMs, uint32_t forgiveMs);
// returns true when a strike was cleared
bool ssForgive(SavedState* s, SetupId id);
void ssNoteGasWarmed(SavedState* s);
