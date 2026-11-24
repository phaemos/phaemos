// test_post.cpp - host test for the pure parts of the post task and the panel: the one-slot
// mailbox, the back-off, the watch the main loop keeps on the post task, the status precedence
// and alternation and the state kept across a warm reset.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_post.cpp ../comms/post_queue.cpp ../outputs/status_logic.cpp ../outputs/saved_state.cpp ../outputs/temp_judge.cpp -o "${TMPDIR:-/tmp}/test_post" && "${TMPDIR:-/tmp}/test_post"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_post.cpp ../comms/post_queue.cpp ../outputs/status_logic.cpp ../outputs/saved_state.cpp ../outputs/temp_judge.cpp -o "${TMPDIR:-/tmp}/test_post_san" && "${TMPDIR:-/tmp}/test_post_san"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "../comms/post_queue.h"
#include "../config.h"
#include "../outputs/saved_state.h"
#include "../outputs/status_logic.h"

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

static Mailbox g_box;

static void testMailbox() {
    mbInit(&g_box);
    char out[TELEMETRY_BODY_MAX_BYTES];
    size_t len = 99;
    // empty
    CHECK(!mbTake(&g_box, out, sizeof out, &len));
    // one body in and out
    CHECK(mbPut(&g_box, "{\"seq\":1}", 9) == PUT_OK);
    CHECK(g_box.full);
    CHECK(mbTake(&g_box, out, sizeof out, &len));
    CHECK(len == 9 && std::strcmp(out, "{\"seq\":1}") == 0);
    CHECK(!g_box.full && g_box.delivered == 1 && g_box.replaced == 0);
    // taking twice gives nothing the second time
    CHECK(!mbTake(&g_box, out, sizeof out, &len));
    // a newer body replaces an older unsent one with the loss counted
    CHECK(mbPut(&g_box, "{\"seq\":2}", 9) == PUT_OK);
    CHECK(mbPut(&g_box, "{\"seq\":3}", 9) == PUT_REPLACED);
    CHECK(mbPut(&g_box, "{\"seq\":4}", 9) == PUT_REPLACED);
    CHECK(g_box.replaced == 2);
    CHECK(mbTake(&g_box, out, sizeof out, &len));
    CHECK(std::strcmp(out, "{\"seq\":4}") == 0);          // always the newest
    CHECK(!mbTake(&g_box, out, sizeof out, &len));
    // the size limit: the largest body that fits and one that does not
    std::string big(TELEMETRY_BODY_MAX_BYTES - 1, 'a');
    CHECK(mbPut(&g_box, big.data(), big.size()) == PUT_OK);
    CHECK(mbTake(&g_box, out, sizeof out, &len) && len == big.size());
    std::string tooBig(TELEMETRY_BODY_MAX_BYTES, 'a');
    CHECK(mbPut(&g_box, tooBig.data(), tooBig.size()) == PUT_TOO_BIG);
    CHECK(!g_box.full);
    // a rejected body leaves a waiting one alone
    CHECK(mbPut(&g_box, "x", 1) == PUT_OK);
    CHECK(mbPut(&g_box, tooBig.data(), tooBig.size()) == PUT_TOO_BIG);
    CHECK(g_box.full && g_box.len == 1);
    // a destination that is too small takes nothing
    char small[4];
    CHECK(mbPut(&g_box, "abcdef", 6) == PUT_REPLACED);
    CHECK(!mbTake(&g_box, small, sizeof small, &len));
    CHECK(g_box.full);
}

static void testBackoff() {
    Backoff b;
    backoffInit(&b);
    // starts at 5 s, doubles and stops at 60 s
    CHECK(backoffFailure(&b) == 5000);
    CHECK(backoffFailure(&b) == 10000);
    CHECK(backoffFailure(&b) == 20000);
    CHECK(backoffFailure(&b) == 40000);
    CHECK(backoffFailure(&b) == 60000);
    CHECK(backoffFailure(&b) == 60000);
    CHECK(backoffFailure(&b) == 60000);
    // one success starts it again
    backoffSuccess(&b);
    CHECK(backoffFailure(&b) == 5000);
    CHECK(POST_BACKOFF_START_MS == 5000 && POST_BACKOFF_MAX_MS == 60000);
}

