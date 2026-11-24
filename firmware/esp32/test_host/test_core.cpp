// test_core.cpp - host test of the hub core (outputs/hub_core.cpp): the order of setup() and the
// decisions of every reading pass, replayed as whole scenarios against a recording platform with an
// assertion on the outputs at every step. esp32.ino is the wiring that implements the platform, so
// what is proved here is the order and the decisions and not the pins.
//
// scenarios: cold boot, warm reset with the relay on, a sensor lost and returning, over-temperature
// on each source, gas alarm (digital and analogue), water alarm, a satellite link dying, Wi-Fi down
// for an hour and a reset loop with every reachable loop state.
//
// build and run from this folder, once for each board image:
//   c++ -std=c++17 -Wall -Wextra -I.. test_core.cpp ../outputs/hub_core.cpp ../outputs/temp_judge.cpp ../outputs/saved_state.cpp ../outputs/status_logic.cpp ../comms/post_queue.cpp -o "${TMPDIR:-/tmp}/test_core" && "${TMPDIR:-/tmp}/test_core"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_core.cpp ../outputs/hub_core.cpp ../outputs/temp_judge.cpp ../outputs/saved_state.cpp ../outputs/status_logic.cpp ../comms/post_queue.cpp -o "${TMPDIR:-/tmp}/test_core_san" && "${TMPDIR:-/tmp}/test_core_san"
//   c++ -std=c++17 -Wall -Wextra -DHAS_SENSOR_RAIL_SWITCH=1 -DHAS_INPUT_PULLDOWNS=1 -I.. test_core.cpp ../outputs/hub_core.cpp ../outputs/temp_judge.cpp ../outputs/saved_state.cpp ../outputs/status_logic.cpp ../comms/post_queue.cpp -o "${TMPDIR:-/tmp}/test_core_revb" && "${TMPDIR:-/tmp}/test_core_revb"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "../config.h"
#include "../outputs/hub_core.h"

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


// a recording platform. every call goes in the log in order
struct Fake : HubPlatform {
    std::vector<std::string> log;
    uint32_t now = 100;
    bool linesIdle = true;
    bool mcp = HAS_SENSOR_RAIL_SWITCH != 0;   // does 0x20 answer: the revised board has it
    bool other = true;           // does any other known device answer
    uint8_t mcpAnswersAfter = 0; // the expander answers only from this try on (0 means the first)
    uint8_t probes = 0;
    bool relay[4] = { false, false, false, false };
    bool gpio14Driven = false;
    HubStepIn scripted;

    Fake() { std::memset(&scripted, 0, sizeof scripted); scripted.temp.bme.trusted = true; scripted.temp.bme.tempC = 25; }
    void add(const std::string& s) { log.push_back(s); }
    int at(const std::string& s) const {
        for (size_t i = 0; i < log.size(); i++) if (log[i] == s) return (int)i;
        return -1;
    }
    int count(const std::string& s) const {
        int n = 0;
        for (auto& l : log) if (l == s) n++;
        return n;
    }

    void relayInitPins() override { add("relayInitPins"); }
    void armWatchdog() override { add("armWatchdog"); }
    void relaySet(uint8_t ch, bool on) override {
        relay[ch] = on;
        add(std::string("relay") + (char)('1' + ch) + (on ? "On" : "Off"));
    }
    void gpio14Release() override { add("gpio14Release"); gpio14Driven = false; }
    void gpio14DriveRelayLow() override { add("gpio14Drive"); gpio14Driven = true; }
    void delayMs(uint32_t ms) override { add("delay" + std::to_string(ms)); now += ms; }
    void i2cBegin() override { add("i2cBegin"); }
    bool i2cLinesIdle() override { add("linesIdle"); return linesIdle; }
    bool i2cProbe(uint8_t a) override {
        if (a == MCP23017_ADDR) {
            add("probe20");
            probes++;
            return mcp && probes > mcpAnswersAfter;
        }
        add("probeOther");
        return other;
    }
    void outputsInit() override { add("outputsInit"); }
    void startPostTask() override { add("startPostTask"); }
    void initSensors(const BootInfo&) override { add("initSensors"); }
    HubStepIn readAll() override { add("readAll"); scripted.nowMs = now; return scripted; }
    void applyOutputs(const HubStepOut&) override { add("applyOutputs"); }
    void splashAndBeeps(bool, bool) override { add("splash"); }
    void dropWatchdog() override { add("dropWatchdog"); }
    uint32_t nowMs() override { return now; }
};

