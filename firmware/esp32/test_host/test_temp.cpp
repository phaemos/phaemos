// test_temp.cpp - host test for the over-temperature judgement in outputs/temp_judge.cpp. each
// temperature source has its own count and latch. the tests cover the review's sequences (a cool
// second sensor must never cancel a hot one), the clear rule with its hysteresis, the junk limit,
// untrusted passes, the saved latch mask and a model check over every three-source combination
// and random runs against an independent per-source model.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_temp.cpp ../outputs/temp_judge.cpp -o "${TMPDIR:-/tmp}/test_temp" && "${TMPDIR:-/tmp}/test_temp"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_temp.cpp ../outputs/temp_judge.cpp -o "${TMPDIR:-/tmp}/test_temp_san" && "${TMPDIR:-/tmp}/test_temp_san"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "../config.h"
#include "../outputs/temp_judge.h"

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

static const float X = -999.0f;   // untrusted
struct P { float b; float d; float m; bool over; };

static TempInputs mk(const P& p) {
    TempInputs in;
    memset(&in, 0, sizeof in);
    in.bme.trusted = p.b != X; in.bme.tempC = p.b == X ? 0.0f : p.b;
    in.ds.trusted  = p.d != X; in.ds.tempC  = p.d == X ? 0.0f : p.d;
    in.mlx.trusted = p.m != X; in.mlx.tempC = p.m == X ? 0.0f : p.m;
    in.bmeOverRange = p.over;
    return in;
}

// runs a sequence and returns how many passes had critical on. last is the final verdict
static int run(TempJudge* j, const std::vector<P>& seq, TempVerdict* last = nullptr) {
    int on = 0;
    for (const P& p : seq) {
        TempVerdict v = tjStep(j, mk(p));
        if (v.critActive) on++;
        if (last) *last = v;
    }
    return on;
}

// the first pass index at which critical turns on or -1
static int firstOn(const std::vector<P>& seq) {
    TempJudge j; tjInit(&j);
    for (size_t i = 0; i < seq.size(); i++) {
        if (tjStep(&j, mk(seq[i])).critActive) return (int)i;
    }
    return -1;
}

static void testSequences() {
    TempJudge j; TempVerdict v;
    std::vector<P> s;

    // A: BME280 alone at 70, one reading in three dropped. untrusted passes change nothing, so it latches
    tjInit(&j); s.clear();
    for (int i = 0; i < 12; i++) s.push_back({ i % 3 == 2 ? X : 70.0f, X, X, false });
    run(&j, s, &v);
    CHECK(v.critActive);

    // B: the same with a healthy DS18B20 at 30. the cool sensor must not cancel the hot one
    tjInit(&j); s.clear();
    for (int i = 0; i < 12; i++) s.push_back({ i % 3 == 2 ? X : 70.0f, 30.0f, X, false });
    run(&j, s, &v);
    CHECK(v.critActive);
    CHECK(j.latch[TS_BME] && !j.latch[TS_DS]);

    // C: BME280 on alternate passes with DS18B20 30 and MLX90614 35 healthy
    tjInit(&j); s.clear();
    for (int i = 0; i < 12; i++) s.push_back({ i % 2 == 1 ? X : 70.0f, 30.0f, 35.0f, false });
    run(&j, s, &v);
    CHECK(v.critActive);

    // D: critical confirmed, then the BME280 is lost for good with no other source. held
    tjInit(&j); s.clear();
    for (int i = 0; i < 4; i++) s.push_back({ 70.0f, X, X, false });
    for (int i = 0; i < 40; i++) s.push_back({ X, X, X, false });
    run(&j, s, &v);
    CHECK(v.critActive && v.alarmUnavailable);

    // E: critical confirmed, then the BME280 is lost while the DS18B20 reads 30. the DS18B20's
    // reading is under its own threshold but it is not the source that latched, so it clears nothing
    tjInit(&j); s.clear();
    for (int i = 0; i < 4; i++) s.push_back({ 70.0f, 30.0f, X, false });
    for (int i = 0; i < 40; i++) s.push_back({ X, 30.0f, X, false });
    run(&j, s, &v);
    CHECK(v.critActive);

    // F: 70, 70, then over range twice (counts), then above the junk limit (untrusted) with DS 30
    tjInit(&j); s.clear();
    s.push_back({ 70, 30, X, false }); s.push_back({ 70, 30, X, false });
    s.push_back({ X, 30, X, true });   s.push_back({ X, 30, X, true });
    for (int i = 0; i < 10; i++) s.push_back({ X, 30, X, false });
    run(&j, s, &v);
    CHECK(v.critActive);                 // a junk reading does not clear the latch
    CHECK(firstOn(s) == 2);              // 70, 70, over range is the third count

    // G: BME280 at 70 dropping one in four with DS18B20 30
    tjInit(&j); s.clear();
    for (int i = 0; i < 16; i++) s.push_back({ i % 4 == 3 ? X : 70.0f, 30.0f, X, false });
    run(&j, s, &v);
    CHECK(v.critActive);

    // H: two readings, a gap, then one at 61 (over by 1). the count is held across the gap
    tjInit(&j); s.clear();
    s.push_back({ 70, X, X, false }); s.push_back({ 70, X, X, false });
    for (int i = 0; i < 3; i++) s.push_back({ X, X, X, false });
    s.push_back({ 61, X, X, false });
    run(&j, s, &v);
    CHECK(v.critActive);

    // the cool DS18B20 and MLX90614 reading under their own limits never lower the BME280's count
    tjInit(&j);
    tjStep(&j, mk({ 70, 30, 30, false }));
    tjStep(&j, mk({ 70, 30, 30, false }));
    CHECK(j.count[TS_BME] == 2);
    tjStep(&j, mk({ X, 30, 30, false }));
    CHECK(j.count[TS_BME] == 2);
    CHECK(tjStep(&j, mk({ 70, 30, 30, false })).critActive);
}

