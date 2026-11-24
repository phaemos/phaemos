#include "temp_judge.h"

#include "../config.h"

namespace {

const float LIMIT[TS_COUNT] = {
    (float)TEMP_CRITICAL_C, (float)TEMP_CRITICAL_DS18_C, (float)TEMP_CRITICAL_MLX_C
};

}  // namespace

void tjInit(TempJudge* j) {
    for (uint8_t i = 0; i < TS_COUNT; i++) {
        j->count[i] = 0;
        j->latch[i] = false;
    }
    j->warnActive = false;
}

void tjClear(TempJudge* j) {
    tjInit(j);
}

TempVerdict tjStep(TempJudge* j, const TempInputs& in) {
    TempVerdict v;
    v.evidence = false;
    bool bmeSeen = in.bme.trusted || in.bmeOverRange;
    v.anyTrusted = bmeSeen || in.ds.trusted || in.mlx.trusted;
    v.alarmUnavailable = !v.anyTrusted;

    bool trusted[TS_COUNT] = { bmeSeen, in.ds.trusted, in.mlx.trusted };
    float temp[TS_COUNT]   = { in.bme.tempC, in.ds.tempC, in.mlx.tempC };
    // an over-range BME280 reading is over its threshold by definition
    bool over[TS_COUNT] = {
        in.bmeOverRange || (in.bme.trusted && in.bme.tempC > LIMIT[TS_BME]),
        in.ds.trusted  && in.ds.tempC  > LIMIT[TS_DS],
        in.mlx.trusted && in.mlx.tempC > LIMIT[TS_MLX]
    };

    for (uint8_t i = 0; i < TS_COUNT; i++) {
        // a source that is not trusted on this pass neither raises nor clears anything
        if (!trusted[i]) continue;
        if (over[i]) {
            v.evidence = true;
            if (j->count[i] < 255) j->count[i]++;
            if (j->count[i] >= CRITICAL_CONFIRM_READINGS) j->latch[i] = true;
        } else {
            // only this source's own trusted reading under its threshold lowers its count
            j->count[i] = 0;
            // and only its own reading below the threshold less the hysteresis clears its latch
            bool clearReading = !(i == TS_BME && in.bmeOverRange) &&
                                temp[i] < LIMIT[i] - (float)TEMP_HYSTERESIS_C;
            if (j->latch[i] && clearReading) j->latch[i] = false;
        }
    }

    // the warning follows the BME280 alone. a hot surface seen by the infrared spot or the
    // contact probe is not by itself a warning
    if (in.bmeOverRange) {
        j->warnActive = true;
    } else if (in.bme.trusted) {
        float t = in.bme.tempC;
        j->warnActive = j->warnActive ? (t > (float)TEMP_WARNING_C - (float)TEMP_HYSTERESIS_C)
                                      : (t > (float)TEMP_WARNING_C);
    } else {
        j->warnActive = false;
    }

    v.critActive = j->latch[0] || j->latch[1] || j->latch[2];
    v.warnActive = j->warnActive;
    return v;
}

bool tjPending(const TempJudge* j) {
    for (uint8_t i = 0; i < TS_COUNT; i++) {
        if (j->count[i] > 0 || j->latch[i]) return true;
    }
    return false;
}

uint8_t tjLatchMask(const TempJudge* j) {
    uint8_t m = 0;
    for (uint8_t i = 0; i < TS_COUNT; i++) {
        if (j->latch[i]) m |= (uint8_t)(1u << i);
    }
    return m;
}

void tjRestore(TempJudge* j, const uint8_t counts[TS_COUNT], uint8_t latchMask) {
    for (uint8_t i = 0; i < TS_COUNT; i++) {
        j->count[i] = counts[i];
        j->latch[i] = (latchMask & (1u << i)) != 0;
    }
    j->warnActive = false;
}
