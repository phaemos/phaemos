/**
 * fft.h - frequency analysis for the vibration node
 *
 * this header needs no HAL or CMSIS header so the same code builds on a
 * host compiler for the tests in test_host/.
 *
 * two interchangeable back ends sit behind FFT_GetPeakFrequency, chosen by
 * the FFT_USE_CMSIS_DSP build flag:
 *   0 (default) - self-contained radix-2 FFT in fft.c, no external library
 *   1           - CMSIS-DSP arm_rfft_fast_f32, which needs ARM_MATH_CM4 and
 *                 the arm_cortexM4lf_math library on the link line
 */

#ifndef FFT_H
#define FFT_H

#include <stdint.h>

/* choose 128 because it is a power of two (required by both back ends),
 * fits comfortably in the F411's 128 KB SRAM and at 100 Hz gives a
 * frequency resolution of 100/128 = 0.78 Hz - adequate for mechanical
 * vibration diagnostics at this sample rate. */
#define FFT_SIZE    128U

/**
 * FFT_Init: prepare the transform tables.  call once before sampling starts.
 * FFT_GetPeakFrequency does this itself on first use, so calling it is only
 * needed to keep that cost out of the first window.
 */
void FFT_Init(void);

/**
 * FFT_GetPeakFrequency: return the frequency of the dominant spectral peak.
 * @samples:     pointer to FFT_SIZE float time-domain samples (not modified)
 * @count:       number of valid samples (must equal FFT_SIZE)
 * @sample_rate: sampling rate in Hz (100.0f for this node)
 *
 * returns the frequency in Hz of the bin with the highest magnitude.  it
 * returns 0.0f if count is not FFT_SIZE.  the mean is removed first and bins 0 and
 * FFT_SIZE/2 are skipped, because gravity dominates DC on the Z axis.
 */
float FFT_GetPeakFrequency(const float *samples, uint16_t count, float sample_rate);

#endif /* FFT_H */