static HubStepIn quiet(uint32_t now) {
    HubStepIn in;
    std::memset(&in, 0, sizeof in);
    in.nowMs = now;
    in.temp.bme.trusted = true;  in.temp.bme.tempC = 25;
    in.temp.ds.trusted = true;   in.temp.ds.tempC = 25;
    in.temp.mlx.trusted = true;  in.temp.mlx.tempC = 25;
    in.gasRaw = 300;
    in.moistureCounts = 3500;
    in.postOkCount = 1;
    return in;
}

static bool has(const char* text, const char* word) { return std::strstr(text, word) != nullptr; }

// every pass in a scenario is 5 s on
struct Run {
    HubCore core;
    SavedState rtc;
    Fake plat;
    uint32_t okCount = 1;
    Run() { ssReset(&rtc); }
    HubStepOut step(HubStepIn in) {
        plat.now += TELEMETRY_INTERVAL_MS;
        in.nowMs = plat.now;
        if (in.postOkCount == 1) in.postOkCount = okCount;
        return core.step(in);
    }
};

static void cold(Run& r) {
    r.core.init(&r.rtc);
    r.core.boot(r.plat, 1);          // power-on
}

static void testColdBootOrder() {
    Run r;
    cold(r);
    const Fake& p = r.plat;
    // the order of setup(): relays low and watchdog armed first
    CHECK(p.at("relayInitPins") == 0 && p.at("armWatchdog") == 1);
    // GPIO14 is released as a plain input, the rail start-up wait passes, only then the bus is used
    int rel = p.at("gpio14Release"), wait = p.at("delay" + std::to_string(SENSOR_RAIL_STARTUP_MS));
    int bus = p.at("i2cBegin"), idle = p.at("linesIdle"), mcp = p.at("probe20");
    CHECK(rel > 1 && wait > rel && bus > wait && idle > bus && mcp > idle);
    // the expander is probed several times when it does not answer, with the bus proven by another device
#if HAS_SENSOR_RAIL_SWITCH
    CHECK(p.count("probe20") == 1);                // it answered at once
#else
    CHECK(p.count("probe20") == BOARD_PROBE_TRIES);
    CHECK(p.count("probeOther") >= 1);
#endif
    // outputs and the post task come up before any sensor set-up, then the first judgement, then the splash
    int outs = p.at("outputsInit"), post = p.at("startPostTask"), init = p.at("initSensors");
    CHECK(outs > mcp && post > outs && init > post);
    int read = p.at("readAll"), apply = p.at("applyOutputs"), splash = p.at("splash"), drop = p.at("dropWatchdog");
    CHECK(read > init && apply > read && splash > apply && drop > splash);
    CHECK((int)p.log.size() == drop + 1);          // the run watchdog is last
    // GPIO14 is driven as relay 3 only on the present image with the present board proved
#if HAS_SENSOR_RAIL_SWITCH
    CHECK(!p.gpio14Driven && r.core.board() == BOARD_OK);
#else
    CHECK(p.gpio14Driven && r.core.board() == BOARD_OK);
    CHECK(p.at("gpio14Drive") > p.at("probe20"));
#endif
    CHECK(!r.core.resetLoop());
    // no relay was switched on a cold start
    for (int i = 0; i < 4; i++) CHECK(!p.relay[i]);
}

