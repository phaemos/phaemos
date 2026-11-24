/**
 * test_sensor_state.c - host test for the lost-sensor rule and line pacing
 *
 * the loop in run_tick() repeats the wiring in main.c (discard on a failed
 * read, the lost rule, the window, the zero line) with the same HAL-free
 * modules, so the rule can be checked without a board.  covers: one failed
 * read gives no zero line and no SENSOR_MISSING, five in a row give a zero
 * line every window period with it, the first complete window after the
 * sensor returns clears it, a discarded window while not lost sends no line
 * and the next line carries WINDOW_DROPPED, SEQ counts only lines sent and
 * a sensor that did not answer at start-up counts as lost.
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_sensor_state.c ../Core/Src/node_core.c ../Core/Src/sensor_state.c ../Core/Src/window_stats.c ../Core/Src/status.c -lm -o "${TMPDIR:-/tmp}/test_sensor_state" && "${TMPDIR:-/tmp}/test_sensor_state"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_sensor_state.c ../Core/Src/node_core.c ../Core/Src/sensor_state.c ../Core/Src/window_stats.c ../Core/Src/status.c -lm -o "${TMPDIR:-/tmp}/test_sensor_state_san" && "${TMPDIR:-/tmp}/test_sensor_state_san"
 */

#include "node_core.h"
#include "test_common.h"

static NodeCore    s_core;
static uint32_t    s_now;
static unsigned    s_seq;          /* lines sent */
static unsigned    s_zero_lines;
static unsigned    s_data_lines;
static uint8_t     s_last_st;
static int         s_recoveries;
static int         s_sample;       /* varies the data so a window is not stuck */
static unsigned    s_tick_now;
static unsigned    s_line_tick[1024];
static uint8_t     s_line_st[1024];
static unsigned    s_nlines;
static unsigned    s_rf;           /* failed reads as the firmware would count them */

#define SS (s_core.sensor)

static void start(bool init_ok)
{
    Node_Init(&s_core, init_ok, 0, 0);
    s_tick_now = 0; s_nlines = 0; s_rf = 0;
    s_now = 0; s_seq = s_zero_lines = s_data_lines = 0; s_last_st = 0; s_recoveries = 0; s_sample = 0;
}

static void record(void)
{
    s_seq++;
    Node_LineSent(&s_core);
    if (s_nlines < 1024) { s_line_tick[s_nlines] = s_tick_now; s_line_st[s_nlines] = s_last_st; s_nlines++; }
}

/* one 10 ms tick.  first_ok and second_ok say whether each attempt gave a good sample, first_ms how long the
 * first attempt took.  this is the sequence main.c runs: attempt, maybe a retry, Node_Tick, the data line when
 * a window completed, then the zero line when one is due.  returns 1 when a line was sent */
static int tick_full(bool first_ok, uint32_t first_ms, bool second_ok)
{
    int sent = 0;
    TickInput in = {0};
    TickOutput out;
    s_now += 10;
    s_tick_now++;
    in.now_ms = s_now;
    in.first_ok = first_ok;
    s_sample++;
    in.first_raw[0] = (int16_t)(s_sample * 7); in.first_raw[1] = (int16_t)(s_sample * 3); in.first_raw[2] = 16384;
    if (SensorState_ShouldRetry(first_ok, first_ms))
    {
        in.retried = true;
        in.second_ok = second_ok;
        in.second_raw[0] = (int16_t)(s_sample * 7); in.second_raw[1] = (int16_t)(s_sample * 3); in.second_raw[2] = 16384;
    }
    Node_Tick(&s_core, &in, &out);
    s_rf += out.failed_reads;
    if (out.recover) s_recoveries++;
    if (out.window_complete)
    {
        s_last_st = Status_Compose(&s_core.status, false, false, false, false);
        s_data_lines++; sent = 1;
        record();
        WinBuf_Clear(&s_core.win);
    }
    ZeroLine zl = Node_ZeroLineDue(&s_core);
    if (zl != ZERO_LINE_NONE)
    {
        s_last_st = Status_Compose(&s_core.status, zl == ZERO_LINE_MISSING, false, false, zl == ZERO_LINE_NO_DATA);
        s_zero_lines++; sent = 1;
        record();
    }
    return sent;
}

