/**
 * window_stats.c - statistics for one window of raw accelerometer samples
 *
 * the mean is removed in integer arithmetic.  for N samples with sum S and
 * sum of squares Q the variance times N squared is N*Q - S*S, which is exact
 * in 64 bits (Q is below 2^37 and N*Q below 2^44).  a float version of
 * sum(x^2)/N - mean^2 would subtract two nearly equal large numbers when the
 * axis carries 1 g of gravity and lose the small vibration under rounding.
 */

#include "window_stats.h"
#include "imu_config.h"
#include <math.h>
#include <stdlib.h>

#define N_SAMPLES   ((int32_t)WINDOW_SIZE)
#define LSB_PER_G   ((float)IMU_ACCEL_LSB_PER_G)

typedef struct
{
    int32_t sum;        /* sum of raw samples */
    float   rms_raw;    /* RMS with the mean removed, in raw counts */
    int32_t peak_num;   /* largest |N*x - sum|, the peak deviation times N */
} AxisAccum;

static void axis_stats(const int16_t *s, AxisAccum *a)
{
    int32_t sum   = 0;
    int64_t sumsq = 0;

    for (int32_t i = 0; i < N_SAMPLES; i++)
    {
        sum   += s[i];
        sumsq += (int64_t)s[i] * (int64_t)s[i];
    }

    /* N*Q - S*S is never negative (Cauchy-Schwarz) and is exactly zero for a
     * constant signal, so a constant gives an RMS of exactly zero. */
    int64_t var_n2 = (int64_t)N_SAMPLES * sumsq - (int64_t)sum * (int64_t)sum;

    int32_t peak = 0;
    for (int32_t i = 0; i < N_SAMPLES; i++)
    {
        int32_t d = abs((N_SAMPLES * (int32_t)s[i]) - sum);
        if (d > peak) peak = d;
    }

    a->sum      = sum;
    a->rms_raw  = sqrtf((float)var_n2) / (float)N_SAMPLES;
    a->peak_num = peak;
}

/* true when every element equals the first */
static bool all_equal(const int16_t *s)
{
    for (int32_t i = 1; i < N_SAMPLES; i++)
    {
        if (s[i] != s[0]) return false;
    }
    return true;
}

/* true when any element is at or beyond full scale */
static bool any_clipped(const int16_t *s)
{
    for (int32_t i = 0; i < N_SAMPLES; i++)
    {
        if ((s[i] >= IMU_RAW_FULL_SCALE_MAX) || (s[i] <= IMU_RAW_FULL_SCALE_MIN))
        {
            return true;
        }
    }
    return false;
}

void WinBuf_Clear(WindowBuf *w)
{
    w->count = 0U;
}

bool WinBuf_Add(WindowBuf *w, int16_t x, int16_t y, int16_t z)
{
    if (w->count < WINDOW_SIZE)
    {
        w->x[w->count] = x;
        w->y[w->count] = y;
        w->z[w->count] = z;
        w->count++;
    }
    return w->count >= WINDOW_SIZE;
}

bool WinBuf_Compute(const WindowBuf *w, WindowStats *out)
{
    if (w->count < WINDOW_SIZE)
    {
        return false;
    }

    AxisAccum ax, ay, az;
    axis_stats(w->x, &ax);
    axis_stats(w->y, &ay);
    axis_stats(w->z, &az);

    float inv_n_g = 1.0f / ((float)N_SAMPLES * LSB_PER_G);
    out->mean_x = (float)ax.sum * inv_n_g;
    out->mean_y = (float)ay.sum * inv_n_g;
    out->mean_z = (float)az.sum * inv_n_g;
    out->magnitude = sqrtf(out->mean_x * out->mean_x +
                           out->mean_y * out->mean_y +
                           out->mean_z * out->mean_z);

    out->rms_x = ax.rms_raw / LSB_PER_G;
    out->rms_y = ay.rms_raw / LSB_PER_G;
    out->rms_z = az.rms_raw / LSB_PER_G;

    int32_t peak_num = ax.peak_num;
    if (ay.peak_num > peak_num) peak_num = ay.peak_num;
    if (az.peak_num > peak_num) peak_num = az.peak_num;
    out->peak = (float)peak_num * inv_n_g;

    /* stuck: the three axes all constant means every sample vector is the
     * same.  compared as raw counts, never as scaled floats. */
    out->stuck = all_equal(w->x) && all_equal(w->y) && all_equal(w->z);

    out->clipping = any_clipped(w->x) || any_clipped(w->y) || any_clipped(w->z);
    return true;
}

void WinBuf_ZToFloat(const WindowBuf *w, float *out)
{
    for (uint32_t i = 0U; i < WINDOW_SIZE; i++)
    {
        out[i] = (float)w->z[i] / LSB_PER_G;
    }
}
