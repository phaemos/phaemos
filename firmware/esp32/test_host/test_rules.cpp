// test_rules.cpp - host test of comms/post_rules.cpp: the clock gate for TLS posts, what each
// response code means for the next attempt (a 429's Retry-After, a 401 that must not be retried
// once a minute for ever) and the boot and sequence numbers that must never repeat or go backwards.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_rules.cpp ../comms/post_rules.cpp ../comms/post_queue.cpp -o "${TMPDIR:-/tmp}/test_rules" && "${TMPDIR:-/tmp}/test_rules"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_rules.cpp ../comms/post_rules.cpp ../comms/post_queue.cpp -o "${TMPDIR:-/tmp}/test_rules_san" && "${TMPDIR:-/tmp}/test_rules_san"

#include <cstdio>
#include <cstdint>
#include <ctime>
#include <set>
#include <utility>

#include "../comms/post_queue.h"
#include "../comms/post_rules.h"
#include "../config.h"

static int g_checks = 0;
static int g_failed = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        g_checks++;                                                          \
        if (!(cond)) {                                                       \
            g_failed++;                                                      \
            std::printf("FAIL line %d: %s\n", __LINE__, #cond);              \
        }                                                                    \
    } while (0)

static void testPlausible() {
    CHECK(!timeIsPlausible(0));
    CHECK(!timeIsPlausible(1));
    CHECK(!timeIsPlausible(86400));                      // a clock that restarted at 1970
    CHECK(!timeIsPlausible((uint32_t)(TIME_VALID_MIN_EPOCH - 1)));
    CHECK(timeIsPlausible((uint32_t)TIME_VALID_MIN_EPOCH));
    CHECK(timeIsPlausible(4000000000u));
    // the floor is the build date: midnight UTC of the day this file was compiled, so it is not in the
    // future and not more than a day behind the clock of the machine that built it
    CHECK(TIME_VALID_MIN_EPOCH <= (int64_t)time(nullptr));
    CHECK(TIME_VALID_MIN_EPOCH % 86400 == 0);
    // the parser, against known dates
    static_assert(buildDateEpoch("Jan  1 1970") == 0, "epoch");
    static_assert(buildDateEpoch("Jan  1 2026") == 1767225600LL, "2026");
    static_assert(buildDateEpoch("Feb 29 2028") == 1835395200LL, "leap day");
    static_assert(buildDateEpoch("Dec 31 1999") == 946598400LL, "end of 1999");
    static_assert(buildDateEpoch("Nov 22 2026") == 1795305600LL, "today");
    static_assert(buildDateEpoch("Mar  5 2030") == 1898899200LL, "a padded day");
    const char* months[12] = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
    for (int m = 1; m <= 12; m++) {
        char buf[16];
        std::snprintf(buf, sizeof buf, "%s %2d 2027", months[m - 1], 9);
        struct tm tmv = {};
        tmv.tm_year = 2027 - 1900; tmv.tm_mon = m - 1; tmv.tm_mday = 9;
        CHECK(buildDateEpoch(buf) == (int64_t)timegm(&tmv));
    }
}