static void testBoardUnknown() {
    // the bus is held low: nothing can be believed, so GPIO14 is never driven
    {
        Run r; r.plat.linesIdle = false; r.plat.other = false; r.plat.mcp = false;
        cold(r);
        CHECK(r.core.board() == BOARD_UNKNOWN && !r.plat.gpio14Driven);
        // a retry on a bus that has come good proves the board
        r.plat.linesIdle = true; r.plat.other = true; r.plat.log.clear();
        r.core.recheckBoard(r.plat);
#if HAS_SENSOR_RAIL_SWITCH
        CHECK(r.core.board() == BOARD_MISMATCH && !r.plat.gpio14Driven);
#else
        CHECK(r.core.board() == BOARD_OK && r.plat.gpio14Driven);
#endif
        // and a verdict that is known is not probed again
        r.plat.log.clear();
        r.core.recheckBoard(r.plat);
        CHECK(r.plat.log.empty());
    }
    // nothing answers at all, even with idle lines: unknown, not a mismatch
    {
        Run r; r.plat.other = false; r.plat.mcp = false;
        cold(r);
        CHECK(r.core.board() == BOARD_UNKNOWN && !r.plat.gpio14Driven);
        HubStepOut o = r.step(quiet(0));
        CHECK(o.board == BOARD_UNKNOWN && has(o.status.text, "BRD"));
    }
    // the expander answers on the fourth try only: the repeat probes find it
    {
        Run r; r.plat.mcp = true; r.plat.mcpAnswersAfter = 3;
        cold(r);
        CHECK(r.plat.count("probe20") == 4);
#if HAS_SENSOR_RAIL_SWITCH
        CHECK(r.core.board() == BOARD_OK);
#else
        CHECK(r.core.board() == BOARD_MISMATCH && !r.plat.gpio14Driven);
#endif
    }
}

static void testWarmResetRelayOn() {
    // a hot machine, then a watchdog reset
    Run r;
    cold(r);
    HubStepIn hot = quiet(0);
    hot.temp.bme.tempC = 70;
    for (int i = 0; i < 3; i++) r.step(hot);
    CHECK(r.rtc.latchMask & 1);
    CHECK(r.rtc.relayMask & 1);
    // the reset: a new core and a new fake, the same RTC memory
    HubCore core2;
    Fake f2;
    f2.now = 100;
    f2.scripted.temp.bme.trusted = false;                 // the first judgement of the boot has no reading
    core2.init(&r.rtc);
    core2.boot(f2, 6);                                    // task watchdog
    // relay 1 is restored before GPIO14 is released and before the bus is touched
    int on1 = f2.at("relay1On");
    CHECK(on1 > 0 && on1 < f2.at("gpio14Release") && on1 < f2.at("i2cBegin"));
    CHECK(core2.info().verdict == RV_RESTORE);
    // the latch came back, so the first judgement with a trusted but cool reading does not
    // drop the cooling relay inside the hysteresis band
    HubStepIn warm = quiet(0);
    warm.temp.bme.tempC = 59;
    warm.nowMs = f2.now + 5000;
    HubStepOut o = core2.step(warm);
    CHECK(o.temp.critActive && o.relayCh1);
    CHECK(o.status.base == STK_CRITICAL);
    // a trusted reading clears the unconfirmed count
    CHECK(r.rtc.unconfirmed == 0);
    // relay 2 and 4 restored too, relay 3 follows the board verdict
    Run q;
    cold(q);
    q.rtc.relayMask = 0x0F;
    ssSeal(&q.rtc);
    HubCore core3; Fake f3;
    core3.init(&q.rtc);
    core3.boot(f3, 3);
    CHECK(f3.at("relay2On") > 0 && f3.at("relay4On") > 0 && f3.at("relay1On") > 0);
    int r3 = f3.at("relay3On");
#if HAS_SENSOR_RAIL_SWITCH
    CHECK(r3 > 0 && !f3.gpio14Driven);   // relay 3 is GPIO23 on the revised board. GPIO14 is never driven
#else
    CHECK(r3 > f3.at("gpio14Drive"));
#endif
    // a restore nothing confirms is dropped
    Run d;
    cold(d);
    for (int i = 0; i < 3; i++) d.step(hot);
    HubCore core4; Fake f4;
    f4.scripted.temp.bme.trusted = false;
    core4.init(&d.rtc);
    core4.boot(f4, 6);
    HubStepIn none = quiet(0);
    none.temp.bme.trusted = none.temp.ds.trusted = none.temp.mlx.trusted = false;
    bool dropped = false;
    for (int i = 0; i < 6 && !dropped; i++) {
        none.nowMs = f4.now + 5000 * (i + 1);
        dropped = core4.step(none).restoreDropped;
    }
    CHECK(dropped);
}

