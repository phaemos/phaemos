// post_queue.h - the pure parts of the post task: the one-slot mailbox that always holds the
// newest body, the back-off after a failed post and the watch the main loop keeps on the post
// task. no Arduino or FreeRTOS types, so the host test covers them. the firmware wraps the
// mailbox in a mutex.
#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>

#include "../config.h"

// ─── one-slot mailbox ────────────────────────────────────────────────────────
struct Mailbox {
    char     data[TELEMETRY_BODY_MAX_BYTES];
    size_t   len;
    bool     full;
    uint32_t replaced;     // unsent bodies pushed out by a newer one
    uint32_t delivered;    // bodies handed to the post task
};

enum PutResult : uint8_t {
    PUT_OK,         // the slot was empty
    PUT_REPLACED,   // an older unsent body was replaced and counted
    PUT_TOO_BIG     // the body does not fit and nothing changed
};

void      mbInit(Mailbox* m);
PutResult mbPut(Mailbox* m, const char* body, size_t len);
// takes the body out and empties the slot. false when there is nothing to take or `cap` is too small.
bool      mbTake(Mailbox* m, char* out, size_t cap, size_t* len);

// ─── back-off ────────────────────────────────────────────────────────────────
struct Backoff {
    uint32_t nextDelayMs;
};

void     backoffInit(Backoff* b);
// returns how long to wait after this failure. it starts at POST_BACKOFF_START_MS, doubles
// on each further failure and stops at POST_BACKOFF_MAX_MS.
uint32_t backoffFailure(Backoff* b);
void     backoffSuccess(Backoff* b);

// ─── post schedule ───────────────────────────────────────────────────────────
// the gate is closed only while a back-off is pending. the old schedule kept a stored time of
// the next attempt and compared it with a signed difference. that turns false once millis() is
// 2^31 ms (24.9 days) past the stored value, so a hub with no failed post for 24.9 days stopped
// posting for the next 24.9 days. the gate now stores when the failure happened and how long to
// wait and compares an unsigned elapsed time. the post task also asks it on every pass, even while
// Wi-Fi is down, so a pending back-off clears as soon as its wait has passed and is never left to
// age. a back-off lasts at most POST_BACKOFF_MAX_MS.
struct PostGate {
    bool     backingOff;
    uint32_t failedAtMs;
    uint32_t waitMs;
};

void pgInit(PostGate* g);
bool pgMayPost(PostGate* g, uint32_t nowMs);
void pgFailed(PostGate* g, uint32_t nowMs, uint32_t waitMs);
void pgSuccess(PostGate* g);

// ─── how long since a post succeeded ─────────────────────────────────────────
// kept by the main loop, from the post task's success counter. stale means no post has
// succeeded for limitMs (counted from boot until the first one). it stays set until a success.
struct PostFreshness {
    uint32_t okCount;
    uint32_t refMs;
    bool     stale;
};

void pfInit(PostFreshness* f, uint32_t nowMs);
// call it every reading with the success counter. returns true while stale.
bool pfUpdate(PostFreshness* f, uint32_t nowMs, uint32_t okCount, uint32_t limitMs);

// ─── watch on the post task ──────────────────────────────────────────────────
// written by the post task and read by the main loop, so every field is atomic.
struct PostWatch {
    std::atomic<uint32_t> busySince;
    std::atomic<uint32_t> beat;
    std::atomic<bool>     busy;
    std::atomic<bool>     paused;    // supervision is suspended, for an OTA download
    std::atomic<uint32_t> pausedSince;
};

void pwInit(PostWatch* w, uint32_t nowMs);
void pwBeat(PostWatch* w, uint32_t nowMs);
void pwBusyStart(PostWatch* w, uint32_t nowMs);
void pwBusyEnd(PostWatch* w, uint32_t nowMs);
void pwPause(PostWatch* w, bool paused, uint32_t nowMs);
// healthy while it is paused (for at most POST_OTA_PAUSE_LIMIT_MS), not busy for longer than busyLimitMs and (when idle) has beaten
// within idleLimitMs. the main loop feeds the task watchdog only while this is true.
bool pwHealthy(const PostWatch* w, uint32_t nowMs, uint32_t busyLimitMs, uint32_t idleLimitMs);
