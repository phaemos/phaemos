/**
 * uptime.c - seconds since boot from a wrapping millisecond tick
 */

#include "uptime.h"

void Uptime_Init(Uptime *u, uint32_t tick_ms)
{
    u->last_tick = tick_ms;
    u->rem_ms    = 0U;
    u->seconds   = 0U;
}

uint32_t Uptime_Update(Uptime *u, uint32_t tick_ms)
{
    /* unsigned subtraction is correct across the wrap: 5 - 0xFFFFFFFB is 10 */
    uint32_t elapsed = tick_ms - u->last_tick;
    u->last_tick = tick_ms;

    /* split the elapsed time first so adding the remainder cannot overflow
     * even after a gap of nearly 49 days */
    u->seconds += elapsed / 1000U;
    u->rem_ms  += elapsed % 1000U;
    if (u->rem_ms >= 1000U)
    {
        u->rem_ms -= 1000U;
        u->seconds++;
    }
    return u->seconds;
}