static void testSensorLostAndReturning() {
    Run r;
    cold(r);
    HubStepOut o = r.step(quiet(0));
    CHECK(o.status.base == STK_NORMAL && !o.temp.alarmUnavailable);
    // the BME280 is lost with the others still reading: a fault is shown, there is still an alarm
    HubStepIn in = quiet(0);
    in.temp.bme.trusted = false;
    in.bmeFault = true;
    o = r.step(in);
    CHECK(o.status.base == STK_FAULT && has(o.status.text, "TEMP") && !o.temp.alarmUnavailable);
    // every source lost: the alarm is not available and the panel says so
    in.temp.ds.trusted = false; in.temp.mlx.trusted = false;
    o = r.step(in);
    CHECK(o.temp.alarmUnavailable && has(o.status.text, "NOTMP") && !has(o.status.text, "TEMP "));
    // it returns
    o = r.step(quiet(0));
    CHECK(o.status.base == STK_NORMAL && !o.temp.alarmUnavailable);
    // lost while critical: held, the relay stays on and the panel says critical
    HubStepIn hot = quiet(0);
    hot.temp.bme.tempC = 70;
    for (int i = 0; i < 3; i++) o = r.step(hot);
    CHECK(o.temp.critActive && o.relayCh1 && o.status.base == STK_CRITICAL);
    in = quiet(0);
    in.temp.bme.trusted = false; in.bmeFault = true;     // lost, with the others cool
    for (int i = 0; i < 20; i++) o = r.step(in);
    CHECK(o.temp.critActive && o.relayCh1 && o.status.base == STK_CRITICAL && o.status.shown == STK_CRITICAL);
    // back and cool
    o = r.step(quiet(0));
    CHECK(!o.temp.critActive && !o.relayCh1);
}

static void testOverTemperaturePerSource() {
    for (int src = 0; src < 3; src++) {
        Run r;
        cold(r);
        HubStepOut o;
        for (int pass = 1; pass <= 3; pass++) {
            HubStepIn in = quiet(0);
            float* t = src == 0 ? &in.temp.bme.tempC : (src == 1 ? &in.temp.ds.tempC : &in.temp.mlx.tempC);
            *t = 70;
            o = r.step(in);
            // critical only on the third confirmed reading, from this source alone. the others are cool
            CHECK(o.temp.critActive == (pass >= 3));
            CHECK(o.relayCh1 == (pass >= 3));
            CHECK(o.status.base == (pass >= 3 ? STK_CRITICAL : (src == 0 ? STK_WARNING : STK_NORMAL)));
        }
        CHECK(has(o.status.text, "CRITICAL"));
        // inside the hysteresis band: still critical
        HubStepIn in = quiet(0);
        float lim = (float)TEMP_CRITICAL_C;
        float* t = src == 0 ? &in.temp.bme.tempC : (src == 1 ? &in.temp.ds.tempC : &in.temp.mlx.tempC);
        *t = lim - 1;
        o = r.step(in);
        CHECK(o.temp.critActive && o.relayCh1);
        // another source reading cool does not clear it, whatever it reads
        *t = 70;
        for (int i = 0; i < 5; i++) o = r.step(in);
        CHECK(o.temp.critActive);
        // clear on its own reading
        *t = lim - (float)TEMP_HYSTERESIS_C - 1;
        o = r.step(in);
        CHECK(!o.temp.critActive && !o.relayCh1 && o.status.base != STK_CRITICAL);
    }
    // two sources hot, one clears: still critical
    Run r;
    cold(r);
    HubStepIn in = quiet(0);
    in.temp.bme.tempC = 70; in.temp.ds.tempC = 70;
    HubStepOut o;
    for (int i = 0; i < 3; i++) o = r.step(in);
    CHECK(o.temp.critActive);
    in.temp.bme.tempC = 25;
    o = r.step(in);
    CHECK(o.temp.critActive && o.relayCh1);
    in.temp.ds.tempC = 25;
    o = r.step(in);
    CHECK(!o.temp.critActive);
}

