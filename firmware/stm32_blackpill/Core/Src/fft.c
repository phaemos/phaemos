/**
 * fft.c - DFT-based peak frequency detection for the vibration node
 *
 * I implement a naive O(n^2) Discrete Fourier Transform rather than a
 * radix-2 FFT because at N=128 and 96 MHz Cortex-M4 with FPU the DFT
 * takes roughly 128*128 = 16384 multiply-accumulate pairs.  With the FPU
 * each MAC runs in ~1 cycle, so the whole DFT completes in well under
 * 1 ms - fast enough to execute in the main loop between 1-second windows
 * without blocking the next sample collection cycle.
 *
 * I acknowledge the O(n^2) cost is wasteful compared to O(n log n) FFT.
 * The TODO in fft.h describes the CMSIS-DSP upgrade path.  I defer that
 * upgrade because it requires additional linker configuration that is
 * outside the scope of the current milestone.
 */

#include "fft.h"
#include <math.h>
#include <stdint.h>

/* I define M_PI locally rather than relying on _USE_MATH_DEFINES or a
 * toolchain-specific header because STM32CubeIDE's arm-none-eabi-gcc does
 * not guarantee M_PI is defined unless __USE_MISC is set. */
#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

/**
 * FFT_GetPeakFrequency - Compute the dominant frequency via DFT.
 *
 * Algorithm:
 *   For each frequency bin k from 1 to count/2 (I skip k=0 because that is
 *   the DC component - which in this application is dominated by gravity and
 *   is not a vibration event):
 *     - Compute the DFT magnitude at bin k using the standard sum:
 *         Re = sum( x[n] * cos(2*pi*k*n/N) )
 *         Im = sum( x[n] * sin(2*pi*k*n/N) )
 *         mag = sqrt(Re^2 + Im^2)
 *     - Track the bin with the maximum magnitude.
 *   Convert the winning bin index to Hz: freq = k * sample_rate / count.
 *
 * I loop only up to count/2 rather than count because the DFT spectrum is
 * symmetric for real inputs; bins above count/2 are mirror images and contain
 * no additional information (Nyquist theorem).
 */
float FFT_GetPeakFrequency(float *samples, uint16_t count, float sample_rate)
{
    float peak_magnitude = -1.0f;
    uint16_t peak_bin = 1U;  /* I initialise to 1 to guarantee a non-DC result */

    /* I iterate k from 1 (not 0) to skip the DC bin.  Gravity produces a
     * large DC component (~1g on the Z axis) that would otherwise always win
     * and mask the actual vibration frequency. */
    for (uint16_t k = 1U; k <= count / 2U; k++)
    {
        float re = 0.0f;
        float im = 0.0f;
        float two_pi_k_over_N = 2.0f * (float)M_PI * (float)k / (float)count;

        for (uint16_t n = 0U; n < count; n++)
        {
            /* I pre-compute the argument outside the trig calls to reduce
             * redundant multiplications in the inner loop. */
            float angle = two_pi_k_over_N * (float)n;
            re += samples[n] * cosf(angle);
            im += samples[n] * sinf(angle);
        }

        /* I use re*re + im*im (magnitude squared) for the comparison to
         * avoid calling sqrtf() in every inner iteration.  The ordering of
         * magnitudes is preserved under squaring because magnitudes are
         * non-negative. */
        float mag_sq = re * re + im * im;
        if (mag_sq > peak_magnitude)
        {
            peak_magnitude = mag_sq;
            peak_bin = k;
        }
    }

    /* Convert bin index to frequency in Hz.
     * freq = bin_index * (sample_rate / N)
     * I return the float directly; the caller formats it with one decimal. */
    return (float)peak_bin * sample_rate / (float)count;
}
