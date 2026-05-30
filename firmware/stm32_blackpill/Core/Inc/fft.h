/**
 * fft.h - Frequency analysis header for the vibration node
 *
 * I use a simple DFT (O(n^2)) here rather than a proper radix-2 FFT because
 * CMSIS-DSP arm_rfft_fast_f32 requires the linker to pull in the CMSIS DSP
 * static library, which needs additional STM32CubeIDE project configuration
 * (DSP lib path, __FPU_PRESENT define, correct Cortex-M4 arch flags).  At
 * this stage of the project the DFT is "good enough" for finding the
 * dominant vibration frequency in a 128-point, 100Hz window.
 *
 * TODO: Once the project matures and the CubeMX/CubeIDE build configuration
 * is finalised, replace FFT_GetPeakFrequency with arm_rfft_fast_f32 from
 * CMSIS-DSP (Drivers/CMSIS/DSP/Lib).  The function signature stays the same
 * so callers do not need to change.
 */

#ifndef FFT_H
#define FFT_H

#include <stdint.h>

/* I choose 128 because it is a power of two (friendly for a future FFT
 * upgrade), fits comfortably in the F411's 128 KB SRAM, and at 100 Hz gives
 * a frequency resolution of 100/128 ~ 0.78 Hz - adequate for mechanical
 * vibration diagnostics. */
#define FFT_SIZE    128

/**
 * FFT_GetPeakFrequency - Return the frequency of the dominant spectral peak.
 * @samples:     pointer to array of float time-domain samples
 * @count:       number of valid samples in the array (should equal FFT_SIZE)
 * @sample_rate: sampling rate in Hz (100.0f for this node)
 *
 * Returns the frequency in Hz of the bin with the highest DFT magnitude,
 * skipping the DC bin (0 Hz) because gravity always dominates DC and is not
 * a vibration event.
 *
 * Time complexity: O(count^2) - acceptable for count=128 on a 96 MHz Cortex-M4.
 */
float FFT_GetPeakFrequency(float *samples, uint16_t count, float sample_rate);

#endif /* FFT_H */
