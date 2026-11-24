#include "post_queue.h"

#include <string.h>

void mbInit(Mailbox* m) {
    m->len = 0;
    m->full = false;
    m->replaced = 0;
    m->delivered = 0;
}

PutResult mbPut(Mailbox* m, const char* body, size_t len) {
    if (len >= sizeof m->data) return PUT_TOO_BIG;
    bool replaced = m->full;
    memcpy(m->data, body, len);
    m->data[len] = 0;
    m->len = len;
    m->full = true;
    if (replaced) {
        m->replaced++;
        return PUT_REPLACED;
    }
    return PUT_OK;
}

bool mbTake(Mailbox* m, char* out, size_t cap, size_t* len) {
    if (!m->full || m->len + 1 > cap) return false;
    memcpy(out, m->data, m->len + 1);
    *len = m->len;
    m->full = false;
    m->delivered++;
    return true;
}

void backoffInit(Backoff* b) {
    b->nextDelayMs = POST_BACKOFF_START_MS;
}

uint32_t backoffFailure(Backoff* b) {
    uint32_t wait = b->nextDelayMs;
    uint32_t next = wait * 2;
    b->nextDelayMs = next > POST_BACKOFF_MAX_MS ? (uint32_t)POST_BACKOFF_MAX_MS : next;
    return wait;
}

void backoffSuccess(Backoff* b) {
    b->nextDelayMs = POST_BACKOFF_START_MS;
}

void pgInit(PostGate* g) {
    g->backingOff = false;
    g->failedAtMs = 0;
    g->waitMs = 0;
}

bool pgMayPost(PostGate* g, uint32_t nowMs) {
    if (!g->backingOff) return true;
    if ((uint32_t)(nowMs - g->failedAtMs) >= g->waitMs) {
        g->backingOff = false;
        return true;
    }
    return false;
}

void pgFailed(PostGate* g, uint32_t nowMs, uint32_t waitMs) {
    g->backingOff = true;
    g->failedAtMs = nowMs;
    g->waitMs = waitMs;
}

void pgSuccess(PostGate* g) {
    g->backingOff = false;
}

void pfInit(PostFreshness* f, uint32_t nowMs) {
    f->okCount = 0;
    f->refMs = nowMs;
    f->stale = false;
}

bool pfUpdate(PostFreshness* f, uint32_t nowMs, uint32_t okCount, uint32_t limitMs) {
    if (okCount != f->okCount) {
        f->okCount = okCount;
        f->refMs = nowMs;
        f->stale = false;
    } else if (!f->stale && (uint32_t)(nowMs - f->refMs) >= limitMs) {
        f->stale = true;      // stays set until a success, whatever millis() does
    }
    return f->stale;
}

void pwInit(PostWatch* w, uint32_t nowMs) {
    w->pausedSince = 0;
    w->busySince = 0;
    w->beat = nowMs;
    w->busy = false;
    w->paused = false;
}

void pwBeat(PostWatch* w, uint32_t nowMs) {
    w->beat = nowMs;
}

void pwBusyStart(PostWatch* w, uint32_t nowMs) {
    // the start time goes in before the flag, so a reader that sees busy also sees its start
    w->busySince = nowMs;
    w->busy = true;
}

void pwBusyEnd(PostWatch* w, uint32_t nowMs) {
    w->busy = false;
    w->beat = nowMs;
}

void pwPause(PostWatch* w, bool paused, uint32_t nowMs) {
    if (paused) w->pausedSince = nowMs;
    w->paused = paused;
    w->beat = nowMs;
}

bool pwHealthy(const PostWatch* w, uint32_t nowMs, uint32_t busyLimitMs, uint32_t idleLimitMs) {
    // a download that hangs is not given for ever
    if (w->paused) return (uint32_t)(nowMs - w->pausedSince) <= POST_OTA_PAUSE_LIMIT_MS;
    if (w->busy) return (uint32_t)(nowMs - w->busySince) <= busyLimitMs;
    return (uint32_t)(nowMs - w->beat) <= idleLimitMs;
}