static void testGasAlarm() {
    Run r;
    cold(r);
    HubStepIn in = quiet(0);
    in.gasWarming = true;
    HubStepOut o = r.step(in);
    // warming up: no alarm, a fault word
    CHECK(!o.gasAlert && has(o.status.text, "WARM") && o.status.base == STK_FAULT);
    in.gasWarming = false;
    in.gasDigitalLow = true;
    in.gasRaw = 1000;                                     // digital path alone
    o = r.step(in);
    CHECK(o.gasAlert && o.status.base == STK_WARNING && !o.gasDisagree && r.rtc.gasWarmedUp == 1);
    in.gasDigitalLow = false;
    in.gasRaw = GAS_ANALOGUE_ALARM_COUNTS;                // analogue path alone
    o = r.step(in);
    CHECK(o.gasAlert && o.status.base == STK_WARNING);
    in.gasRaw = 300;
    o = r.step(in);
    CHECK(!o.gasAlert && o.status.base == STK_NORMAL);
    // disagreement: the digital line alarms on a clean analogue level. the alarm stays and a fault shows
    in.gasDigitalLow = true;
    o = r.step(in);
    HubStepOut o2 = r.step(in);                           // the warning and the fault alternate
    CHECK(o.gasAlert && o.gasDisagree);
    CHECK(has(o.status.text, "MQ-2") || has(o2.status.text, "MQ-2"));
    // a dead module: near zero is a fault and no alarm
    in.gasRaw = 0;
    o = r.step(in);
    CHECK(!o.gasAlert && o.gasFault && has(o.status.text, "MQ-2"));
    // a warm reset after the warm-up skips it. one inside the warm-up does not
    HubCore c2; Fake f2;
    c2.init(&r.rtc);
    c2.boot(f2, 6);
    CHECK(c2.info().gasSkipWarmup);
    Run fresh;
    cold(fresh);
    fresh.step(in);                                       // an early pass, still warming
    SavedState early;
    ssReset(&early);
    HubCore c3; Fake f3;
    c3.init(&early);
    c3.boot(f3, 6);
    CHECK(!c3.info().gasSkipWarmup);
}

static void testWaterAlarm() {
    Run r;
    cold(r);
    HubStepIn in = quiet(0);
    in.moistureCounts = WATER_THRESHOLD - 1;
    HubStepOut o = r.step(in);
    CHECK(o.waterAlarm && o.status.base == STK_WARNING && has(o.status.text, "WARNING"));
    in.moistureCounts = WATER_THRESHOLD;
    o = r.step(in);
    CHECK(!o.waterAlarm && o.status.base == STK_NORMAL);
    // a warning and a fault alternate and neither hides the other
    in.moistureCounts = 100;
    in.otherFault = true;
    HubStepOut a = r.step(in), b = r.step(in);
    CHECK(a.status.shown != b.status.shown);
    CHECK((a.status.shown == STK_WARNING && b.status.shown == STK_FAULT) ||
          (b.status.shown == STK_WARNING && a.status.shown == STK_FAULT));
    // critical wins and never alternates
    HubStepIn hot = in;
    hot.temp.bme.tempC = 70;
    HubStepOut c;
    for (int i = 0; i < 3; i++) c = r.step(hot);
    HubStepOut c2 = r.step(hot);
    CHECK(c.status.shown == STK_CRITICAL && c2.status.shown == STK_CRITICAL);
}

static void testSatelliteLinkDying() {
    Run r;
    cold(r);
    HubStepOut o = r.step(quiet(0));
    CHECK(o.status.base == STK_NORMAL);
    HubStepIn in = quiet(0);
    in.otherFault = true;                                 // a satellite link has gone silent
    o = r.step(in);
    CHECK(o.status.base == STK_FAULT && has(o.status.text, "SENS") && !o.relayCh1);
    // the link comes back
    o = r.step(quiet(0));
    CHECK(o.status.base == STK_NORMAL);
}