static void testClockGate() {
    TimeGate g;
    tgInit(&g, 1000);
    CHECK(!tgMayPostTls(&g));
    // the first call opens a round at once
    CHECK(tgStep(&g, 1000, 0) == TG_START && g.running);
    CHECK(!tgMayPostTls(&g));
    // inside the round with no answer: nothing and still no TLS
    CHECK(tgStep(&g, 1000 + 5000, 3) == TG_NONE && !tgMayPostTls(&g));
    // the clock arrives
    CHECK(tgStep(&g, 1000 + 7000, (uint32_t)TIME_VALID_MIN_EPOCH + 5) == TG_SYNCED);
    CHECK(tgMayPostTls(&g) && !g.running);
    CHECK(tgStep(&g, 1000 + 8000, (uint32_t)TIME_VALID_MIN_EPOCH + 6) == TG_NONE && tgMayPostTls(&g));

    // a round that gets no answer closes after the window, waits and tries again, with doubling waits
    tgInit(&g, 0);
    uint32_t t = 0;
    CHECK(tgStep(&g, t, 0) == TG_START);
    uint32_t expectWait = TIME_RETRY_START_MS;
    for (int round = 0; round < 8; round++) {
        // run to the end of the window
        t += TIME_SYNC_WINDOW_MS;
        CHECK(tgStep(&g, t, 0) == TG_NONE && !g.running && !tgMayPostTls(&g));
        CHECK(g.retryMs == expectWait);
        // one millisecond short of the wait: still idle
        CHECK(tgStep(&g, t + expectWait - 1, 0) == TG_NONE && !g.running);
        t += expectWait;
        CHECK(tgStep(&g, t, 0) == TG_START && g.running);
        expectWait = expectWait * 2 > TIME_RETRY_MAX_MS ? (uint32_t)TIME_RETRY_MAX_MS : expectWait * 2;
    }
    CHECK(g.retryMs == TIME_RETRY_MAX_MS);

    // the wait uses unsigned differences, so a millis() wrap in the middle changes nothing
    tgInit(&g, 0xFFFFF000u);
    CHECK(tgStep(&g, 0xFFFFF000u, 0) == TG_START);
    CHECK(tgStep(&g, (uint32_t)(0xFFFFF000u + TIME_SYNC_WINDOW_MS), 0) == TG_NONE && !g.running);
    CHECK(tgStep(&g, (uint32_t)(0xFFFFF000u + TIME_SYNC_WINDOW_MS + TIME_RETRY_START_MS), 0) == TG_START);

    // a clock that was already right (the core set it) needs no round
    tgInit(&g, 5);
    CHECK(tgStep(&g, 5, (uint32_t)TIME_VALID_MIN_EPOCH + 1) == TG_SYNCED && tgMayPostTls(&g));

    // a clock that falls back to unset withdraws the permission and starts again at once
    CHECK(tgStep(&g, 100, 10) == TG_NONE && !tgMayPostTls(&g));
    CHECK(tgStep(&g, 101, 10) == TG_START);

    // no TLS permission is ever given without a plausible clock, whatever the call order
    for (uint32_t seed = 1; seed < 2000; seed++) {
        TimeGate x;
        tgInit(&x, seed * 7);
        uint32_t now = seed * 7;
        for (int i = 0; i < 400; i++) {
            now += (seed * 31 + i * 17) % 4000;
            uint32_t epoch = ((seed + i) % 5 == 0) ? (uint32_t)TIME_VALID_MIN_EPOCH + now : (uint32_t)(i % 3);
            bool before = tgMayPostTls(&x);
            tgStep(&x, now, epoch);
            // a clock that is not plausible on this call never leaves permission standing
            if (!timeIsPlausible(epoch)) CHECK(!tgMayPostTls(&x));
            // permission can only appear on a call whose clock is plausible
            if (!before && tgMayPostTls(&x)) CHECK(timeIsPlausible(epoch));
        }
    }
}

