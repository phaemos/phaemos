/**
 * status.h - the status word and the reset cause
 *
 * no HAL header, so it builds on a host compiler.  bit values are fixed by
 * the serial link contract.
 */

#ifndef STATUS_H
#define STATUS_H

#include <stdbool.h>
#include <stdint.h>

#define ST_SENSOR_MISSING   0x01U   /* the MPU6050 is not answering */
#define ST_SENSOR_STUCK     0x02U   /* every sample in the window was identical */
#define ST_CLIPPING         0x04U   /* a sample was at full scale */
#define ST_ID_MISMATCH      0x08U   /* WHO_AM_I was not 0x68 at the last check */
#define ST_RESET_WATCHDOG   0x10U   /* this boot followed a watchdog reset */
#define ST_WINDOW_DROPPED   0x20U   /* a window was discarded since the last line */
#define ST_RESET_BROWNOUT   0x40U   /* this boot followed a brown-out reset */
#define ST_NO_DATA          0x80U   /* no window for two periods, sensor not lost: readings are zeros */

typedef struct
{
    uint8_t boot_bits;      /* reset cause, held for the whole boot */
    bool    id_mismatch;    /* result of the latest identity check */
    bool    dropped;        /* a window was discarded and no line has said so yet */
} StatusState;

/**
 * Status_ResetBits: turn the reset flags into status bits.
 * @iwdg, @wwdg: the independent and window watchdog reset flags
 * @bor, @por:   the brown-out and power-on reset flags
 * on the STM32F4 the BOR flag is also set by a power-on reset, so a brown-out
 * is reported only when BOR is set and POR is not.  a cold start would
 * otherwise show as a brown-out every time.  on a chip whose option bytes
 * still have the brown-out level off (as shipped, to our memory of RM0383)
 * every supply reset sets POR too, so this bit stays clear until the level is
 * programmed.  the firmware never writes option bytes.
 */
uint8_t Status_ResetBits(bool iwdg, bool wwdg, bool bor, bool por);

void Status_Init(StatusState *s, uint8_t boot_bits);

/* record the outcome of an identity check */
void Status_SetIdMismatch(StatusState *s, bool mismatch);

/* record that a window was discarded for a timing gap */
void Status_NoteDropped(StatusState *s);

/**
 * Status_Compose: build the status word for the line about to be sent and
 * clear the dropped flag, because the line reports it.
 */
uint8_t Status_Compose(StatusState *s, bool missing, bool stuck, bool clipping, bool no_data);

#endif /* STATUS_H */