static void testWifiDownAnHour() {
    Run r;
    cold(r);
    HubStepIn in = quiet(0);
    HubStepOut o;
    uint32_t t0 = r.plat.now;
    bool sawNet = false;
    int firstNet = -1;
    // 720 passes of 5 s is one hour, with no post succeeding
    for (int i = 0; i < 720; i++) {
        in.postOkCount = r.okCount;
        o = r.step(in);
        if (has(o.status.text, "NET") && !sawNet) { sawNet = true; firstNet = i; }
        // the cooling alarm is unaffected by the network
        CHECK(!o.relayCh1);
    }
    CHECK(sawNet);
    // the fault shows once POST_STALE_MS has passed and not before
    uint32_t at = (uint32_t)(firstNet + 1) * TELEMETRY_INTERVAL_MS;
    CHECK(at >= POST_STALE_MS - 2 * TELEMETRY_INTERVAL_MS && at <= POST_STALE_MS + 2 * TELEMETRY_INTERVAL_MS);
    CHECK(o.postStale && o.status.base == STK_FAULT);
    // over-temperature during the outage still goes critical
    HubStepIn hot = in;
    hot.temp.bme.tempC = 70;
    for (int i = 0; i < 3; i++) o = r.step(hot);
    CHECK(o.status.base == STK_CRITICAL && o.relayCh1);
    // a post succeeds and the fault clears
    r.okCount++;
    in.postOkCount = r.okCount;
    o = r.step(quiet(0));
    (void)t0;
    o = r.step([&] { HubStepIn q = quiet(0); q.postOkCount = r.okCount; return q; }());
    CHECK(!o.postStale);
}

