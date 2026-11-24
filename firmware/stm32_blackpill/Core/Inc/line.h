/**
 * line.h - builds the telemetry line and the pong reply
 *
 * no HAL header, so it builds on a host compiler.  the format is the fixed
 * serial link contract for the Black Pill:
 *
 *   VIB:x,y,z,MAG:m,FFT_PEAK:fHz,RMS:x,y,z,PK:p,ST:s,SEQ:n,UP:u,MT:a,RF:b,BR:c*CCCC\r\n
 *
 * CCCC is CRC-16/CCITT-FALSE over every byte before the asterisk.  a line is
 * at most 160 bytes including CR LF.
 */

#ifndef LINE_H
#define LINE_H

#include <stddef.h>
#include <stdint.h>

/* the contract limit, CR LF included */
#define LINE_MAX_LEN        160U

/* the caller's buffer needs room for the line and the string terminator */
#define LINE_BUF_SIZE       (LINE_MAX_LEN + 1U)

/* longest line the builder can produce.  the floats are clamped to the
 * ranges below, so every field has a known widest form:
 *   VIB 3 x "-9.99", MAG "9.99", FFT_PEAK "99.9", RMS 3 x "9.999", PK "9.999",
 *   ST "255" (a one byte mask, so three digits at most, NO_DATA included), SEQ "65535", UP MT RF BR "4294967295", then "*CCCC\r\n".
 * a compile-time check in line.c keeps this under LINE_MAX_LEN and a host
 * test builds a line at these values to confirm the figure. */
#define LINE_WORST_CASE_LEN 157U

/* clamp ranges.  the accelerometer works at +/-2 g so none of these limits
 * cuts a real reading.  they exist so a corrupt value cannot lengthen the
 * line past the contract limit. */
#define LINE_VIB_LIMIT      9.99f
#define LINE_RMS_LIMIT      9.999f
#define LINE_FFT_LIMIT      99.9f

typedef struct
{
    float    vib_x, vib_y, vib_z;   /* mean acceleration per axis (g) */
    float    magnitude;             /* vector magnitude of the mean (g) */
    float    fft_peak_hz;           /* dominant frequency (Hz) */
    float    rms_x, rms_y, rms_z;   /* RMS per axis, mean removed (g) */
    float    peak;                  /* largest absolute sample, mean removed (g) */
    uint8_t  status;                /* status bit mask */
    uint16_t seq;                   /* data lines since boot, wraps at 65536 */
    uint32_t up_s;                  /* whole seconds since boot */
    uint32_t missed_ticks;          /* MT */
    uint32_t read_failures;         /* RF */
    uint32_t bus_recoveries;        /* BR */
} LineFields;

/**
 * Line_Build: write one data line, CR LF terminated, into buf.
 * @cap: size of buf in bytes, at least LINE_BUF_SIZE
 * returns the line length in bytes (never more than LINE_MAX_LEN) or 0 when
 * cap is too small or the line would not fit.  it never writes past cap.
 */
size_t Line_Build(char *buf, size_t cap, const LineFields *fields);

/** size of the buffer Line_BuildPong needs */
#define PONG_BUF_SIZE       24U

/**
 * Line_BuildPong: write "PONG:<n>*CCCC\r\n" into buf.
 * returns the length or 0 when cap is smaller than PONG_BUF_SIZE.
 */
size_t Line_BuildPong(char *buf, size_t cap, uint16_t n);

#endif /* LINE_H */