/* a tick that is good (ok) or fails quickly twice... kept simple: ok or a slow failure (a timeout, not retried) */
static int run_tick(bool ok) { return tick_full(ok, ok ? 1 : 20, false); }

static void run_good(unsigned n) { for (unsigned i = 0; i < n; i++) run_tick(true); }
static void run_bad(unsigned n)  { for (unsigned i = 0; i < n; i++) run_tick(false); }

int main(void)
{
    /* ---- healthy: one data line per 128 ticks, nothing else ---- */
    start(true);
    run_good(128 * 3);
    CHECK(s_data_lines == 3 && s_zero_lines == 0 && s_last_st == 0, "healthy run: 3 data lines, no zero line, ST 0");

    /* ---- one failed read: no zero line, no SENSOR_MISSING, then DROPPED ---- */
    start(true);
    run_good(50);
    run_bad(1);
    CHECK(!SS.lost && s_recoveries == 0, "one failed read does not make the sensor lost or start a recovery");
    run_good(128);
    CHECK(s_zero_lines == 0, "no zero line after one failed read (a full period later)");
    CHECK(s_data_lines == 1, "the next complete window sends one data line");
    CHECK((s_last_st & ST_SENSOR_MISSING) == 0, "that line has no SENSOR_MISSING");
    CHECK((s_last_st & ST_WINDOW_DROPPED) != 0, "that line carries WINDOW_DROPPED (ST %u)", s_last_st);
    CHECK(s_seq == 1, "SEQ counted only the line sent");
    run_good(128);
    CHECK(s_last_st == 0 && s_data_lines == 2, "the line after is clean again");

    /* ---- four failed reads in a row are still a glitch ---- */
    start(true);
    run_good(10);
    run_bad(4);
    CHECK(!SS.lost && s_recoveries == 0, "four failures in a row: not lost");
    run_good(1);
    run_bad(4);
    CHECK(!SS.lost, "a good read resets the failure count");
    run_good(128);

    /* ---- five in a row: lost, recovery, zero lines on the rhythm ---- */
    start(true);
    run_good(128);
    unsigned data_before = s_data_lines;
    run_bad(5);
    CHECK(SS.lost, "five failures in a row make the sensor lost");
    CHECK(s_recoveries == 1, "and trigger one recovery at the fifth");
    unsigned seq_before = s_seq;
    unsigned lines = 0;
    unsigned first_gap = 0;
    for (unsigned t = 1; t <= 128 * 4; t++)
    {
        if (run_tick(false)) { lines++; if (!first_gap) first_gap = t; }
    }
    CHECK(lines >= 3 && lines <= 4, "about one zero line per window period while lost (%u in 4 periods)", lines);
    CHECK(s_zero_lines == lines && s_data_lines == data_before, "all of them are zero lines");
    CHECK((s_last_st & ST_SENSOR_MISSING) != 0, "zero lines carry SENSOR_MISSING (ST %u)", s_last_st);
    CHECK(s_seq == seq_before + lines, "SEQ moves by one per zero line");
    CHECK(s_recoveries >= 3 && s_recoveries <= 6, "recoveries are paced once a second, not every 50 ms (%d in about 5 s)", s_recoveries);

    /* ---- recovery: the first complete window clears the flag ---- */
    {
        unsigned d0 = s_data_lines;
        unsigned good = 0;
        while (s_data_lines == d0 && good < 400)
        {
            if (good > 0 && !SS.lost) { CHECK(0, "lost cleared early at %u", good); }
            run_tick(true);
            good++;
        }
        CHECK(s_data_lines == d0 + 1, "a data line arrives after %u good samples", good);
        CHECK(!SS.lost, "the first complete window clears lost");
        CHECK((s_last_st & ST_SENSOR_MISSING) == 0, "and its line has no SENSOR_MISSING (ST %u)", s_last_st);
        unsigned zl = s_zero_lines;
        run_good(256);
        CHECK(s_zero_lines == zl, "no more zero lines once the data flows");
    }

    /* ---- sensor absent at start-up ---- */
    start(false);
    CHECK(SS.lost, "no answer at init counts as lost from the start");
    run_bad(128);
    CHECK(s_zero_lines == 1 && (s_last_st & ST_SENSOR_MISSING), "first zero line after one window period with SENSOR_MISSING");
    run_good(128);
    CHECK(s_data_lines == 1 && s_last_st == 0, "the sensor appears: a clean data line follows");

    /* ---- a gap while not lost: no line, DROPPED on the next ---- */
    start(true);
    run_good(100);
    run_bad(2);                 /* two failures, not five */
    unsigned s0 = s_seq;
    run_good(300);
    CHECK(s_zero_lines == 0, "a discarded window while not lost sends no zero line");
    CHECK(s_seq == s0 + 2 || s_seq == s0 + 3, "SEQ counts only the data lines sent (%u)", s_seq - s0);

    /* ---- NO_DATA: one read in ten fails, never five in a row ---- */
    {
        start(true);
        run_good(128);                           /* one good line at tick 128 */
        unsigned last_good = s_tick_now;
        unsigned n0 = s_nlines;
        for (unsigned i = 1; i <= 128 * 8; i++) run_tick((i % 10) != 0);
        CHECK(!SS.lost, "one in ten failing never makes the sensor lost");
        CHECK(s_nlines > n0, "lines keep coming (%u in 8 periods)", s_nlines - n0);
        unsigned first = s_line_tick[n0];
        CHECK(first - last_good <= 2 * 128, "first NO_DATA line %u ticks after the last good line (limit 256)", first - last_good);
        CHECK(s_line_st[n0] & ST_NO_DATA, "it has NO_DATA (ST %u)", s_line_st[n0]);
        CHECK((s_line_st[n0] & ST_SENSOR_MISSING) == 0, "and not SENSOR_MISSING");
        CHECK((s_line_st[n0] & ST_WINDOW_DROPPED) != 0, "and WINDOW_DROPPED (ST %u)", s_line_st[n0]);
        int periodic = 1;
        for (unsigned i = n0 + 1; i < s_nlines; i++)
        {
            if (s_line_tick[i] - s_line_tick[i - 1] != 128 || !(s_line_st[i] & ST_NO_DATA)) periodic = 0;
        }
        CHECK(periodic, "then one NO_DATA line every 128 ticks");
        CHECK(s_data_lines == 1, "no data line was sent meanwhile");
        CHECK(s_seq == s_nlines, "SEQ counts every line sent (%u lines, SEQ %u)", s_nlines, s_seq);
        /* a complete window clears it */
        unsigned d0 = s_data_lines;
        for (unsigned i = 0; i < 400 && s_data_lines == d0; i++) run_tick(true);
        CHECK(s_data_lines == d0 + 1, "a complete window sends a data line");
        CHECK((s_last_st & ST_NO_DATA) == 0, "that line clears NO_DATA (ST %u)", s_last_st);
        run_good(128);
        CHECK(s_last_st == 0, "and the line after is clean");
        CHECK(s_seq == s_nlines, "SEQ still without gaps (%u lines, SEQ %u)", s_nlines, s_seq);
    }

    /* ---- the node is never silent for more than two periods ---- */
    {
        start(true);
        unsigned maxgap = 0, prev = 0;
        for (unsigned i = 1; i <= 128 * 12; i++)
        {
            run_tick((i % 3) != 0);               /* a third of the reads fail */
            if (s_nlines && s_line_tick[s_nlines - 1] == s_tick_now) { unsigned g = s_tick_now - prev; if (g > maxgap) maxgap = g; prev = s_tick_now; }
        }
        CHECK(maxgap <= 256, "longest gap between lines with a third failing: %u ticks (limit 256)", maxgap);
    }

    /* ---- hand-over NO_DATA -> SENSOR_MISSING (five in a row while in NO_DATA) ---- */
    {
        start(true);
        run_good(128);
        for (unsigned i = 1; i <= 128 * 3; i++) run_tick((i % 10) != 0);
        unsigned n0 = s_nlines;
        CHECK(s_line_st[n0 - 1] & ST_NO_DATA, "in NO_DATA (ST %u)", s_line_st[n0 - 1]);
        run_bad(5);
        CHECK(SS.lost, "five failures in a row make it lost");
        for (unsigned i = 0; i < 128 * 2; i++) run_tick(false);
        unsigned last = s_nlines - 1;
        CHECK((s_line_st[last] & ST_SENSOR_MISSING) && !(s_line_st[last] & ST_NO_DATA),
              "lost takes precedence: SENSOR_MISSING without NO_DATA (ST %u)", s_line_st[last]);
        int never_both = 1;
        for (unsigned i = 0; i < s_nlines; i++) if ((s_line_st[i] & ST_SENSOR_MISSING) && (s_line_st[i] & ST_NO_DATA)) never_both = 0;
        CHECK(never_both, "never both bits on one line");
        CHECK(s_seq == s_nlines, "SEQ without gaps");
    }

    /* ---- hand-over SENSOR_MISSING -> data -> NO_DATA ---- */
    {
        start(false);                              /* lost from the start */
        run_bad(128 * 2);
        CHECK(s_line_st[s_nlines - 1] == ST_SENSOR_MISSING, "lost: SENSOR_MISSING only (ST %u)", s_line_st[s_nlines - 1]);
        unsigned d0 = s_data_lines;
        for (unsigned i = 0; i < 400 && s_data_lines == d0; i++) run_tick(true);
        CHECK(s_data_lines == d0 + 1 && !(s_last_st & ST_SENSOR_MISSING), "the sensor returns: the first complete window clears SENSOR_MISSING");
        unsigned n0 = s_nlines;
        for (unsigned i = 1; i <= 128 * 4; i++) run_tick((i % 10) != 0);
        CHECK(s_nlines > n0 && (s_line_st[n0] & ST_NO_DATA) && !(s_line_st[n0] & ST_SENSOR_MISSING),
              "then it turns flaky: NO_DATA without SENSOR_MISSING (ST %u)", s_line_st[n0]);
        CHECK(s_seq == s_nlines, "SEQ without gaps");
    }

    /* ---- failures at random, 2 per cent: some windows complete ---- */
    {
        /* a fixed pattern (every 50th) can never give a run of 128, so the failures are placed by a small
         * pseudo-random generator.  the chance of 128 good reads in a row is 0.98^128, about 7.5 per cent */
        start(true);
        uint32_t x = 12345;
        for (unsigned i = 1; i <= 128 * 200; i++)
        {
            x ^= x << 13; x ^= x >> 17; x ^= x << 5;
            run_tick((x % 50) != 0);
        }
        CHECK(s_data_lines >= 1, "2 per cent random failures still complete windows (%u data lines and %u zero lines in 200 periods)", s_data_lines, s_zero_lines);
        CHECK(s_seq == s_nlines, "SEQ without gaps");
    }

    /* ---- the state module on its own ---- */
    {
        SensorState ss;
        SensorState_Init(&ss, true, 0);
        SensorState_AddTicks(&ss, 255);
        CHECK(SensorState_ZeroLineDue(&ss) == ZERO_LINE_NONE, "255 ticks without a window: not yet NO_DATA");
        SensorState_AddTicks(&ss, 1);
        CHECK(SensorState_ZeroLineDue(&ss) == ZERO_LINE_NO_DATA, "256 ticks: NO_DATA due");
        SensorState_OnLineSent(&ss);
        SensorState_AddTicks(&ss, 127);
        CHECK(SensorState_ZeroLineDue(&ss) == ZERO_LINE_NONE, "127 ticks after that line: not due");
        SensorState_AddTicks(&ss, 1);
        CHECK(SensorState_ZeroLineDue(&ss) == ZERO_LINE_NO_DATA, "128 ticks after: due again");
        SensorState_OnWindowComplete(&ss);
        SensorState_OnLineSent(&ss);
        SensorState_AddTicks(&ss, 200);
        CHECK(SensorState_ZeroLineDue(&ss) == ZERO_LINE_NONE, "a window resets the NO_DATA clock");
        SensorState_AddTicks(&ss, 0xFFFFFFFFU);
        CHECK(SensorState_ZeroLineDue(&ss) == ZERO_LINE_NO_DATA, "tick counters saturate instead of wrapping");
    }

    /* ---- quick retry within the tick ---- */
    {
        CHECK(SensorState_ShouldRetry(false, 0) && SensorState_ShouldRetry(false, QUICK_FAIL_MAX_MS), "a failure that took up to %u ms is retried", QUICK_FAIL_MAX_MS);
        CHECK(!SensorState_ShouldRetry(false, QUICK_FAIL_MAX_MS + 1), "a failure that took %u ms is not retried", QUICK_FAIL_MAX_MS + 1);
        CHECK(!SensorState_ShouldRetry(false, 20), "a timeout (20 ms) is never retried");
        CHECK(!SensorState_ShouldRetry(true, 0), "a good read is not retried");
        CHECK(SensorState_FailedReads(true, false, false) == 0 && SensorState_FailedReads(false, true, true) == 1 &&
              SensorState_FailedReads(false, true, false) == 2 && SensorState_FailedReads(false, false, false) == 1,
              "RF counts 0 for a good read, 1 for retry-works or no retry, 2 for both failing");

        start(true);
        run_good(50);
        tick_full(false, 1, true);
        CHECK(s_core.win.count == 51, "quick failure then success keeps the window (%u samples)", s_core.win.count);
        CHECK(s_rf == 1, "and counts one failed read in RF (%u)", s_rf);
        CHECK(!s_core.status.dropped, "and drops nothing");
        run_good(77);
        CHECK(s_data_lines == 1 && s_last_st == 0, "the window completes on time with ST 0 (ST %u)", s_last_st);

        start(true);
        run_good(50);
        tick_full(false, 1, false);
        CHECK(s_core.win.count == 0 && s_core.status.dropped, "quick failure twice discards the window");
        CHECK(s_rf == 2, "and counts two failed reads in RF (%u)", s_rf);

        start(true);
        run_good(50);
        tick_full(false, 20, true);
        CHECK(s_core.win.count == 0 && s_rf == 1, "a slow failure is not retried: the window is discarded and RF is %u", s_rf);

        /* the lost rule counts failed ticks, not attempts */
        start(true);
        for (int i = 0; i < 4; i++) tick_full(false, 1, false);       /* 4 failed ticks, 8 failed attempts */
        CHECK(!SS.lost && s_recoveries == 0, "four failed ticks (eight failed attempts) are not lost");
        tick_full(false, 1, true);                                    /* a retry that works resets the run */
        for (int i = 0; i < 4; i++) tick_full(false, 1, false);
        CHECK(!SS.lost, "a retry that works resets the run: 4 + good + 4 is not lost");
        tick_full(false, 1, false);
        CHECK(SS.lost && s_recoveries == 1, "the fifth failed tick in a row is lost, with one recovery");

        /* 2 per cent failures per attempt: a tick fails only when both attempts do */
        start(true);
        uint32_t x = 2463534242u;
        unsigned periods = 400;
        for (unsigned i = 0; i < 128 * periods; i++)
        {
            x ^= x << 13; x ^= x >> 17; x ^= x << 5; bool a_ok = (x % 50) != 0;
            x ^= x << 13; x ^= x >> 17; x ^= x << 5; bool b_ok = (x % 50) != 0;
            tick_full(a_ok, a_ok ? 1 : 1, b_ok);
        }
        double expect = 0.95;           /* (1 - 0.02^2)^128 */
        double share = (double)s_data_lines / (double)periods;
        CHECK(share > 0.80 && share < 1.0, "2 per cent failures with the retry: %.0f per cent of periods completed a window (expected about %.0f)", share * 100, expect * 100);
        CHECK(s_rf > 128 * periods / 100 && s_rf < 128 * periods * 4 / 100, "RF still shows the flaky bus: %u failed reads in %u ticks (about 2 per cent)", s_rf, 128 * periods);
        CHECK(!SS.lost, "never lost");
    }

    /* ---- the lost flag clears: lost, then returns, through the same wiring main.c uses ---- */
    {
        start(true);
        run_good(128);
        for (int i = 0; i < 300; i++) run_tick(false);
        CHECK(SS.lost, "lost after a long run of failures");
        unsigned d0 = s_data_lines;
        for (unsigned i = 0; i < 128 && s_data_lines == d0; i++) run_tick(true);
        CHECK(s_data_lines == d0 + 1, "the sensor returns and a window completes");
        CHECK(!SS.lost, "the lost flag is clear after the first complete window");
        CHECK(s_core.sensor.ticks_since_window < 128, "and the no-data clock restarted");
    }

    TEST_FINISH();
}
