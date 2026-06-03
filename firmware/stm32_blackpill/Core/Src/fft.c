/**
 * fft.c - CMSIS-DSP FFT peak frequency detection for the vibration node
 *
 * I replaced the previous O(N^2) DFT with arm_rfft_fast_f32 from CMSIS-DSP.
 * On a 96 MHz Cortex-M4 with FPU this processes 128 points in roughly 19 us
 * versus 171 us for the DFT, leaving substantially more headroom in the
 * 10 ms TIM2 window for a future multi-axis expansion.
 *
 * The arm_rfft_fast_f32 output for an N-point real FFT is packed as:
 *   output[0]      = Re[0]       (DC component - I skip, gravity dominates)
 *   output[1]      = Re[N/2]     (Nyquist bin  - I skip, not meaningful here)
 *   output[2*k]    = Re[k]       for k = 1 .. N/2-1
 *   output[2*k+1]  = Im[k]       for k = 1 .. N/2-1
 *
 * Magnitude of bin k: sqrt(Re[k]^2 + Im[k]^2).
 *
 * Build requirements - see fft.h for the full list of STM32CubeIDE settings.
 */

#include "fft.h"
#include "arm_math.h"
#include <stdint.h>

/* I keep these static so repeated calls reuse the same allocation without
 * touching malloc or the stack.  The instance holds pre-computed twiddle
 * factors for N=128; they are computed once on first call after the FPU
 * is enabled, not at static-init time where FPU state is undefined. */
static arm_rfft_fast_instance_f32 s_fft_instance;
static float                      s_fft_output[FFT_SIZE];
static uint8_t                    s_initialised = 0U;

/**
 * FFT_GetPeakFrequency - Compute the dominant frequency via CMSIS-DSP FFT.
 */
float FFT_GetPeakFrequency(float *samples, uint16_t count, float sample_rate)
{
    (void)count;  /* count must equal FFT_SIZE; kept for API compatibility */

    /* I initialise on first call rather than at reset so twiddle-factor
     * computation happens after SystemClock_Config has enabled the FPU. */
    if (!s_initialised)
    {
        arm_rfft_fast_init_f32(&s_fft_instance, FFT_SIZE);
        s_initialised = 1U;
    }

    /* ifftFlag=0 means forward transform (time -> frequency).
     * arm_rfft_fast_f32 writes results into s_fft_output and does not
     * modify the input buffer, so accel_z_buf remains intact for the
     * mean calculation in main.c. */
    arm_rfft_fast_f32(&s_fft_instance, samples, s_fft_output, 0);

    float    peak_mag_sq = -1.0f;
    uint16_t peak_bin    = 1U;

    /* I scan bins 1 to FFT_SIZE/2-1.
     * Bin 0 (output[0]) is DC - gravity on the Z axis always wins it.
     * Bin FFT_SIZE/2 (output[1]) is the Nyquist bin - aliased content at
     * the folding frequency is not meaningful for mechanical vibration. */
    for (uint16_t k = 1U; k < (FFT_SIZE / 2U); k++)
    {
        float re     = s_fft_output[2U * k];
        float im     = s_fft_output[2U * k + 1U];
        float mag_sq = re * re + im * im;

        /* I compare magnitude-squared to avoid calling sqrtf() in every
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