static void testOutcomes() {
    const uint32_t BO = 20000;
    PostOutcome o = poClassify(200, 0, BO);
    CHECK(o.kind == PK_OK && o.waitMs == 0);
    CHECK(poClassify(201, 0, BO).kind == PK_OK && poClassify(204, 0, BO).kind == PK_OK);
    // a failure with no status waits the normal back-off
    o = poClassify(-1, 0, BO);
    CHECK(o.kind == PK_NETWORK && o.waitMs == BO);
    // a redirect is a failed post, named as one, on the normal back-off
    o = poClassify(301, 0, BO);
    CHECK(o.kind == PK_REDIRECT && o.waitMs == BO);
    CHECK(poClassify(308, 0, BO).kind == PK_REDIRECT);
    // a 401 or a 403 waits ten minutes, not the back-off and a longer Retry-After does not change that
    o = poClassify(401, 0, 5000);
    CHECK(o.kind == PK_AUTH && o.waitMs == POST_AUTH_RETRY_MS && POST_AUTH_RETRY_MS == 600000UL);
    o = poClassify(401, 5, 60000);
    CHECK(o.waitMs == POST_AUTH_RETRY_MS);
    CHECK(poClassify(403, 0, 5000).kind == PK_AUTH);
    // a 409 means the server holds a newer counter. only an admin can fix that, so it waits ten minutes too
    o = poClassify(409, 0, 5000);
    CHECK(o.kind == PK_CONFLICT && o.waitMs == POST_AUTH_RETRY_MS);
    CHECK(poClassify(409, 3, 60000).waitMs == POST_AUTH_RETRY_MS);
    // a 404 is a wrong address: ten minutes and its own kind
    o = poClassify(404, 0, 5000);
    CHECK(o.kind == PK_NOTFOUND && o.waitMs == POST_AUTH_RETRY_MS);
    CHECK(poClassify(404, 9, 60000).waitMs == POST_AUTH_RETRY_MS);
    CHECK(poClassify(410, 0, 5000).kind == PK_REJECTED);
    // a 429 waits at least its Retry-After and never less than the back-off
    o = poClassify(429, 120, 5000);
    CHECK(o.kind == PK_THROTTLED && o.waitMs == 120000);
    o = poClassify(429, 2, 40000);
    CHECK(o.waitMs == 40000);
    o = poClassify(429, 0, 10000);
    CHECK(o.waitMs == 10000);
    // and is capped at an hour, whatever the server says
    o = poClassify(429, 86400, 5000);
    CHECK(o.waitMs == POST_RETRY_AFTER_MAX_MS);
    o = poClassify(429, 0xFFFFFFFFu, 5000);
    CHECK(o.waitMs == POST_RETRY_AFTER_MAX_MS);
    // other responses
    CHECK(poClassify(400, 0, BO).kind == PK_REJECTED && poClassify(422, 0, BO).kind == PK_REJECTED);
    CHECK(poClassify(500, 0, BO).kind == PK_SERVER && poClassify(503, 0, BO).kind == PK_SERVER);
    // a Retry-After on anything but a 429 is ignored
    CHECK(poClassify(503, 3600, BO).waitMs == BO);
    // the names are never empty
    for (int k = 0; k <= PK_SERVER; k++) CHECK(poKindName((PostKind)k)[0] != 0);
}

// a 401 for ever: the gate through PostGate. one attempt every ten minutes, never one a minute
static void testAuthRetryRate() {
    PostGate gate;
    pgInit(&gate);
    Backoff b;
    backoffInit(&b);
    uint32_t attempts = 0;
    for (uint32_t t = 0; t < 3600UL * 1000UL; t += 200) {
        if (!pgMayPost(&gate, t)) continue;
        attempts++;
        PostOutcome o = poClassify(401, 0, backoffFailure(&b));
        pgFailed(&gate, t, o.waitMs);
    }
    CHECK(attempts <= 7);                    // one at the start and one every ten minutes
    CHECK(attempts >= 6);
    // a 429 with Retry-After holds the gate for that long
    pgInit(&gate);
    backoffInit(&b);
    PostOutcome o = poClassify(429, 90, backoffFailure(&b));
    pgFailed(&gate, 1000, o.waitMs);
    CHECK(!pgMayPost(&gate, 1000 + 89000));
    CHECK(pgMayPost(&gate, 1000 + 90000));
}

// a storage the tests control: it can fail to read, fail to write, lose the value after a write or
// report that credentials are stored
struct FakeStore : BootStore {
    bool     has = false;
    uint32_t value = 0;
    bool     failRead = false, failWrite = false, dropWrite = false, creds = false;
    int      writes = 0;
    NvsRead read(uint32_t* v) override {
        if (failRead) return NVSR_ERROR;
        if (!has) return NVSR_NOT_FOUND;
        *v = value;
        return NVSR_OK;
    }
    bool write(uint32_t v) override {
        writes++;
        if (failWrite) return false;
        if (dropWrite) return true;              // says it wrote and did not
        has = true;
        value = v;
        return true;
    }
    bool credsStored() override { return creds; }
};

