/**
 * uptime.h - whole seconds since boot from a wrapping millisecond tick
 *
 * no HAL header, so it builds on a host compiler.  the tick is a 32-bit
 * millisecond counter that wraps every 49.7 days.  dividing the raw tick by
 * 1000 would jump back at the wrap, so the counter adds up the elapsed time
 * between calls instead.  unsigned subtraction gives the right elapsed time
 * across the wrap as long as it is called at least once per 49 days.
 */

#ifndef UPTIME_H
#define UPTIME_H

#include <stdint.h>

typedef struct
{
    uint32_t last_tick;     /* tick at the previous call (ms) */
    uint32_t rem_ms;        /* milliseconds not yet counted as a second, 0 to 999 */
    uint32_t seconds;       /* whole seconds since Uptime_Init */
} Uptime;

void Uptime_Init(Uptime *u, uint32_t tick_ms);

/* fold in the time since the last call and return the seconds so far */
uint32_t Uptime_Update(Uptime *u, uint32_t tick_ms);

#endif /* UPTIME_H */
