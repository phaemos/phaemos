#include "post_rules.h"

#include "../config.h"

bool timeIsPlausible(uint32_t epochSeconds) {
    return (int64_t)epochSeconds >= TIME_VALID_MIN_EPOCH;
}

void tgInit(TimeGate* g, uint32_t nowMs) {
    g->synced = false;
    g->running = false;
    g->roundStartMs = 0;
    g->idleSinceMs = nowMs;
    g->retryMs = 0;
}

TimeAction tgStep(TimeGate* g, uint32_t nowMs, uint32_t epoch) {
    bool ok = timeIsPlausible(epoch);
    if (g->synced) {
        // a clock that falls back to an unset value is not trusted. open a new round at once
        if (!ok) {
            g->synced = false;
            g->running = false;
            g->idleSinceMs = nowMs;
            g->retryMs = 0;
        }
        return TG_NONE;
    }
    if (g->running) {
        if (ok) {
            g->synced = true;
            g->running = false;
            g->retryMs = 0;
            return TG_SYNCED;
        }
        if ((uint32_t)(nowMs - g->roundStartMs) >= TIME_SYNC_WINDOW_MS) {
            g->running = false;
            g->idleSinceMs = nowMs;
            uint32_t next = g->retryMs == 0 ? TIME_RETRY_START_MS : g->retryMs * 2;
            g->retryMs = next > TIME_RETRY_MAX_MS ? (uint32_t)TIME_RETRY_MAX_MS : next;
        }
        return TG_NONE;
    }
    // idle. a clock that is already right (set by an earlier round or by the core) needs no round
    if (ok) {
        g->synced = true;
        g->retryMs = 0;
        return TG_SYNCED;
    }
    if ((uint32_t)(nowMs - g->idleSinceMs) >= g->retryMs) {
        g->running = true;
        g->roundStartMs = nowMs;
        return TG_START;
    }
    return TG_NONE;
}

bool tgMayPostTls(const TimeGate* g) {
    return g->synced;
}

PostOutcome poClassify(int code, uint32_t retryAfterSeconds, uint32_t backoffWaitMs) {
    PostOutcome o;
    o.waitMs = backoffWaitMs;
    if (code >= 200 && code < 300) {
        o.kind = PK_OK;
        o.waitMs = 0;
    } else if (code < 0) {
        o.kind = PK_NETWORK;
    } else if (code >= 300 && code < 400) {
        o.kind = PK_REDIRECT;
    } else if (code == 401 || code == 403) {
        o.kind = PK_AUTH;
        o.waitMs = POST_AUTH_RETRY_MS;
    } else if (code == 404) {
        // the path does not exist on the server (a trailing slash, a wrong path or the wrong host). that is a
        // configuration fault, so it is retried as slowly as a rejected key
        o.kind = PK_NOTFOUND;
        o.waitMs = POST_AUTH_RETRY_MS;
    } else if (code == 409) {
        // the server holds a newer counter for this machine. retrying cannot fix that, only an admin
        // accepting a new counter can, so it is retried as slowly as a rejected key
        o.kind = PK_CONFLICT;
        o.waitMs = POST_AUTH_RETRY_MS;
    } else if (code == 429) {
        o.kind = PK_THROTTLED;
        uint64_t ra = (uint64_t)retryAfterSeconds * 1000ull;
        if (ra > POST_RETRY_AFTER_MAX_MS) ra = POST_RETRY_AFTER_MAX_MS;
        if (ra > o.waitMs) o.waitMs = (uint32_t)ra;
    } else if (code >= 400 && code < 500) {
        o.kind = PK_REJECTED;
    } else {
        o.kind = PK_SERVER;
    }
    return o;
}

const char* poKindName(PostKind k) {
    switch (k) {
        case PK_OK:        return "ok";
        case PK_NETWORK:   return "no response";
        case PK_REDIRECT:  return "redirect not followed";
        case PK_AUTH:      return "key rejected";
        case PK_NOTFOUND:  return "address not found";
        case PK_CONFLICT:  return "counter refused";
        case PK_THROTTLED: return "throttled";
        case PK_REJECTED:  return "rejected";
        default:           return "server error";
    }
}

BootResult bootAdvance(BootStore& store, uint32_t* out) {
    uint32_t stored = 0;
    NvsRead r = store.read(&stored);
    if (r == NVSR_ERROR) return BOOT_READ_FAILED;
    if (r == NVSR_NOT_FOUND) {
        // a counter that was never written is the first boot. on a hub that already holds stored
        // credentials it is a lost counter and a boot that restarts at 1 would be refused by the
        // server for ever
        if (store.credsStored()) return BOOT_LOST;
        stored = 0;
    }
    if (stored == 0xFFFFFFFFu) return BOOT_LIMIT;
    uint32_t next = stored + 1;
    if (!store.write(next)) return BOOT_WRITE_FAILED;
    uint32_t back = 0;
    if (store.read(&back) != NVSR_OK || back != next) return BOOT_READBACK_FAILED;
    *out = next;
    return BOOT_OK;
}

const char* bootResultName(BootResult r) {
    switch (r) {
        case BOOT_OK:              return "ok";
        case BOOT_READ_FAILED:     return "the boot counter could not be read";
        case BOOT_LOST:            return "the boot counter is missing on a hub that has stored credentials";
        case BOOT_LIMIT:           return "the boot counter is at its limit";
        case BOOT_WRITE_FAILED:    return "the boot counter could not be written";
        default:                   return "the boot counter did not read back after the write";
    }
}

bool seqNext(uint32_t* seq) {
    if (*seq == 0xFFFFFFFFu) return false;
    (*seq)++;
    return true;
}