static void testBootAdvance() {
    uint32_t out = 99;
    // the first boot of a hub that was never provisioned
    FakeStore s;
    CHECK(bootAdvance(s, &out) == BOOT_OK && out == 1 && s.value == 1);
    CHECK(bootAdvance(s, &out) == BOOT_OK && out == 2 && s.value == 2);
    s.value = 41;
    CHECK(bootAdvance(s, &out) == BOOT_OK && out == 42);
    // a read error is not "never written": nothing is written and no boot is given
    FakeStore e;
    e.has = true; e.value = 41; e.failRead = true;
    out = 7;
    CHECK(bootAdvance(e, &out) == BOOT_READ_FAILED && out == 7 && e.writes == 0 && e.value == 41);
    // a counter that is missing on a hub that has stored credentials is a lost counter. it is not the first boot
    FakeStore lost;
    lost.creds = true;
    out = 7;
    CHECK(bootAdvance(lost, &out) == BOOT_LOST && out == 7 && lost.writes == 0);
    // and the same missing counter on a hub with no credentials is a first boot
    FakeStore first;
    first.creds = false;
    CHECK(bootAdvance(first, &out) == BOOT_OK && out == 1);
    // a hub with credentials and a counter carries on as normal
    FakeStore normal;
    normal.creds = true; normal.has = true; normal.value = 10;
    CHECK(bootAdvance(normal, &out) == BOOT_OK && out == 11);
    // the limit never wraps
    FakeStore lim;
    lim.has = true; lim.value = 0xFFFFFFFFu;
    out = 7;
    CHECK(bootAdvance(lim, &out) == BOOT_LIMIT && out == 7 && lim.writes == 0 && lim.value == 0xFFFFFFFFu);
    lim.value = 0xFFFFFFFEu;
    CHECK(bootAdvance(lim, &out) == BOOT_OK && out == 0xFFFFFFFFu);
    CHECK(bootAdvance(lim, &out) == BOOT_LIMIT);
    // a write that fails and a write that says it worked and did not
    FakeStore w;
    w.has = true; w.value = 5; w.failWrite = true;
    out = 7;
    CHECK(bootAdvance(w, &out) == BOOT_WRITE_FAILED && out == 7);
    FakeStore d;
    d.has = true; d.value = 5; d.dropWrite = true;
    CHECK(bootAdvance(d, &out) == BOOT_READBACK_FAILED && out == 7);
    // a counter that was never written and a write that is dropped
    FakeStore n;
    n.dropWrite = true;
    CHECK(bootAdvance(n, &out) == BOOT_READBACK_FAILED);
    // every failure has a name for the serial monitor
    for (int r = 0; r <= BOOT_READBACK_FAILED; r++) CHECK(bootResultName((BootResult)r)[0] != 0);
}

// (boot, seq) strictly increases across every path
static void testIdentity() {
    uint32_t seq = 0;
    CHECK(seqNext(&seq) && seq == 1);
    seq = 0xFFFFFFFEu;
    CHECK(seqNext(&seq) && seq == 0xFFFFFFFFu);
    CHECK(!seqNext(&seq) && seq == 0xFFFFFFFFu);         // never wraps to 0
    CHECK(!seqNext(&seq) && seq == 0xFFFFFFFFu);

    // many boots through the real bootAdvance with a storage that fails on some boots, with resets after
    // any number of bodies. every pair that is sent is new and greater than the one before it and a boot
    // whose counter fails sends nothing and leaves the stored counter alone
    FakeStore store;
    store.creds = true;
    store.has = true;
    std::pair<uint32_t, uint32_t> last(0, 0);
    std::set<std::pair<uint32_t, uint32_t>> seen;
    int failedBoots = 0, goodBoots = 0;
    for (int boot = 0; boot < 300; boot++) {
        store.failRead = (boot % 17 == 5);
        store.failWrite = (boot % 23 == 7);
        store.dropWrite = (boot % 29 == 11);
        uint32_t before = store.value;
        uint32_t b = 0;
        BootResult r = bootAdvance(store, &b);
        if (r != BOOT_OK) {
            failedBoots++;
            CHECK(store.value == before || store.value == before + 1);   // a dropped write may have raised it, never lowered it
            continue;                                    // the hub builds nothing on this boot
        }
        goodBoots++;
        CHECK(b == store.value && b > last.first);
        uint32_t s = 0;
        int bodies = (boot * 13) % 40;
        for (int i = 0; i < bodies; i++) {
            CHECK(seqNext(&s));                          // a body that is later replaced still takes its number
            std::pair<uint32_t, uint32_t> cur(b, s);
            CHECK(cur > last);
            CHECK(seen.insert(cur).second);
            last = cur;
        }
        if (bodies == 0) last.first = b;                 // a boot with no body still used its number
    }
    CHECK(failedBoots > 10 && goodBoots > 200);
}

int main() {
    testPlausible();
    testClockGate();
    testOutcomes();
    testAuthRetryRate();
    testBootAdvance();
    testIdentity();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
