// temp_judge.h - judges the over-temperature state from every temperature source the hub has.
// no Arduino types, so the host test covers every combination. each source is judged on its own,
// because one critical count and one latch for all of them let a healthy cool sensor cancel a hot
// one. the rules:
//   each source has its own count and its own latch
//   a source's count goes up on its own trusted reading over its threshold and is lowered only by
//   its own trusted reading under it. a source that is not trusted on a pass changes nothing
//   a latch is set when its count reaches CRITICAL_CONFIRM_READINGS
//   a latch is cleared only by that source's own trusted reading below its threshold less
//   TEMP_HYSTERESIS_C. a reading past the junk limit is not trusted, so it clears nothing
//   critical is any latch set
//   a BME280 reading above its range from a part that passes its register checks counts as
//   over-temperature for the BME280's count and latch, as well as being reported out_of_range
//   when no source is trusted at all the over-temperature alarm is unavailable and the panel
//   says so. a count or a latch is held across any length of untrusted passes
#pragma once

#include <stdint.h>

enum TempSrc : uint8_t {
    TS_BME = 0,
    TS_DS,
    TS_MLX,
    TS_COUNT
};

struct TempSource {
    bool  trusted;
    float tempC;
};

struct TempInputs {
    TempSource bme;
    bool       bmeOverRange;   // a reading above BME_TEMP_MAX_C from a part that passed its register
                               // checks. it is evidence of over-temperature
    TempSource ds;
    TempSource mlx;
};

struct TempJudge {
    uint8_t count[TS_COUNT];
    bool    latch[TS_COUNT];
    bool    warnActive;
};

struct TempVerdict {
    bool critActive;           // any latch is set
    bool warnActive;
    bool anyTrusted;           // at least one source gave a trusted reading this pass
    bool alarmUnavailable;     // no trusted source: the over-temperature alarm is not available
    bool evidence;             // a source was over its threshold on this pass
};

void        tjInit(TempJudge* j);
TempVerdict tjStep(TempJudge* j, const TempInputs& in);
// any count above zero (a confirmation is under way) or any latch set
bool        tjPending(const TempJudge* j);
// the latches as a bit mask, for the saved state and back
uint8_t     tjLatchMask(const TempJudge* j);
void        tjRestore(TempJudge* j, const uint8_t counts[TS_COUNT], uint8_t latchMask);
void        tjClear(TempJudge* j);
