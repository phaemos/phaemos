// stuck_check.h - a part is called stuck when its raw data words repeat for a run of reads. no
// Arduino types, so the host test covers it. the run limit is BME_STUCK_READS.
#pragma once

#include <stdint.h>
#include <string.h>

struct StuckDetector {
    uint8_t last[8];
    uint8_t run;
    bool    have;
};

inline void stuckReset(StuckDetector* d) {
    memset(d, 0, sizeof *d);
}

// note one read of eight raw bytes. returns true once the same bytes have come `limit` times in a row.
inline bool stuckNote(StuckDetector* d, const uint8_t* bytes, uint8_t limit) {
    if (!d->have || memcmp(d->last, bytes, sizeof d->last) != 0) {
        memcpy(d->last, bytes, sizeof d->last);
        d->have = true;
        d->run = 1;
        return false;
    }
    if (d->run < 255) d->run++;
    return d->run >= limit;
}
