/**
 * status.c - status word and reset cause
 */

#include "status.h"

uint8_t Status_ResetBits(bool iwdg, bool wwdg, bool bor, bool por)
{
    uint8_t bits = 0U;

    if (iwdg || wwdg)
    {
        bits |= ST_RESET_WATCHDOG;
    }
    /* BOR is set by a power-on reset as well, so POR must be clear for the
     * flag to mean the supply dipped while the chip was running. */
    if (bor && !por)
    {
        bits |= ST_RESET_BROWNOUT;
    }
    return bits;
}

void Status_Init(StatusState *s, uint8_t boot_bits)
{
    s->boot_bits   = boot_bits;
    s->id_mismatch = false;
    s->dropped     = false;
}

void Status_SetIdMismatch(StatusState *s, bool mismatch)
{
    s->id_mismatch = mismatch;
}

void Status_NoteDropped(StatusState *s)
{
    s->dropped = true;
}

uint8_t Status_Compose(StatusState *s, bool missing, bool stuck, bool clipping, bool no_data)
{
    uint8_t word = s->boot_bits;

    if (missing)        word |= ST_SENSOR_MISSING;
    if (stuck)          word |= ST_SENSOR_STUCK;
    if (clipping)       word |= ST_CLIPPING;
    if (no_data)        word |= ST_NO_DATA;
    if (s->id_mismatch) word |= ST_ID_MISMATCH;
    if (s->dropped)     word |= ST_WINDOW_DROPPED;

    /* the line carries the news, so the next one starts clean */
    s->dropped = false;
    return word;
}
