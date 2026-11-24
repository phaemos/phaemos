/**
 * window_stats.h - statistics for one 128-sample window of raw accelerometer data
 *
 * no HAL header, so it builds on a host compiler.  samples are kept as the
 * raw signed counts the sensor returns, not as floats, because:
 *  - the stuck test must compare exact values and two floats made from the
 *    same count are equal only by luck of the conversion
 *  - the clipping test is a comparison against the full-scale count
 *  - removing the mean from large counts is exact in integers, but in floats
 *    a 1 g offset costs the low bits that a few-mg vibration lives in
 */

#ifndef WINDOW_STATS_H
#define WINDOW_STATS_H

#include <stdbool.h>
#include <stdint.h>
#include "fft.h"

#define WINDOW_SIZE     FFT_SIZE

typedef struct
{
    int16_t  x[WINDOW_SIZE];
    int16_t  y[WINDOW_SIZE];
    int16_t  z[WINDOW_SIZE];
    uint16_t count;             /* samples stored so far */
} WindowBuf;                    /* 770 bytes */

typedef struct
{
    float mean_x, mean_y, mean_z;   /* mean per axis (g) */
    float magnitude;                /* vector magnitude of the mean (g) */
    float rms_x, rms_y, rms_z;      /* RMS per axis with the mean removed (g) */
    float peak;                     /* largest absolute sample of any axis, mean removed (g) */
    bool  stuck;                    /* every sample identical on all three axes */
    bool  clipping;                 /* any raw sample at or beyond full scale */
} WindowStats;

/* empty the window */
void WinBuf_Clear(WindowBuf *w);

/* store one raw sample.  returns true when the window is now full.  a sample
 * added to a full window is ignored and true is returned again. */
bool WinBuf_Add(WindowBuf *w, int16_t x, int16_t y, int16_t z);

/* statistics for a full window.  returns false (and leaves out untouched)
 * when the window is not full. */
bool WinBuf_Compute(const WindowBuf *w, WindowStats *out);

/* copy the Z axis as g-units into out[WINDOW_SIZE] for the FFT */
void WinBuf_ZToFloat(const WindowBuf *w, float *out);

#endif /* WINDOW_STATS_H */
