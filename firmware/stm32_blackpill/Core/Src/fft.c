/**
 * fft.c - FFT peak frequency detection for the vibration node
 *
 * the transform sits behind fft_forward so two back ends can be swapped with
 * the FFT_USE_CMSIS_DSP build flag.  both write the same packed layout, which
 * is the one arm_rfft_fast_f32 uses for an N-point real FFT:
 *   output[0]      = Re[0]       (DC component - skipped, gravity dominates)
 *   output[1]      = Re[N/2]     (Nyquist bin  - skipped, not meaningful here)
 *   output[2*k]    = Re[k]       for k = 1 .. N/2-1
 *   output[2*k+1]  = Im[k]       for k = 1 .. N/2-1
 *
 * the default back end is a plain radix-2 FFT so the first build has no
 * dependency on a DSP library being present in the framework package.
 * nothing in this file includes a HAL header, so test_host/ builds it with
 * the host compiler.
 */

#include "fft.h"
#include <math.h>
#include <stdint.h>

#ifndef FFT_USE_CMSIS_DSP
#define FFT_USE_CMSIS_DSP 0
#endif

#if FFT_USE_CMSIS_DSP
#include "arm_math.h"
#endif

/* log2(FFT_SIZE), checked below so a size change cannot silently break the
 * bit-reversal loop. */
#define FFT_LOG2N   7U
_Static_assert(FFT_SIZE == (1U << FFT_LOG2N), "FFT_SIZE must be 2^FFT_LOG2N");

/* work and result buffers are static so repeated calls reuse the same
 * memory without malloc or a large stack frame.  the fallback transform's
 * re and im arrays are static too, for the same reason. */
static float s_work[FFT_SIZE];      /* mean-removed copy of the input */
static float s_spectrum[FFT_SIZE];  /* packed spectrum, layout above */

#if FFT_USE_CMSIS_DSP

/* CMSIS-DSP back end.  arm_rfft_fast_f32 uses its input buffer as scratch
 * space and overwrites it, which is why FFT_GetPeakFrequency passes it the
 * private s_work copy and never the caller's samples. */
static arm_rfft_fast_instance_f32 s_fft_instance;
static uint8_t                    s_initialised = 0U;

static void fft_setup(void)
{
    if (!s_initialised)
    {
        arm_rfft_fast_init_f32(&s_fft_instance, FFT_SIZE);
        s_initialised = 1U;
    }
}

static void fft_forward(float *in, float *out)
{
    fft_setup();

    /* ifftFlag = 0 selects the forward transform */
    arm_rfft_fast_f32(&s_fft_instance, in, out, 0);
}

#else

/* self-contained radix-2 back end: a complex decimation-in-time FFT with the
 * imaginary part of the input set to zero.  a real-input split would halve
 * the work but 128 points at 100 Hz leaves ample time, so the simpler code
 * wins. */
#define FFT_PI  3.14159265358979323846f

static float   s_tw_cos[FFT_SIZE / 2U];
static float   s_tw_sin[FFT_SIZE / 2U];
static uint8_t s_tw_ready = 0U;

/* reverse the low FFT_LOG2N bits of an index */
static uint32_t bit_reverse(uint32_t x)
{
    uint32_t r = 0U;
    for (uint32_t b = 0U; b < FFT_LOG2N; b++)
    {
        r = (r << 1) | (x & 1U);
        x >>= 1;
    }
    return r;
}

static float s_re[FFT_SIZE];
static float s_im[FFT_SIZE];

/* build the twiddle table once.  computing it on the fly would call sinf and
 * cosf in the inner loop. */
static void fft_setup(void)
{
    if (!s_tw_ready)
    {
        for (uint32_t k = 0U; k < (FFT_SIZE / 2U); k++)
        {
            float angle = -2.0f * FFT_PI * (float)k / (float)FFT_SIZE;
            s_tw_cos[k] = cosf(angle);
            s_tw_sin[k] = sinf(angle);
        }
        s_tw_ready = 1U;
    }
}

static void fft_forward(float *in, float *out)
{
    float *re = s_re;
    float *im = s_im;

    fft_setup();

    /* load in bit-reversed order so the butterflies can run in place */
    for (uint32_t i = 0U; i < FFT_SIZE; i++)
    {
        uint32_t j = bit_reverse(i);
        re[j] = in[i];
        im[j] = 0.0f;
    }

    for (uint32_t len = 2U; len <= FFT_SIZE; len <<= 1)
    {
        uint32_t half = len >> 1;
        uint32_t step = FFT_SIZE / len;  /* stride into the twiddle table */

        for (uint32_t i = 0U; i < FFT_SIZE; i += len)
        {
            for (uint32_t k = 0U; k < half; k++)
            {
                float    wr = s_tw_cos[k * step];
                float    wi = s_tw_sin[k * step];
                uint32_t a  = i + k;
                uint32_t b  = a + half;

                float tr = re[b] * wr - im[b] * wi;
                float ti = re[b] * wi + im[b] * wr;

                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] += tr;
                im[a] += ti;
            }
        }
    }

    /* pack into the same layout as arm_rfft_fast_f32 */
    out[0] = re[0];
    out[1] = re[FFT_SIZE / 2U];
    for (uint32_t k = 1U; k < (FFT_SIZE / 2U); k++)
    {
        out[2U * k]      = re[k];
        out[2U * k + 1U] = im[k];
    }
}

#endif /* FFT_USE_CMSIS_DSP */

/**
 * FFT_Init: build the twiddle table or DSP instance ahead of the first window.
 * the table costs a few hundred sinf and cosf calls, which would make the
 * first window overrun a 10 ms tick if it were built on demand.
 */
void FFT_Init(void)
{
    fft_setup();
}

/**
 * FFT_GetPeakFrequency: compute the dominant frequency.
 */
float FFT_GetPeakFrequency(const float *samples, uint16_t count, float sample_rate)
{
    /* refuse a wrong-sized window rather than read past the buffer */
    if (count != FFT_SIZE)
    {
        return 0.0f;
    }

    /* remove the mean before transforming.  a 1 g gravity offset on Z is far
     * larger than the vibration and its leakage into the low bins would
     * otherwise win the peak search. */
    float sum = 0.0f;
    for (uint16_t i = 0U; i < FFT_SIZE; i++)
    {
        sum += samples[i];
    }
    float mean = sum / (float)FFT_SIZE;

    for (uint16_t i = 0U; i < FFT_SIZE; i++)
    {
        s_work[i] = samples[i] - mean;
    }

    fft_forward(s_work, s_spectrum);

    float    peak_mag_sq = -1.0f;
    uint16_t peak_bin    = 1U;

    /* scan bins 1 to FFT_SIZE/2-1.
     * bin 0 (output[0]) is DC.  bin FFT_SIZE/2 (output[1]) is the Nyquist
     * bin, where aliased content is not meaningful for mechanical
     * vibration. */
    for (uint16_t k = 1U; k < (FFT_SIZE / 2U); k++)
    {
        float re     = s_spectrum[2U * k];
        float im     = s_spectrum[2U * k + 1U];
        float mag_sq = re * re + im * im;

        /* compare magnitude-squared to avoid calling sqrtf() in every
         * iteration - ordering of non-negative values is preserved under
         * squaring so the winning bin is still correct. */
        if (mag_sq > peak_mag_sq)
        {
            peak_mag_sq = mag_sq;
            peak_bin    = k;
        }
    }

    /* freq = bin_index * (sample_rate / FFT_SIZE) */
    return (float)peak_bin * sample_rate / (float)FFT_SIZE;
}
