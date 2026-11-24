/**
 * sensor_state.c - lost-sensor rule and line pacing
 */

#include "sensor_state.h"

static uint32_t sat_add(uint32_t a, uint32_t b)
{
    return (a > (0xFFFFFFFFU - b)) ? 0xFFFFFFFFU : (a + b);
}

void SensorState_Init(SensorState *s, bool init_ok, uint32_t now_ms)
{
    s->lost             = !init_ok;
    s->consecutive_fail = 0U;
    s->ticks_since_line = 0U;
    s->ticks_since_window = 0U;
    s->last_recover_ms  = now_ms;
}

void SensorState_AddTicks(SensorState *s, uint32_t ticks)
{
    /* saturate so a very long silence cannot wrap the counters */
    s->ticks_since_line   = sat_add(s->ticks_since_line, ticks);
    s->ticks_since_window = sat_add(s->ticks_since_window, ticks);
}

bool SensorState_OnRead(SensorState *s, bool ok, uint32_t now_ms)
{
    if (ok)
    {
        s->consecutive_fail = 0U;
        return false;
    }

    if (s->consecutive_fail < 255U)
    {
        s->consecutive_fail++;
    }

    if (s->consecutive_fail < MAX_CONSECUTIVE_FAILURES)
    {
        return false;   /* a glitch: not lost, nothing to do */
    }

    s->lost = true;

    /* the fifth failure recovers at once, later ones wait out the interval */
    if ((s->consecutive_fail == MAX_CONSECUTIVE_FAILURES) ||
        ((now_ms - s->last_recover_ms) >= RECOVER_INTERVAL_MS))
    {
        s->last_recover_ms = now_ms;
        return true;
    }
    return false;
}

void SensorState_OnWindowComplete(SensorState *s)
{
    s->lost = false;
    s->ticks_since_window = 0U;
}

void SensorState_OnLineSent(SensorState *s)
{
    s->ticks_since_line = 0U;
}

ZeroLine SensorState_ZeroLineDue(const SensorState *s)
{
    if (s->ticks_since_line < FFT_SIZE)
    {
        return ZERO_LINE_NONE;
    }
    if (s->lost)
    {
        return ZERO_LINE_MISSING;
    }
    if (s->ticks_since_window >= NO_DATA_TICKS)
    {
        return ZERO_LINE_NO_DATA;
    }
    return ZERO_LINE_NONE;
}

bool SensorState_ShouldRetry(bool first_ok, uint32_t first_elapsed_ms)
{
    return (!first_ok) && (first_elapsed_ms <= QUICK_FAIL_MAX_MS);
}

bool SensorState_TickOk(bool first_ok, bool retried, bool second_ok)
{
    return first_ok || (retried && second_ok);
}

uint8_t SensorState_FailedReads(bool first_ok, bool retried, bool second_ok)
{
    if (first_ok)
    {
        return 0U;
    }
    if (retried && !second_ok)
    {
        return 2U;
    }
    return 1U;
}