static void testClearRule() {
    TempJudge j;
    std::vector<P> hot;
    for (int i = 0; i < 4; i++) hot.push_back({ 70, X, X, false });

    // a latch clears only below the threshold less the hysteresis
    tjInit(&j); run(&j, hot);
    TempVerdict v = tjStep(&j, mk({ 59.0f, X, X, false }));      // under 60 but inside the 2 degC band
    CHECK(v.critActive);
    v = tjStep(&j, mk({ 58.5f, X, X, false }));
    CHECK(v.critActive);
    v = tjStep(&j, mk({ 57.9f, X, X, false }));
    CHECK(!v.critActive);

    // each source clears its own latch only. the BME280 latch is not cleared by a cool DS18B20
    tjInit(&j); run(&j, hot);
    for (int i = 0; i < 20; i++) v = tjStep(&j, mk({ X, 20.0f, 20.0f, false }));
    CHECK(v.critActive);
    // with two latches set, clearing one leaves critical
    tjInit(&j);
    for (int i = 0; i < 4; i++) tjStep(&j, mk({ 70, 70, X, false }));
    CHECK(j.latch[TS_BME] && j.latch[TS_DS]);
    v = tjStep(&j, mk({ 20, 70, X, false }));
    CHECK(!j.latch[TS_BME] && j.latch[TS_DS] && v.critActive);
    v = tjStep(&j, mk({ 20, 20, X, false }));
    CHECK(!v.critActive);

    // a reading past the junk limit while latched does not clear it (the wiring marks it untrusted)
    tjInit(&j); run(&j, hot);
    for (int i = 0; i < 10; i++) v = tjStep(&j, mk({ X, X, X, false }));
    CHECK(v.critActive && v.alarmUnavailable);

    // an over-range reading is never a clearing reading for the BME280
    tjInit(&j); run(&j, hot);
    v = tjStep(&j, mk({ X, X, X, true }));
    CHECK(v.critActive && j.count[TS_BME] >= 3);

    // each source has its own limit
    tjInit(&j);
    for (int i = 0; i < 4; i++) tjStep(&j, mk({ X, X, (float)TEMP_CRITICAL_MLX_C + 1, false }));
    CHECK(j.latch[TS_MLX] && !j.latch[TS_BME] && !j.latch[TS_DS]);
}

static void testSaveAndRestore() {
    TempJudge a, b;
    tjInit(&a);
    for (int i = 0; i < 4; i++) tjStep(&a, mk({ 70, X, 70, false }));
    tjStep(&a, mk({ X, 70, X, false }));
    uint8_t mask = tjLatchMask(&a);
    CHECK(mask == ((1u << TS_BME) | (1u << TS_MLX)));
    tjRestore(&b, a.count, mask);
    for (int i = 0; i < TS_COUNT; i++) {
        CHECK(a.count[i] == b.count[i]);
        CHECK(a.latch[i] == b.latch[i]);
    }
    CHECK(tjPending(&b));
    // the restored latches clear on the right source only
    TempVerdict v = tjStep(&b, mk({ 20, X, X, false }));
    CHECK(v.critActive && !b.latch[TS_BME] && b.latch[TS_MLX]);
    tjClear(&b);
    CHECK(!tjPending(&b));
}