static void testPostWatch() {
    PostWatch w;
    pwInit(&w, 1000);
    // idle and beating
    CHECK(pwHealthy(&w, 1000, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    pwBeat(&w, 5000);
    CHECK(pwHealthy(&w, 14999, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    CHECK(pwHealthy(&w, 15000, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // idle and silent for longer than the limit: the task is stuck
    CHECK(!pwHealthy(&w, 15001, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // a post that is in progress may take the long limit
    pwBusyStart(&w, 20000);
    CHECK(pwHealthy(&w, 20000 + 19000, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));   // a 19 s worst post
    CHECK(pwHealthy(&w, 20000 + 30000, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    CHECK(!pwHealthy(&w, 20000 + 30001, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // when it ends the beat is fresh again
    pwBusyEnd(&w, 50000);
    CHECK(pwHealthy(&w, 50500, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // an OTA download suspends the watch
    pwPause(&w, true, 60000);
    CHECK(pwHealthy(&w, 60000 + POST_OTA_PAUSE_LIMIT_MS, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    pwPause(&w, false, 600000);
    CHECK(pwHealthy(&w, 601000, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // across a millis() rollover
    pwInit(&w, 0xFFFFFF00u);
    pwBusyStart(&w, 0xFFFFFF00u);
    CHECK(pwHealthy(&w, 0xFFFFFF00u + 20000u, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    CHECK(!pwHealthy(&w, 0xFFFFFF00u + 31000u, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // the watchdog margin: the main loop's own limit is far under the post task's
    CHECK(WDT_TIMEOUT_S * 1000UL < POST_BUSY_LIMIT_MS);
    // 15 s of DNS plus the two HTTP timeouts is the slowest post. the limit leaves 11 s over
    CHECK(15000UL + HTTP_CONNECT_TIMEOUT_MS + HTTP_RESPONSE_TIMEOUT_MS == 19000UL);
    CHECK(POST_BUSY_LIMIT_MS - 19000UL >= 11000UL);
}

static StatusInput none() {
    StatusInput i;
    std::memset(&i, 0, sizeof i);
    return i;
}

static void testStatusPrecedence() {
    // nothing
    StatusResult r = decideStatus(none(), false);
    CHECK(r.base == STK_NORMAL && r.shown == STK_NORMAL && !r.both);
    CHECK(std::strcmp(r.text, "NORMAL") == 0);

    // a warning alone
    StatusInput w = none(); w.waterAlert = true;
    r = decideStatus(w, false);
    CHECK(r.base == STK_WARNING && r.shown == STK_WARNING && !r.both);
    CHECK(std::strcmp(r.text, "WARNING") == 0);
    StatusInput g = none(); g.gasAlert = true;
    CHECK(decideStatus(g, true).base == STK_WARNING);
    StatusInput t = none(); t.warnActive = true;
    CHECK(decideStatus(t, true).base == STK_WARNING);

    // a fault alone
    StatusInput f = none(); f.tempFault = true;
    r = decideStatus(f, false);
    CHECK(r.base == STK_FAULT && r.shown == STK_FAULT && !r.both);
    CHECK(std::strcmp(r.text, "FAULT: TEMP") == 0);

    // critical beats everything and never alternates
    StatusInput c = none();
    c.critActive = true; c.warnActive = true; c.waterAlert = true; c.tempFault = true; c.gasFault = true;
    for (int phase = 0; phase < 2; phase++) {
        r = decideStatus(c, phase != 0);
        CHECK(r.base == STK_CRITICAL && r.shown == STK_CRITICAL && !r.both);
        CHECK(std::strcmp(r.text, "CRITICAL") == 0);
    }
}

static void testStatusAlternation() {
    // a warning and a fault: the water warning from an unplugged probe must not hide FAULT: TEMP
    StatusInput b = none();
    b.waterAlert = true;
    b.tempFault = true;
    b.probeFault = true;
    StatusResult a = decideStatus(b, false);
    StatusResult c = decideStatus(b, true);
    CHECK(a.both && c.both);
    CHECK(a.base == STK_WARNING && c.base == STK_WARNING);      // the sound follows the highest level
    CHECK(a.shown == STK_WARNING && c.shown == STK_FAULT);      // the panel shows both in turn
    CHECK(std::strcmp(a.text, "WARNING") == 0);
    CHECK(std::strncmp(c.text, "FAULT:", 6) == 0);
    CHECK(std::strstr(c.text, "TEMP") != nullptr);
    // the text always fits the display row (17 characters after "STATUS: ")
    CHECK(std::strlen(c.text) <= 17);

    // every combination of warning and fault inputs shows both across two readings
    for (int m = 0; m < 4096; m++) {
        StatusInput i = none();
        i.warnActive = m & 1; i.gasAlert = m & 2; i.waterAlert = m & 4;
        i.tempFault = m & 8; i.gasFault = m & 16; i.probeFault = m & 32;
        i.gasWarm = m & 64; i.noTemp = m & 128; i.boardFault = m & 256;
        i.resetLoop = m & 512; i.otherFault = m & 1024; i.postFault = m & 2048;
        bool anyWarn = (m & 7) != 0;
        bool anyFault = (m & ~7) != 0;
        StatusResult p0 = decideStatus(i, false);
        StatusResult p1 = decideStatus(i, true);
        if (anyWarn && anyFault) {
            CHECK(p0.shown != p1.shown);
            CHECK((p0.shown == STK_WARNING && p1.shown == STK_FAULT) ||
                  (p0.shown == STK_FAULT && p1.shown == STK_WARNING));
            CHECK(p0.base == STK_WARNING && p1.base == STK_WARNING);
        } else {
            CHECK(p0.shown == p1.shown && !p0.both);
        }
    }
}

static void testStatusNewFaults() {
    // each new fault shows on its own, in words, by the same precedence
    struct Case { const char* name; void (*set)(StatusInput*); } cases[] = {
        { "NOTMP",  [](StatusInput* i) { i->noTemp = true; } },
        { "WARM",   [](StatusInput* i) { i->gasWarm = true; } },
        { "MQ-2",   [](StatusInput* i) { i->gasFault = true; } },
        { "BRD",    [](StatusInput* i) { i->boardFault = true; } },
        { "LOOP",   [](StatusInput* i) { i->resetLoop = true; } },
        { "PLN",    [](StatusInput* i) { i->plainHttp = true; } },
        { "CTR",    [](StatusInput* i) { i->counterRejected = true; } },
        { "NET",    [](StatusInput* i) { i->postFault = true; } },
        { "SENS",   [](StatusInput* i) { i->otherFault = true; } },
    };
    for (const Case& c : cases) {
        StatusInput i = none();
        c.set(&i);
        StatusResult r = decideStatus(i, false);
        CHECK(r.base == STK_FAULT && r.shown == STK_FAULT);
        CHECK(std::strstr(r.text, c.name) != nullptr);
        CHECK(std::strlen(r.text) <= 17);
        // a warning alongside it alternates and never hides it
        i.waterAlert = true;
        StatusResult a = decideStatus(i, false);
        StatusResult b = decideStatus(i, true);
        CHECK(a.shown == STK_WARNING && b.shown == STK_FAULT);
        CHECK(std::strstr(b.text, c.name) != nullptr);
        // and critical wins over all of it
        i.critActive = true;
        CHECK(decideStatus(i, true).shown == STK_CRITICAL && decideStatus(i, false).shown == STK_CRITICAL);
    }
    // the gas alarm not being available (warming up) is a fault for the whole warm-up
    StatusInput w = none();
    w.gasWarm = true;
    CHECK(decideStatus(w, true).base == STK_FAULT);
    // every name at once is cut to fit and marked
    StatusInput all = none();
    all.noTemp = all.gasFault = all.gasWarm = all.tempFault = all.probeFault = true;
    all.boardFault = all.resetLoop = all.postFault = all.otherFault = true;
    StatusResult r = decideStatus(all, false);
    CHECK(std::strlen(r.text) <= 17 && r.text[std::strlen(r.text) - 1] == '+');
    CHECK(std::strncmp(r.text, "FAULT: LOOP", 11) == 0);   // a reset loop is listed first
    // whole names only: nothing is ever cut in the middle
    CHECK(std::strstr(r.text, "NOTM") == nullptr || std::strstr(r.text, "NOTMP") != nullptr);
    // nothing wrong shows normal
    CHECK(decideStatus(none(), true).base == STK_NORMAL);
}

static void testStatusFaultText() {
    StatusInput i = none();
    i.tempFault = true; i.gasFault = true;
    CHECK(std::strcmp(decideStatus(i, false).text, "FAULT: MQ-2 TEMP") == 0);
    i.probeFault = true;
    StatusResult r = decideStatus(i, false);
    // three names do not fit the row, so the list is cut and marked
    CHECK(std::strlen(r.text) <= 17);
    CHECK(r.text[std::strlen(r.text) - 1] == '+');
    CHECK(std::strncmp(r.text, "FAULT: MQ-2 TEMP", 16) == 0);
    StatusInput p = none();
    p.probeFault = true;
    CHECK(std::strcmp(decideStatus(p, false).text, "FAULT: PRB") == 0);
}

static SavedState sealed(uint8_t crit, uint8_t mask) {
    SavedState s;
    std::memset(&s, 0, sizeof s);
    s.latchMask = crit ? 1 : 0;
    s.relayMask = mask;
    s.linksSeen = 3;
    ssSeal(&s);
    return s;
}

static void testSavedState() {
    SavedState s;
    std::memset(&s, 0, sizeof s);
    s.latchMask = 1;
    s.relayMask = 1;
    s.linksSeen = 3;
    CHECK(!ssValid(&s));                       // not sealed yet
    ssSeal(&s);
    CHECK(ssValid(&s));
    // warm resets restore. a cold power-up, a brown-out, the reset pin, deep sleep and unknown do not
    CHECK(ssRestoreVerdict(3, &s) == RV_RESTORE);              // software
    CHECK(ssRestoreVerdict(4, &s) == RV_RESTORE);              // panic
    CHECK(ssRestoreVerdict(5, &s) == RV_RESTORE);              // interrupt watchdog
    CHECK(ssRestoreVerdict(6, &s) == RV_RESTORE);              // task watchdog
    CHECK(ssRestoreVerdict(7, &s) == RV_RESTORE);              // other watchdog
    CHECK(ssRestoreVerdict(0, &s) == RV_NONE);
    CHECK(ssRestoreVerdict(1, &s) == RV_NONE);                 // power-on
    CHECK(ssRestoreVerdict(2, &s) == RV_NONE);                 // reset pin
    CHECK(ssRestoreVerdict(8, &s) == RV_NONE);
    CHECK(ssRestoreVerdict(9, &s) == RV_NONE);                 // brown-out
    CHECK(ssRestoreVerdict(10, &s) == RV_NONE);
    CHECK(ssRestoreVerdict(-1, &s) == RV_NONE);
    // a warm reset is a restore verdict whatever the relays were doing, because every warm reset
    // is counted until a trusted temperature reading arrives
    SavedState off = sealed(0, 0);
    CHECK(ssRestoreVerdict(6, &off) == RV_RESTORE);
    // damage is refused: the magic, any byte of the body and the checksum
    SavedState d = s;
    d.magic ^= 1;
    CHECK(!ssValid(&d));
    d = s; d.latchMask ^= 1;
    CHECK(!ssValid(&d));
    d = s; d.relayMask ^= 1;
    CHECK(!ssValid(&d));
    d = s; d.linksSeen ^= 1;
    CHECK(!ssValid(&d));
    d = s; d.unconfirmed ^= 1;
    CHECK(!ssValid(&d));
    d = s; d.strikes[2] ^= 1;
    CHECK(!ssValid(&d));
    d = s; d.check ^= 0x100;
    CHECK(!ssValid(&d));
    CHECK(ssRestoreVerdict(6, &d) == RV_NONE);
    // every single bit of the struct: none may leave it valid
    int stillValid = 0;
    for (unsigned i = 0; i < sizeof(SavedState) * 8; i++) {
        SavedState e = s;
        ((uint8_t*)&e)[i / 8] ^= (uint8_t)(1u << (i % 8));
        if (ssValid(&e) && std::memcmp(&e, &s, sizeof s) != 0) {
            // a flip in the reserved bytes does not change the meaning. only those may remain valid
            size_t byte = i / 8;
            if (byte != offsetof(SavedState, reserved) && byte != offsetof(SavedState, reserved) + 1) stillValid++;
        }
    }
    CHECK(stillValid == 0);
    // random memory (a cold start) is not valid
    SavedState junk;
    std::memset(&junk, 0xA5, sizeof junk);
    CHECK(!ssValid(&junk));
    std::memset(&junk, 0, sizeof junk);
    CHECK(!ssValid(&junk));
    // out of range values are refused even with a good checksum
    SavedState o = s;
    o.relayMask = 0x1F;
    ssSeal(&o);
    CHECK(!ssValid(&o));
    o = s; o.setupMarker = SETUP_COUNT + 1;
    ssSeal(&o);
    CHECK(!ssValid(&o));
    // the layout is versioned in the magic, so a record from another layout is never valid
    SavedState v = s;
    v.magic = (SAVED_STATE_MAGIC & ~0xFFu) | ((SAVED_STATE_LAYOUT + 1) & 0xFF);
    CHECK(!ssValid(&v));
    CHECK((SAVED_STATE_MAGIC & 0xFF) == SAVED_STATE_LAYOUT);
    // ssReset gives a valid empty record
    ssReset(&v);
    CHECK(ssValid(&v) && v.latchMask == 0 && v.unconfirmed == 0 && v.setupMarker == 0);
}

static void testResetLoop() {
    // a reset loop: restores that no reading confirmed are counted. after RESTORE_MAX_UNCONFIRMED
    // the hub stops restoring. the relay takes its no-information state
    SavedState s = sealed(1, 1);
    CHECK(s.unconfirmed == 0);
    CHECK(ssRestoreVerdict(6, &s) == RV_RESTORE);
    ssNoteBoot(&s);
    CHECK(s.unconfirmed == 1 && ssValid(&s));
    CHECK(ssRestoreVerdict(6, &s) == RV_RESTORE);           // the second boot of the loop still restores
    ssNoteBoot(&s);
    CHECK(s.unconfirmed == 2);
    CHECK(RESTORE_MAX_UNCONFIRMED == 2);
    CHECK(ssRestoreVerdict(6, &s) == RV_REFUSE);            // the third does not
    CHECK(ssRestoreVerdict(3, &s) == RV_REFUSE);
    CHECK(ssRestoreVerdict(1, &s) == RV_NONE);              // a power-up clears it all (cold start)
    // a confirmed reading clears the count
    ssNoteConfirmed(&s);
    CHECK(s.unconfirmed == 0 && ssValid(&s));
    CHECK(ssRestoreVerdict(6, &s) == RV_RESTORE);
    // confirming with nothing to clear changes nothing
    SavedState t = sealed(1, 1);
    SavedState copy = t;
    ssNoteConfirmed(&t);
    CHECK(std::memcmp(&t, &copy, sizeof t) == 0);
    // the no-information state is one named constant
    CHECK(COOLING_RELAY_NO_INFO_ON == 1);
}

static void testSetupProtection() {
    // a sensor whose set-up is running is named in the record. a warm reset then finds the marker
    SavedState s = sealed(0, 0);
    ssSetupBegin(&s, SETUP_MPU6050);
    CHECK(s.setupMarker == SETUP_MPU6050 + 1 && ssValid(&s));
    // the set-up ends normally: nothing to find
    ssSetupEnd(&s);
    CHECK(s.setupMarker == 0 && ssValid(&s));
    SetupVerdict v = ssSetupBootCheck(&s, 6);
    for (int i = 0; i < SETUP_COUNT; i++) CHECK(!v.skipThisBoot[i] && !v.excluded[i]);

    // the set-up stalls and the watchdog resets the hub
    ssSetupBegin(&s, SETUP_BME280);
    v = ssSetupBootCheck(&s, 6);                            // task watchdog
    CHECK(v.skipThisBoot[SETUP_BME280]);
    CHECK(!v.excluded[SETUP_BME280]);                       // one strike
    CHECK(s.strikes[SETUP_BME280] == 1 && s.setupMarker == 0);
    for (int i = 0; i < SETUP_COUNT; i++) if (i != SETUP_BME280) CHECK(!v.skipThisBoot[i]);
    CHECK(!ssSetupExcluded(&s, SETUP_BME280));
    // retried later and it stalls again: two strikes and it stays out until power-up
    // a panic or a software reset inside a set-up is not a task watchdog stall, so it costs nothing
    ssSetupBegin(&s, SETUP_BME280);
    v = ssSetupBootCheck(&s, 4);
    CHECK(!v.skipThisBoot[SETUP_BME280] && s.strikes[SETUP_BME280] == 1 && s.setupMarker == 0);
    ssSetupBegin(&s, SETUP_BME280);
    v = ssSetupBootCheck(&s, 3);
    CHECK(!v.skipThisBoot[SETUP_BME280] && s.strikes[SETUP_BME280] == 1);
    ssSetupBegin(&s, SETUP_BME280);
    v = ssSetupBootCheck(&s, 6);                            // task watchdog again
    CHECK(v.skipThisBoot[SETUP_BME280] && v.excluded[SETUP_BME280]);
    CHECK(ssSetupExcluded(&s, SETUP_BME280));
    CHECK(SETUP_MAX_STRIKES == 2);
    // another sensor is not affected
    CHECK(!ssSetupExcluded(&s, SETUP_MPU6050));
    // a boot with no marker keeps the exclusion
    v = ssSetupBootCheck(&s, 3);
    CHECK(!v.skipThisBoot[SETUP_BME280] && v.excluded[SETUP_BME280]);
    // a cold start gives a fresh record, so the sensor is tried again after power-up
    SavedState cold;
    ssReset(&cold);
    CHECK(!ssSetupExcluded(&cold, SETUP_BME280));
    // a cold reset reason never reads the marker
    SavedState c = sealed(0, 0);
    ssSetupBegin(&c, SETUP_INA219);
    v = ssSetupBootCheck(&c, 1);
    CHECK(!v.skipThisBoot[SETUP_INA219] && c.strikes[SETUP_INA219] == 0);
    // a damaged record is never read
    SavedState dmg = sealed(0, 0);
    ssSetupBegin(&dmg, SETUP_AS5600);
    dmg.check ^= 1;
    v = ssSetupBootCheck(&dmg, 6);
    CHECK(!v.skipThisBoot[SETUP_AS5600]);
}

// ─── the post schedule across simulated days ─────────────────────────────────
// runs the post task's schedule for `days` of simulated time on a 200 ms tick, the way the task
// does: a gate that is closed only while a back-off is pending. `failDay` makes one post fail on
// that day (negative for none). start is the millis() value at boot, so the 49.7 day wrap can be
// crossed. returns the longest run of ticks, in seconds, during which the gate was open but nothing
// was posted because the schedule had stopped. it counts a gap between two posts
static uint32_t longestGapSeconds(double days, int failDay, uint32_t start, uint32_t* posts) {
    PostGate g;
    pgInit(&g);
    Backoff b;
    backoffInit(&b);
    const uint32_t tickMs = 200;
    const uint32_t intervalMs = TELEMETRY_INTERVAL_MS;        // one body every 5 s
    uint64_t total = (uint64_t)(days * 86400.0 * 1000.0);
    uint32_t lastPost = start;
    uint32_t longest = 0;
    bool failed = false;
    uint64_t nextBody = 0;
    bool haveBody = false;
    *posts = 0;
    for (uint64_t t = 0; t < total; t += tickMs) {
        uint32_t now = start + (uint32_t)t;                   // wraps like millis()
        if (t >= nextBody) { haveBody = true; nextBody += intervalMs; }
        if (!haveBody || !pgMayPost(&g, now)) continue;
        haveBody = false;
        bool failNow = (failDay >= 0 && !failed && t >= (uint64_t)failDay * 86400000ull);
        if (failNow) {
            failed = true;
            pgFailed(&g, now, backoffFailure(&b));
        } else {
            pgSuccess(&g);
            backoffSuccess(&b);
            (*posts)++;
            uint32_t gap = (uint32_t)(now - lastPost) / 1000;
            if (gap > longest) longest = gap;
            lastPost = now;
        }
    }
    return longest;
}

// the schedule the hub used before: a stored time of the next attempt, compared with a signed
// difference whether or not a back-off was pending. kept here only to show the test above fails on it
static uint32_t longestGapSecondsOld(double days, int failDay, uint32_t start) {
    uint32_t nextAttemptMs = 0;
    const uint32_t tickMs = 200;
    uint64_t total = (uint64_t)(days * 86400.0 * 1000.0);
    uint32_t lastPost = start, longest = 0;
    bool failed = false, haveBody = false;
    uint64_t nextBody = 0;
    for (uint64_t t = 0; t < total; t += tickMs) {
        uint32_t now = start + (uint32_t)t;
        if (t >= nextBody) { haveBody = true; nextBody += TELEMETRY_INTERVAL_MS; }
        if (!haveBody || (int32_t)(now - nextAttemptMs) < 0) continue;
        haveBody = false;
        if (failDay >= 0 && !failed && t >= (uint64_t)failDay * 86400000ull) {
            failed = true;
            nextAttemptMs = now + 5000;
        } else {
            uint32_t gap = (uint32_t)(now - lastPost) / 1000;
            if (gap > longest) longest = gap;
            lastPost = now;
        }
    }
    return longest;
}

static void testPostScheduleAcrossDays() {
    uint32_t posts = 0;
    // no failure for 60 days: it must keep posting every interval, with no gap longer than a few
    // seconds. the old schedule went silent from day 25 to day 48
    uint32_t gap = longestGapSeconds(60.0, -1, 0, &posts);
    CHECK(gap <= 6);
    CHECK(posts > 60ull * 86400 / 5 - 100);
    // one failed post on day 10. the back-off is 5 s and then it carries on. the old schedule
    // went silent from day 35 to day 58
    gap = longestGapSeconds(60.0, 10, 0, &posts);
    CHECK(gap <= 12);
    CHECK(posts > 60ull * 86400 / 5 - 100);
    // a failure at day 30, after the old fault would already have shown
    gap = longestGapSeconds(60.0, 30, 0, &posts);
    CHECK(gap <= 12);
    // boot at a millis() value that makes the 49.7 day wrap fall inside the run
    gap = longestGapSeconds(60.0, -1, 0xFFFFFFFFu - 20ull * 86400 * 1000, &posts);
    CHECK(gap <= 6);
    gap = longestGapSeconds(60.0, 10, 0xFFFFFFFFu - 20ull * 86400 * 1000, &posts);
    CHECK(gap <= 12);
    // and for a boot just before the signed half-way point
    gap = longestGapSeconds(60.0, 5, 0x7FFFFFFFu - 3ull * 86400 * 1000, &posts);
    CHECK(gap <= 12);

    // the old schedule really did go silent for about 24 days, so the test above would have caught it
    CHECK(longestGapSecondsOld(60.0, -1, 0) > 20ull * 86400);
    CHECK(longestGapSecondsOld(60.0, 10, 0) > 20ull * 86400);

    // the gate itself: open with no back-off at any time, closed only while one is pending
    PostGate g;
    pgInit(&g);
    for (uint32_t t : { 0u, 1u, 0x7FFFFFFFu, 0x80000000u, 0xFFFFFFFFu }) CHECK(pgMayPost(&g, t));
    pgFailed(&g, 1000, 5000);
    CHECK(!pgMayPost(&g, 1000));
    CHECK(!pgMayPost(&g, 5999));
    CHECK(pgMayPost(&g, 6000));
    CHECK(pgMayPost(&g, 6001));                              // and it stays open once it has opened
    // a back-off that crosses the wrap
    pgFailed(&g, 0xFFFFFF00u, 5000);
    CHECK(!pgMayPost(&g, 0xFFFFFF00u + 4000u));
    CHECK(pgMayPost(&g, 0xFFFFFF00u + 5000u));
    // a success ends a back-off at once
    pgFailed(&g, 100, 60000);
    pgSuccess(&g);
    CHECK(pgMayPost(&g, 101));
}

static void testPostFreshness() {
    PostFreshness f;
    pfInit(&f, 1000);
    // nothing for five minutes from boot: stale
    CHECK(!pfUpdate(&f, 1000 + POST_STALE_MS - 1, 0, POST_STALE_MS));
    CHECK(pfUpdate(&f, 1000 + POST_STALE_MS, 0, POST_STALE_MS));
    // it stays stale until a post succeeds
    CHECK(pfUpdate(&f, 1000 + 2 * POST_STALE_MS, 0, POST_STALE_MS));
    CHECK(!pfUpdate(&f, 1000 + 2 * POST_STALE_MS + 5000, 1, POST_STALE_MS));
    // each success moves the reference
    CHECK(!pfUpdate(&f, 1000 + 2 * POST_STALE_MS + 5000 + POST_STALE_MS - 1, 1, POST_STALE_MS));
    CHECK(!pfUpdate(&f, 1000 + 3 * POST_STALE_MS, 2, POST_STALE_MS));
    // and a long outage is latched across a millis() alias
    uint32_t t = 0xFFFFF000u;
    pfInit(&f, t);
    CHECK(!pfUpdate(&f, t + 1000, 0, POST_STALE_MS));
    uint32_t cursor = t;
    bool stale = false;
    for (int i = 0; i < 100 && !stale; i++) {
        cursor += 20000;
        stale = pfUpdate(&f, cursor, 0, POST_STALE_MS);
    }
    CHECK(stale);
    CHECK(pfUpdate(&f, cursor + 5000, 0, POST_STALE_MS));
    CHECK(POST_STALE_MS == 300000);
}

static void testOtaPauseLimit() {
    PostWatch w;
    pwInit(&w, 0);
    pwPause(&w, true, 10000);
    CHECK(pwHealthy(&w, 10000 + POST_OTA_PAUSE_LIMIT_MS, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    // a download that hangs is not given for ever
    CHECK(!pwHealthy(&w, 10000 + POST_OTA_PAUSE_LIMIT_MS + 1, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
    pwPause(&w, false, 400000);
    CHECK(pwHealthy(&w, 401000, POST_BUSY_LIMIT_MS, POST_IDLE_LIMIT_MS));
}

static void testRestoreStep() {
    const uint32_t deadline = 10000;
    CHECK(ssRestoreStep(false, true, 0, deadline) == RESTORE_NONE);
    CHECK(ssRestoreStep(false, false, 99999, deadline) == RESTORE_NONE);
    // waiting for a reading
    CHECK(ssRestoreStep(true, false, 0, deadline) == RESTORE_WAIT);
    CHECK(ssRestoreStep(true, false, 9999, deadline) == RESTORE_WAIT);
    // a good reading hands it to the normal judgement
    CHECK(ssRestoreStep(true, true, 500, deadline) == RESTORE_CONFIRMED);
    CHECK(ssRestoreStep(true, true, 20000, deadline) == RESTORE_CONFIRMED);
    // no reading by the deadline: dropped, so a reset loop cannot hold the relay on for ever
    CHECK(ssRestoreStep(true, false, 10000, deadline) == RESTORE_DROP);
    CHECK(ssRestoreStep(true, false, 30000, deadline) == RESTORE_DROP);
    // the deadline works across a millis() rollover
    uint32_t d2 = 0xFFFFFF00u + 10000u;                 // wraps
    CHECK(ssRestoreStep(true, false, 0xFFFFFF00u + 5000u, d2) == RESTORE_WAIT);
    CHECK(ssRestoreStep(true, false, 0xFFFFFF00u + 10000u, d2) == RESTORE_DROP);
    CHECK(RELAY_RESTORE_CONFIRM_MS == 10000);
}


// the post task asks the gate on every pass, Wi-Fi up or not. a pending back-off must never be left
// to age through an outage. outDays is how long Wi-Fi is down, starting on outStartDay. the gate is
// the real one. the old signed schedule is modelled alongside to show the test bites
static uint32_t longestGapWithOutage(double days, int failDay, int outStartDay, double outDays, bool oldGate) {
    PostGate g;
    pgInit(&g);
    Backoff b;
    backoffInit(&b);
    uint32_t oldUntil = 0;
    bool oldPending = false;
    const uint32_t tickMs = 200;
    uint64_t total = (uint64_t)(days * 86400.0 * 1000.0);
    uint64_t outFrom = (uint64_t)outStartDay * 86400000ull;
    uint64_t outTo = outFrom + (uint64_t)(outDays * 86400000.0);
    uint32_t lastPost = 0, longest = 0;
    bool failed = false, haveBody = false;
    uint64_t nextBody = 0;
    for (uint64_t t = 0; t < total; t += tickMs) {
        uint32_t now = (uint32_t)t;
        if (t >= nextBody) { haveBody = true; nextBody += TELEMETRY_INTERVAL_MS; }
        bool up = !(t >= outFrom && t < outTo);
        bool open;
        if (oldGate) {
            open = !oldPending || (int32_t)(now - oldUntil) >= 0;
            if (up && open) oldPending = false;
            // the old loop did not look at the gate while the radio was down
            if (!up) open = false;
        } else {
            open = pgMayPost(&g, now);          // asked on every pass
            if (!up) open = false;
        }
        if (!haveBody || !open) continue;
        haveBody = false;
        if (failDay >= 0 && !failed && t >= (uint64_t)failDay * 86400000ull) {
            failed = true;
            if (oldGate) { oldPending = true; oldUntil = now + 5000; }
            else pgFailed(&g, now, backoffFailure(&b));
        } else {
            if (!oldGate) { pgSuccess(&g); backoffSuccess(&b); }
            uint32_t gap = (uint32_t)(now - lastPost) / 1000;
            if (gap > longest) longest = gap;
            lastPost = now;
        }
    }
    return longest;
}

static void testWifiOutages() {
    // a back-off pending when Wi-Fi drops, then outages of 1, 26 and 50 days. after the radio is
    // back the first post must follow within a few seconds
    const double outages[] = { 1.0, 26.0, 50.0 };
    for (double o : outages) {
        // failure on day 3, outage from the same day. the run goes 5 days past the outage's end.
        // the longest gap may be the outage plus a few seconds, never longer
        double days = 3.0 + o + 5.0;
        uint32_t gap = longestGapWithOutage(days, 3, 3, o, false);
        CHECK(gap <= (uint32_t)(o * 86400.0) + 12);
    }
    // the gate does not depend on the outage length: a pending back-off ends by its own wait
    PostGate g;
    pgInit(&g);
    pgFailed(&g, 1000, 5000);
    CHECK(!pgMayPost(&g, 3000));
    CHECK(pgMayPost(&g, 0x7FFFFFFFu + 1000u));        // aged by 2^31 ms
    pgFailed(&g, 1000, 5000);
    CHECK(pgMayPost(&g, (uint32_t)(1000u + 0xFFFFFFFFu)));         // aged by 2^32 - 1 ms
    // the old signed gate, not asked during an outage, is closed for a long time after a 26 day outage
    CHECK(longestGapWithOutage(40.0, 3, 3, 26.0, true) > 40ull * 86400 / 2);
}

static void testFaultTextWholeNames() {
    // every one of the 2,048 combinations: the text fits the row, ends with a whole code or a +.
    // it never holds half a code
    const char* codes[] = { "LOOP", "NOTMP", "MQ-2", "WARM", "TEMP", "PRB", "BRD", "PLN", "CTR", "NET", "SENS" };
    for (int m = 0; m < 2048; m++) {
        StatusInput i = none();
        i.resetLoop = m & 1;  i.noTemp = m & 2;  i.gasFault = m & 4;  i.gasWarm = m & 8;
        i.tempFault = m & 16; i.probeFault = m & 32; i.boardFault = m & 64; i.plainHttp = m & 128;
        i.counterRejected = m & 256; i.postFault = m & 512; i.otherFault = m & 1024;
        StatusResult r = decideStatus(i, false);
        CHECK(std::strlen(r.text) <= 17);
        if (m == 0) continue;
        // tokenise and compare each token with a code
        std::string t(r.text);
        CHECK(t.rfind("FAULT:", 0) == 0);
        size_t pos = 6;
        bool plus = false;
        while (pos < t.size()) {
            CHECK(t[pos] == ' ' || t[pos] == '+');
            if (t[pos] == '+') { plus = true; CHECK(pos + 1 == t.size()); break; }
            size_t end = t.find_first_of(" +", pos + 1);
            std::string tok = t.substr(pos + 1, end == std::string::npos ? std::string::npos : end - pos - 1);
            bool known = false;
            for (const char* c : codes) if (tok == c) known = true;
            CHECK(known);
            pos = end == std::string::npos ? t.size() : end;
        }
        // the most important code is always shown. TEMP is dropped when NOTMP is on
        if (i.resetLoop) CHECK(t.find("LOOP") != std::string::npos);
        else if (i.noTemp) CHECK(t.find("NOTMP") != std::string::npos);
        (void)plus;
    }
}

static void testForgiveAndGas() {
    SavedState s = sealed(0, 0);
    ssSetupBegin(&s, SETUP_BME280);
    ssSetupBootCheck(&s, 6);
    CHECK(s.strikes[SETUP_BME280] == 1);
    CHECK(!ssStrikeForgiveDue(1000, 1000 + SETUP_FORGIVE_MS - 1, SETUP_FORGIVE_MS));
    CHECK(ssStrikeForgiveDue(1000, 1000 + SETUP_FORGIVE_MS, SETUP_FORGIVE_MS));
    CHECK(ssStrikeForgiveDue(0xFFFFFF00u, (uint32_t)(0xFFFFFF00u + SETUP_FORGIVE_MS), SETUP_FORGIVE_MS));   // across the wrap
    CHECK(ssForgive(&s, SETUP_BME280) && s.strikes[SETUP_BME280] == 0 && ssValid(&s));
    CHECK(!ssForgive(&s, SETUP_BME280));
    // gas warm-up is saved and a cold start forgets it
    CHECK(s.gasWarmedUp == 0);
    ssNoteGasWarmed(&s);
    CHECK(s.gasWarmedUp == 1 && ssValid(&s));
    ssReset(&s);
    CHECK(s.gasWarmedUp == 0);
    // the judge is saved and loaded with its per-source counts and latches
    TempJudge j;
    tjInit(&j);
    j.count[TS_DS] = 2; j.latch[TS_BME] = true;
    SavedState t = sealed(0, 0);
    ssStoreJudge(&t, &j);
    ssSeal(&t);
    CHECK(ssValid(&t) && t.critCount[TS_DS] == 2 && t.latchMask == 1);
    TempJudge k;
    ssLoadJudge(&t, &k);
    CHECK(k.count[TS_DS] == 2 && k.latch[TS_BME] && !k.latch[TS_DS]);
}

int main() {
    testMailbox();
    testBackoff();
    testPostWatch();
    testStatusPrecedence();
    testStatusAlternation();
    testStatusFaultText();
    testStatusNewFaults();
    testSavedState();
    testResetLoop();
    testSetupProtection();
    testRestoreStep();
    testPostScheduleAcrossDays();
    testPostFreshness();
    testOtaPauseLimit();
    testWifiOutages();
    testFaultTextWholeNames();
    testForgiveAndGas();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
