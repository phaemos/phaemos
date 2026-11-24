/**
 * sensor_state.h - when the sensor counts as lost and when a line is due
 *
 * no HAL header, so it builds on a host compiler.  one failed read is a bus
 * glitch and must not look like a lost sensor to the hub.  the sensor is
 * lost only after MAX_CONSECUTIVE_FAILURES failed reads in a row or when it
 * did not answer at start-up.  it stays lost until the first complete window
 * after it returns.  a zero-reading line is due once per window period
 * while the sensor is lost (SENSOR_MISSING).  when the sensor is not lost but
 * no window has completed for two periods (reads keep failing so no run of
 * 128 good reads forms) a zero-reading line is also due once per period
 * (NO_DATA).  lost takes precedence so the two are never reported together.
 * the node is never silent for more than two window periods.
 */

#ifndef SENSOR_STATE_H
#define SENSOR_STATE_H

#include <stdbool.h>
#include <stdint.h>
#include "fft.h"

/* failed reads in a row that make the sensor lost.  five reads is 50 ms:
 * long enough to ignore one corrupted transfer and short enough that a
 * wedged bus costs well under a window of data. */
#define MAX_CONSECUTIVE_FAILURES    5U

/* while the sensor stays lost, try to recover it once a second rather than
 * every 50 ms, so the bus is not pulsed and the recovery counter does not
 * climb 20 times a second. */
#define RECOVER_INTERVAL_MS         1000U

/* a failed read is retried once within the same tick when the first attempt
 * came back quickly, which means the bus answered with an error and did not
 * hang.  the limit is 2 ms of HAL tick (a 1 ms counter, so a read that
 * really took under 3 ms): a normal read takes about 1 ms and a timeout takes
 * 20 ms, so the two cannot be confused.  the retry gets a short timeout of
 * 3 ms.  first attempt under 3 ms plus retry of about 1 ms (3 ms at the
 * worst when it fails too) stays well inside the 10 ms tick and a timeout is
 * never retried. */
#define QUICK_FAIL_MAX_MS           2U
#define RETRY_TIMEOUT_MS            3U

/* true when a failed first attempt should be retried now */
bool SensorState_ShouldRetry(bool first_ok, uint32_t first_elapsed_ms);

/* the tick's sample is good when the first attempt was or the retry was */
bool SensorState_TickOk(bool first_ok, bool retried, bool second_ok);

/* failed reads to add to RF for this tick: 0 when the first attempt worked,
 * 1 when it failed and the retry worked or was not made, 2 when both failed */
uint8_t SensorState_FailedReads(bool first_ok, bool retried, bool second_ok);

typedef struct
{
    bool     lost;              /* the sensor is considered lost */
    uint8_t  consecutive_fail;  /* failed reads in a row, saturates at 255 */
    uint32_t ticks_since_line;  /* 100 Hz ticks since the last line was sent */
    uint32_t ticks_since_window;/* 100 Hz ticks since a window last completed */
    uint32_t last_recover_ms;   /* tick of the latest recovery attempt */
} SensorState;

/* init_ok is false when the sensor did not answer at start-up */
void SensorState_Init(SensorState *s, bool init_ok, uint32_t now_ms);

/* the lost-sensor rule counts failed TICKS in a row, not failed attempts: a tick
 * whose retry worked is a good tick and resets the run.  call OnRead once per
 * tick with the tick's final result. */

/* count ticks towards the line period (one per tick plus any missed ones) */
void SensorState_AddTicks(SensorState *s, uint32_t ticks);

/**
 * SensorState_OnRead: record the outcome of one read.
 * returns true when a bus recovery and sensor re-initialisation should run
 * now: at the fifth failure in a row, then once per RECOVER_INTERVAL_MS while
 * the failures continue.
 */
bool SensorState_OnRead(SensorState *s, bool ok, uint32_t now_ms);

/* a full window arrived, so the sensor is back */
void SensorState_OnWindowComplete(SensorState *s);

/* a line was sent, data or zero */
void SensorState_OnLineSent(SensorState *s);

/* no window for this many ticks (two periods) while not lost means NO_DATA */
#define NO_DATA_TICKS               (2U * FFT_SIZE)

typedef enum
{
    ZERO_LINE_NONE = 0,
    ZERO_LINE_MISSING,      /* lost: send zeros with SENSOR_MISSING */
    ZERO_LINE_NO_DATA       /* not lost but no window: send zeros with NO_DATA */
} ZeroLine;

/* which zero-reading line, if any, is due now.  at most one per window period
 * since the last line */
ZeroLine SensorState_ZeroLineDue(const SensorState *s);

#endif /* SENSOR_STATE_H */