static void testWarnAndUnavailable() {
    TempJudge j; tjInit(&j);
    TempVerdict v = tjStep(&j, mk({ X, X, X, false }));
    CHECK(v.alarmUnavailable && !v.critActive && !v.anyTrusted);
    v = tjStep(&j, mk({ 20, X, X, false }));
    CHECK(!v.alarmUnavailable && v.anyTrusted && !v.warnActive);
    v = tjStep(&j, mk({ (float)TEMP_WARNING_C + 1, X, X, false }));
    CHECK(v.warnActive && !v.critActive);
    v = tjStep(&j, mk({ (float)TEMP_WARNING_C - 1, X, X, false }));
    CHECK(v.warnActive);                 // inside the hysteresis band
    v = tjStep(&j, mk({ (float)TEMP_WARNING_C - 3, X, X, false }));
    CHECK(!v.warnActive);
    v = tjStep(&j, mk({ X, 90, 90, false }));
    CHECK(!v.warnActive);                // only the BME280 warns
}

// an independent model of the rules, run against random sequences and against every combination
struct Model {
    int count[3] = { 0, 0, 0 };
    bool latch[3] = { false, false, false };
};
static void modelStep(Model* m, const P& p) {
    const float lim[3] = { (float)TEMP_CRITICAL_C, (float)TEMP_CRITICAL_DS18_C, (float)TEMP_CRITICAL_MLX_C };
    float t[3] = { p.b, p.d, p.m };
    for (int i = 0; i < 3; i++) {
        bool trusted = t[i] != X || (i == 0 && p.over);
        if (!trusted) continue;
        bool over = (i == 0 && p.over) || (t[i] != X && t[i] > lim[i]);
        if (over) {
            m->count[i]++;
            if (m->count[i] >= CRITICAL_CONFIRM_READINGS) m->latch[i] = true;
        } else {
            m->count[i] = 0;
            if (t[i] < lim[i] - (float)TEMP_HYSTERESIS_C) m->latch[i] = false;
        }
    }
}

static void testAgainstModel() {
    const float levels[] = { X, 20.0f, 59.0f, 61.0f, 90.0f };
    // every single pass from every state reachable in four passes is too many for the full
    // product, so run a million random steps in runs of 30 and compare after each
    srand(12345);
    for (int run = 0; run < 40000; run++) {
        TempJudge j; tjInit(&j);
        Model m;
        for (int n = 0; n < 30; n++) {
            P p = { levels[rand() % 5], levels[rand() % 5], levels[rand() % 5], (rand() % 9) == 0 };
            if (p.over) p.b = X;                      // over range is only ever seen with no trusted value
            TempVerdict v = tjStep(&j, mk(p));
            modelStep(&m, p);
            bool any = m.latch[0] || m.latch[1] || m.latch[2];
            CHECK(v.critActive == any);
            for (int i = 0; i < 3; i++) CHECK(j.latch[i] == m.latch[i]);
            // a cool pass from another source never lowered a count
            for (int i = 0; i < 3; i++) CHECK(j.count[i] == m.count[i] || (j.count[i] == 255));
        }
    }
    // every combination of the three sources over five levels, from a hot start and a cold start
    for (int a = 0; a < 5; a++) for (int b = 0; b < 5; b++) for (int c = 0; c < 5; c++) for (int o = 0; o < 2; o++) {
        for (int start = 0; start < 2; start++) {
            TempJudge j; tjInit(&j);
            Model m;
            if (start) {
                for (int k = 0; k < 4; k++) { P h = { 70, 70, 70, false }; tjStep(&j, mk(h)); modelStep(&m, h); }
            }
            P p = { levels[a], levels[b], levels[c], o == 1 };
            if (p.over) p.b = X;
            TempVerdict v = tjStep(&j, mk(p));
            modelStep(&m, p);
            CHECK(v.critActive == (m.latch[0] || m.latch[1] || m.latch[2]));
        }
    }
}

int main() {
    testSequences();
    testClearRule();
    testSaveAndRestore();
    testWarnAndUnavailable();
    testAgainstModel();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed == 0 ? 0 : 1;
}
