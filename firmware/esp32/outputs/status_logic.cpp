#include "status_logic.h"

#include <string.h>

namespace {

const size_t MAX_FAULT_TEXT = 17;   // the display row is "STATUS: " plus this

const char* word(StatusKind k) {
    switch (k) {
        case STK_NORMAL:   return "NORMAL";
        case STK_WARNING:  return "WARNING";
        case STK_CRITICAL: return "CRITICAL";
        case STK_FAULT:    return "FAULT";
    }
    return "UNKNOWN";
}

void faultText(const StatusInput& in, char* out, size_t cap) {
    // short codes, most important first, so the whole list fits the display row when it can.
    // LOOP a reset loop, NOTMP no trusted temperature source (the over-temperature alarm is not
    // available), MQ-2 the gas sensor is faulted, WARM the gas alarm is warming up, TEMP the
    // BME280 is lost, PRB the moisture probe is unplugged, BRD the board check failed, PLN plain HTTP bench mode, CTR the server refused the boot counter, NET no
    // post has succeeded for POST_STALE_MS, SENS any other sensor or link is in a fault state.
    // TEMP is left out when NOTMP is shown, because NOTMP already says the temperature is lost.
    const char* names[11] = { "LOOP", "NOTMP", "MQ-2", "WARM", "TEMP", "PRB", "BRD", "PLN", "CTR", "NET", "SENS" };
    bool on[11] = { in.resetLoop, in.noTemp, in.gasFault, in.gasWarm, in.tempFault && !in.noTemp,
                   in.probeFault, in.boardFault, in.plainHttp, in.counterRejected, in.postFault, in.otherFault };
    size_t limit = cap - 1 < MAX_FAULT_TEXT ? cap - 1 : MAX_FAULT_TEXT;
    strcpy(out, "FAULT:");
    size_t len = strlen(out);
    int left = 0;
    for (int i = 0; i < 11; i++) left += on[i] ? 1 : 0;
    bool more = false;
    for (int i = 0; i < 11; i++) {
        if (!on[i]) continue;
        left--;
        size_t need = 1 + strlen(names[i]);
        // whole names only. when more are waiting, keep one character for the +
        if (len + need + (left > 0 ? 1 : 0) <= limit) {
            out[len++] = ' ';
            strcpy(out + len, names[i]);
            len += strlen(names[i]);
        } else {
            more = true;
            break;
        }
    }
    if (more) {
        out[len++] = '+';
        out[len] = 0;
    }
}

}  // namespace

StatusResult decideStatus(const StatusInput& in, bool altPhase) {
    StatusResult r;
    bool anyFault = in.tempFault || in.gasFault || in.gasWarm || in.probeFault || in.noTemp ||
                    in.boardFault || in.resetLoop || in.otherFault || in.postFault || in.plainHttp || in.counterRejected;
    bool anyWarn  = in.warnActive || in.gasAlert || in.waterAlert;

    if (in.critActive)      r.base = STK_CRITICAL;
    else if (anyWarn)       r.base = STK_WARNING;
    else if (anyFault)      r.base = STK_FAULT;
    else                    r.base = STK_NORMAL;

    r.both  = (r.base == STK_WARNING && anyFault);
    r.shown = r.both ? (altPhase ? STK_FAULT : STK_WARNING) : r.base;

    if (r.shown == STK_FAULT) faultText(in, r.text, sizeof r.text);
    else                      strcpy(r.text, word(r.shown));
    return r;
}