// the loop: every reachable state
static void testResetLoop() {
    // consecutive warm resets with no trusted reading: restore, restore, then refuse
    SavedState rtc;
    ssReset(&rtc);
    rtc.relayMask = 1;
    rtc.latchMask = 1;
    ssSeal(&rtc);
    int verdicts[6];
    for (int i = 0; i < 6; i++) {
        HubCore c; Fake f;
        f.scripted.temp.bme.trusted = false;
        c.init(&rtc);
        c.boot(f, 6);
        verdicts[i] = (int)c.info().verdict;
        // the saved state is written by step. here no step has run, so the record only keeps the count
        CHECK(ssValid(&rtc));
        if (i >= RESTORE_MAX_UNCONFIRMED) {
            CHECK(c.resetLoop() && c.info().verdict == RV_REFUSE);
            // the relay takes its no-information state and the panel says LOOP
            CHECK(f.relay[0] == (COOLING_RELAY_NO_INFO_ON != 0));
        }
    }
    CHECK(verdicts[0] == RV_RESTORE && verdicts[1] == RV_RESTORE && verdicts[2] == RV_REFUSE);
    // the same loop with every relay state and every latch state: warm resets are counted whatever
    // the relay was doing
    for (int relays = 0; relays < 16; relays++) {
        for (int latch = 0; latch < 8; latch++) {
            SavedState s;
            ssReset(&s);
            s.relayMask = (uint8_t)relays;
            s.latchMask = (uint8_t)latch;
            ssSeal(&s);
            for (int boot = 0; boot < 4; boot++) {
                HubCore c; Fake f;
                f.scripted.temp.bme.trusted = false;
                c.init(&s);
                c.boot(f, boot % 2 ? 4 : 6);
                bool loop = boot >= RESTORE_MAX_UNCONFIRMED;
                CHECK(c.resetLoop() == loop);
                CHECK((c.info().verdict == RV_REFUSE) == loop);
                // in a loop the first pass shows LOOP, even with nothing on before
                HubStepIn in = quiet(0);
                in.temp.bme.trusted = in.temp.ds.trusted = in.temp.mlx.trusted = false;
                in.nowMs = f.now + 5000;
                HubStepOut o = c.step(in);
                if (loop) {
                    CHECK(o.resetLoop && has(o.status.text, "LOOP") && o.status.base == STK_FAULT);
                    CHECK(o.relayCh1 == (COOLING_RELAY_NO_INFO_ON != 0));
                } else {
                    CHECK(!o.resetLoop);
                }
                // the record is written, with the per-source state, every pass
                CHECK(ssValid(&s));
            }
        }
    }
    // a trusted reading ends the loop and the count. the relay stays on while a source is still pending
    SavedState s;
    ssReset(&s);
    s.unconfirmed = 5;
    ssSeal(&s);
    HubCore c; Fake f;
    c.init(&s);
    c.boot(f, 6);
    CHECK(c.info().verdict == RV_REFUSE);
    // the boot's own first judgement had a trusted reading (the fake default), so the loop ended there
    CHECK(s.unconfirmed == 0);
    // a loop with no trusted reading stays a loop, whatever the time
    SavedState s2;
    ssReset(&s2);
    s2.unconfirmed = 5;
    ssSeal(&s2);
    HubCore c2; Fake f2;
    f2.scripted.temp.bme.trusted = false;
    c2.init(&s2);
    c2.boot(f2, 6);
    CHECK(c2.resetLoop());
    HubStepIn in = quiet(0);
    in.temp.bme.trusted = in.temp.ds.trusted = in.temp.mlx.trusted = false;
    for (int i = 1; i <= 50; i++) {
        in.nowMs = f2.now + 5000u * i;
        HubStepOut o = c2.step(in);
        CHECK(o.resetLoop && has(o.status.text, "LOOP"));
    }
    in = quiet(f2.now + 400000);
    HubStepOut o = c2.step(in);
    CHECK(!o.resetLoop && !has(o.status.text, "LOOP") && s2.unconfirmed == 0);
    // a cold start gives a clean record
    SavedState s3;
    std::memset(&s3, 0xA5, sizeof s3);
    HubCore c3; Fake f3;
    c3.init(&s3);
    c3.boot(f3, 1);
    CHECK(!c3.resetLoop() && c3.info().verdict == RV_NONE);
    // a damaged record on a warm reset is a cold start: nothing restored, nothing counted
    SavedState s4;
    ssReset(&s4);
    s4.relayMask = 1;
    s4.latchMask = 1;
    ssSeal(&s4);
    s4.check ^= 1;
    HubCore c4; Fake f4;
    f4.scripted.temp.bme.trusted = false;
    c4.init(&s4);
    c4.boot(f4, 6);
    CHECK(c4.info().verdict == RV_NONE && !c4.resetLoop() && s4.unconfirmed == 0 && s4.relayMask == 0);
    CHECK(f4.count("relay1On") == 0);
}

// a key the backend rejects shows NET at once and plain HTTP shows PLN and neither touches the alarms
static void testPostFaults() {
    Run r;
    cold(r);
    HubStepIn in = quiet(0);
    HubStepOut o = r.step(in);
    CHECK(o.status.base == STK_NORMAL);
    in.postRejected = true;
    o = r.step(in);
    CHECK(o.status.base == STK_FAULT && has(o.status.text, "NET") && !o.postStale);
    in.postRejected = false;
    o = r.step(in);
    CHECK(o.status.base == STK_NORMAL);
    in.counterRejected = true;
    o = r.step(in);
    CHECK(o.status.base == STK_FAULT && has(o.status.text, "CTR"));
    in.counterRejected = false;
    o = r.step(in);
    CHECK(o.status.base == STK_NORMAL);
    in.plainHttp = true;
    o = r.step(in);
    CHECK(o.status.base == STK_FAULT && has(o.status.text, "PLN"));
    // over-temperature in either state is still critical and still switches the relay
    in.temp.bme.tempC = 70;
    in.postRejected = true;
    for (int i = 0; i < 3; i++) o = r.step(in);
    CHECK(o.status.base == STK_CRITICAL && o.relayCh1);
}

int main() {
    testColdBootOrder();
    testBoardUnknown();
    testWarmResetRelayOn();
    testSensorLostAndReturning();
    testOverTemperaturePerSource();
    testGasAlarm();
    testWaterAlarm();
    testSatelliteLinkDying();
    testWifiDownAnHour();
    testPostFaults();
    testResetLoop();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
