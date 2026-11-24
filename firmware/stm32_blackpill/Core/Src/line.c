/**
 * line.c - telemetry line and pong builder
 *
 * the whole line is built in the caller's one fixed buffer.  every float is
 * clamped to a known range first, so the widest possible line is a constant
 * (LINE_WORST_CASE_LEN) that is checked against the contract limit when the
 * file compiles.  snprintf is also given the exact space left and its result
 * is checked, so even a mistake in the constant cannot write past the buffer.
 */

#include "line.h"
#include "crc16.h"
#include <stdio.h>

/* "*CCCC\r\n" */
#define LINE_TAIL_LEN   7U

/* the body may use whatever the tail leaves */
#define LINE_BODY_MAX   (LINE_MAX_LEN - LINE_TAIL_LEN)

_Static_assert(LINE_WORST_CASE_LEN <= LINE_MAX_LEN,
               "worst-case line is longer than the contract allows");

/* clamp a float into [lo, hi].  a NaN fails the first comparison and so
 * becomes lo, which keeps it from printing as "nan". */
static float clampf(float v, float lo, float hi)
{
    if (!(v >= lo)) return lo;
    if (v > hi)     return hi;
    return v;
}

/* append "*CCCC\r\n" and a terminator after a body of body_len bytes.  the
 * caller has checked that body_len <= LINE_BODY_MAX, so this writes at most
 * LINE_MAX_LEN + 1 bytes. */
static size_t finish(char *buf, size_t body_len)
{
    static const char hex[] = "0123456789ABCDEF";
    uint16_t crc = CRC16_Compute((const uint8_t *)buf, body_len);
    size_t   i   = body_len;

    buf[i++] = '*';
    buf[i++] = hex[(crc >> 12) & 0xFU];
    buf[i++] = hex[(crc >> 8)  & 0xFU];
    buf[i++] = hex[(crc >> 4)  & 0xFU];
    buf[i++] = hex[crc & 0xFU];
    buf[i++] = '\r';
    buf[i++] = '\n';
    buf[i]   = '\0';
    return i;
}

size_t Line_Build(char *buf, size_t cap, const LineFields *f)
{
    if ((buf == NULL) || (f == NULL) || (cap < LINE_BUF_SIZE))
    {
        return 0U;
    }

    int n = snprintf(buf, LINE_BODY_MAX + 1U,
                     "VIB:%.2f,%.2f,%.2f,MAG:%.2f,FFT_PEAK:%.1fHz,"
                     "RMS:%.3f,%.3f,%.3f,PK:%.3f,"
                     "ST:%u,SEQ:%u,UP:%lu,MT:%lu,RF:%lu,BR:%lu",
                     (double)clampf(f->vib_x, -LINE_VIB_LIMIT, LINE_VIB_LIMIT),
                     (double)clampf(f->vib_y, -LINE_VIB_LIMIT, LINE_VIB_LIMIT),
                     (double)clampf(f->vib_z, -LINE_VIB_LIMIT, LINE_VIB_LIMIT),
                     (double)clampf(f->magnitude, 0.0f, LINE_VIB_LIMIT),
                     (double)clampf(f->fft_peak_hz, 0.0f, LINE_FFT_LIMIT),
                     (double)clampf(f->rms_x, 0.0f, LINE_RMS_LIMIT),
                     (double)clampf(f->rms_y, 0.0f, LINE_RMS_LIMIT),
                     (double)clampf(f->rms_z, 0.0f, LINE_RMS_LIMIT),
                     (double)clampf(f->peak, 0.0f, LINE_RMS_LIMIT),
                     (unsigned)f->status,
                     (unsigned)f->seq,
                     (unsigned long)f->up_s,
                     (unsigned long)f->missed_ticks,
                     (unsigned long)f->read_failures,
                     (unsigned long)f->bus_recoveries);

    /* a negative result is an encoding error and a result above the body
     * limit means snprintf truncated.  either way no line is sent. */
    if ((n < 0) || ((size_t)n > LINE_BODY_MAX))
    {
        return 0U;
    }
    return finish(buf, (size_t)n);
}

size_t Line_BuildPong(char *buf, size_t cap, uint16_t n)
{
    if ((buf == NULL) || (cap < PONG_BUF_SIZE))
    {
        return 0U;
    }

    /* "PONG:65535" is 10 bytes, so the body always fits */
    int len = snprintf(buf, PONG_BUF_SIZE - LINE_TAIL_LEN, "PONG:%u", (unsigned)n);
    if ((len < 0) || ((size_t)len > (PONG_BUF_SIZE - LINE_TAIL_LEN - 1U)))
    {
        return 0U;
    }
    return finish(buf, (size_t)len);
}
