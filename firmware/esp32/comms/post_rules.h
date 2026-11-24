// post_rules.h - the pure rules around a post that need no Arduino types, so the host test
// covers them: the clock gate for TLS, what a response code means for the next attempt and the
// boot and sequence numbers that must never repeat or go backwards.
#pragma once

#include <stddef.h>
#include <stdint.h>

// ─── the clock gate ──────────────────────────────────────────────────────────
// the hub checks certificate dates against the clock (tls_checks.h), so a TLS post is not even tried until the clock is
// plausible. the post task owns the clock and asks SNTP for it. the main loop never does.
// the floor is the date this image was built (__DATE__, midnight UTC of that day or the build flag
// TIME_FLOOR_EPOCH). a clock earlier than the build is a clock that was never set. a hub flashed long
// after it was built has a floor that is only a lower bound, which is harmless: the floor never
// rejects a right clock and the certificate dates are what do the real work (see tls_checks.h). a
// network that can forge SNTP can still choose any time after the floor, which is a limit of SNTP and
// is written up in the README.
// "Nov 22 2026" (the day may be space padded) to seconds since 1970
constexpr int64_t buildMonth(const char* d) {
    return d[0] == 'J' ? (d[1] == 'a' ? 1 : (d[2] == 'n' ? 6 : 7))
         : d[0] == 'F' ? 2
         : d[0] == 'M' ? (d[2] == 'r' ? 3 : 5)
         : d[0] == 'A' ? (d[1] == 'p' ? 4 : 8)
         : d[0] == 'S' ? 9
         : d[0] == 'O' ? 10
         : d[0] == 'N' ? 11 : 12;
}
constexpr int64_t buildDay(const char* d) {
    return (d[4] == ' ' ? 0 : (d[4] - '0') * 10) + (d[5] - '0');
}
constexpr int64_t buildYear(const char* d) {
    return (d[7] - '0') * 1000 + (d[8] - '0') * 100 + (d[9] - '0') * 10 + (d[10] - '0');
}
// days since 1970 for a civil date (the standard days-from-civil algorithm, one expression per
// step because this has to be constexpr in C++11)
constexpr int64_t civilYear(int64_t y, int64_t m) { return m <= 2 ? y - 1 : y; }
constexpr int64_t civilEra(int64_t y) { return (y >= 0 ? y : y - 399) / 400; }
constexpr int64_t civilYoe(int64_t y) { return y - civilEra(y) * 400; }
constexpr int64_t civilDoe(int64_t y, int64_t m, int64_t d) {
    return civilYoe(civilYear(y, m)) * 365 + civilYoe(civilYear(y, m)) / 4 - civilYoe(civilYear(y, m)) / 100 +
           (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1;
}
constexpr int64_t daysFromCivil(int64_t y, int64_t m, int64_t d) {
    return civilEra(civilYear(y, m)) * 146097 + civilDoe(y, m, d) - 719468;
}
constexpr int64_t buildDateEpoch(const char* d) {
    return daysFromCivil(buildYear(d), buildMonth(d), buildDay(d)) * 86400;
}
#ifdef TIME_FLOOR_EPOCH
#define TIME_VALID_MIN_EPOCH   ((int64_t)(TIME_FLOOR_EPOCH))
#else
#define TIME_VALID_MIN_EPOCH   buildDateEpoch(__DATE__)
#endif
bool timeIsPlausible(uint32_t epochSeconds);

struct TimeGate {
    bool     synced;
    bool     running;        // a sync round is open
    uint32_t roundStartMs;
    uint32_t idleSinceMs;
    uint32_t retryMs;        // how long to stay idle before the next round
};
enum TimeAction : uint8_t {
    TG_NONE,
    TG_START,                // start a round: call configTime() now
    TG_SYNCED                // the clock became plausible on this call
};
void       tgInit(TimeGate* g, uint32_t nowMs);
// call often. epoch is the clock's seconds, 0 or a small number while it is unset. a round lasts
// TIME_SYNC_WINDOW_MS. when it ends with no plausible clock the gate stays idle for a wait that
// starts at TIME_RETRY_START_MS and doubles up to TIME_RETRY_MAX_MS, then opens another round.
TimeAction tgStep(TimeGate* g, uint32_t nowMs, uint32_t epoch);
// a TLS post may be tried only while this is true
bool       tgMayPostTls(const TimeGate* g);

// ─── what a response means ───────────────────────────────────────────────────
enum PostKind : uint8_t {
    PK_OK,
    PK_NETWORK,              // no status line at all
    PK_REDIRECT,             // 3xx: not followed, usually http:// pointed at a server that wants https://
    PK_AUTH,                 // 401 or 403: the key is wrong and retrying will not fix it
    PK_NOTFOUND,             // 404: the address is wrong. retrying will not fix it
    PK_CONFLICT,             // 409: the server has seen a newer (boot, seq) from this machine. only an admin accepting a new counter fixes it
    PK_THROTTLED,            // 429
    PK_REJECTED,             // another 4xx
    PK_SERVER                // 5xx and anything else
};
struct PostOutcome {
    PostKind kind;
    uint32_t waitMs;         // how long the gate stays closed after this response (0 for a success)
};
// backoffWaitMs is the wait the normal back-off would give. a 429 waits at least as long as the
// server's Retry-After (capped at POST_RETRY_AFTER_MAX_MS) and never less than the back-off. a 401
// or 403 or 409 waits POST_AUTH_RETRY_MS (ten minutes) and not the back-off
PostOutcome poClassify(int code, uint32_t retryAfterSeconds, uint32_t backoffWaitMs);
const char* poKindName(PostKind k);

// ─── the numbers the backend compares ────────────────────────────────────────
// the backend refuses a post whose (boot, seq) is not newer than the last. boot is a counter
// kept in non-volatile storage and raised once per boot. seq is a counter in RAM raised for every
// body built, so it restarts at 0 on each boot and the pair still only goes up. an exact repeat of
// the last accepted pair is answered 200 with status "duplicate", which is a delivery and needs no
// care here.
//
// what a read of the counter can say. the sketch asks the storage library directly, because a getter
// with a default returns 0 for a read error as well as for a counter that was never written
enum NvsRead : uint8_t { NVSR_OK, NVSR_NOT_FOUND, NVSR_ERROR };

class BootStore {
public:
    virtual ~BootStore() {}
    virtual NvsRead read(uint32_t* value) = 0;
    virtual bool    write(uint32_t value) = 0;       // set and commit
    // credentials are stored in flash. a hub that has them has booted before, so a missing counter
    // on such a hub means the counter was lost and not that this is the first boot
    virtual bool    credsStored() = 0;
};

enum BootResult : uint8_t {
    BOOT_OK,
    BOOT_READ_FAILED,        // the storage could not be read
    BOOT_LOST,               // no counter, but the hub has stored credentials: it would restart at 1
    BOOT_LIMIT,              // the counter is at its limit and would wrap
    BOOT_WRITE_FAILED,
    BOOT_READBACK_FAILED     // written, but it did not read back the same
};
// reads the counter, raises it, writes it and reads it back. *out is set only on BOOT_OK. on any
// other result the hub builds no bodies at all, because a boot that could repeat or go backwards
// would be refused or would replay. it sends no guessed boot. alarms, relays and the panel do not
// depend on it
BootResult  bootAdvance(BootStore& store, uint32_t* out);
const char* bootResultName(BootResult r);
// the next sequence number. false once the counter is at its limit (about 680 years at one body
// every 5 s). the hub then builds no more bodies until the next boot and never wraps
bool seqNext(uint32_t* seq);
