// analog_checks.h - pure decisions about analogue readings. header only and free of
// Arduino types, so the host test in test_host/ can include it unchanged.
#pragma once

#include <stdint.h>

#include "../config.h"
#include "health.h"

// microphone: judged on the mean of the samples and not on the swing, because a quiet room
// gives a tiny swing from a working module too.
inline HealthState micState(float meanCounts) {
    if (meanCounts <= MIC_UNPLUGGED_MAX_COUNTS) return HS_UNPLUGGED;
    if (meanCounts >= MIC_RAIL_MIN_COUNTS)      return HS_OUT_OF_RANGE;
    return HS_OK;
}

// the water alarm. without the series resistor any reading under WATER_THRESHOLD raises it,
// zero included, because an unplugged input and a flooded probe cannot be told apart and a
// missed leak is worse than a false one. with the series resistor (HAS_PROBE_SERIES_R) a
// reading at or under PROBE_UNPLUGGED_MAX_COUNTS is an unplugged probe and never an alarm.
// only a real flood (above that and under the threshold) raises it.
inline bool waterAlarm(float counts) {
#if HAS_PROBE_SERIES_R
    return counts > PROBE_UNPLUGGED_MAX_COUNTS && counts < WATER_THRESHOLD;
#else
    return counts < WATER_THRESHOLD;
#endif
}

// the band an unplugged probe reads in
#if HAS_PROBE_SERIES_R
#define MOISTURE_UNPLUGGED_BAND PROBE_UNPLUGGED_MAX_COUNTS
#else
#define MOISTURE_UNPLUGGED_BAND MOISTURE_UNPLUGGED_MAX_COUNTS
#endif

// moisture: only the low end can be a fault. only after MOISTURE_UNPLUGGED_PASSES passes
// in a row, so one dip from a flooded probe is not named. a dry probe reads high on purpose.
// the run length is kept by the caller. this says nothing about the water alarm (see waterAlarm).
inline HealthState moistureState(float counts, uint8_t* lowPasses) {
    if (counts <= MOISTURE_UNPLUGGED_BAND) {
        if (*lowPasses < 255) (*lowPasses)++;
    } else {
        *lowPasses = 0;
    }
    return *lowPasses >= MOISTURE_UNPLUGGED_PASSES ? HS_UNPLUGGED : HS_OK;
}

// MQ-2 after its warm-up: an analogue reading near zero is a fault (a dead 5 V rail or an
// unplugged module) whatever the digital line says. the digital line is pulled up by the board,
// so an unplugged module reads high and would otherwise look like clean air.
inline bool mq2ReadingIsFault(int rawCounts) {
    return rawCounts < MQ2_FAULT_ADC_MAX;
}

// the gas judgement after the warm-up, from both paths. either path raises the alarm: the
// digital output (the module's comparator, set by its potentiometer) or the analogue level over
// GAS_ANALOGUE_ALARM_COUNTS. a reading near zero is a fault and raises nothing. a digital alarm with
// the analogue level inside the clean-air band is a disagreement between the two paths and is
// reported as a fault, while the alarm is still raised (the safe side).
struct GasJudgement {
    bool alarm;
    bool fault;           // the analogue reading is near zero
    bool disagree;        // the digital line alarms but the analogue level reads clean air
    bool digitalAlarm;
    bool analogueAlarm;
};

inline GasJudgement gasJudge(int rawCounts, bool digitalLow) {
    GasJudgement g;
    g.fault = mq2ReadingIsFault(rawCounts);
    g.digitalAlarm = digitalLow && !g.fault;
    g.analogueAlarm = !g.fault && rawCounts >= GAS_ANALOGUE_ALARM_COUNTS;
    g.alarm = g.digitalAlarm || g.analogueAlarm;
    g.disagree = g.digitalAlarm && rawCounts <= MQ2_CLEAN_AIR_MAX_COUNTS;
    return g;
}

// the LDR has no fault band. a bright LDR already reads full scale, so a short to 3.3 V
// cannot be told from bright light. zero is darkness.

// pin millivolts to the volts at the 12 V input. the divider is 100 kohm over 10 kohm.
inline float inputVoltsFromPinMilliVolts(float pinMv) {
    const float factor = (float)(INPUT_DIVIDER_TOP_OHM + INPUT_DIVIDER_BOTTOM_OHM)
                       / (float)INPUT_DIVIDER_BOTTOM_OHM;
    return pinMv * factor / 1000.0f;
}

inline HealthState supplyState(float volts) {
    return (volts < SUPPLY_MIN_V || volts > SUPPLY_MAX_V) ? HS_OUT_OF_RANGE : HS_OK;
}
