/**
 * fft.h - CMSIS-DSP frequency analysis for the vibration node
 *
 * I use arm_rfft_fast_f32 (radix-2 real FFT, O(N log N)) from CMSIS-DSP.
 * This replaces the previous O(N^2) DFT implementation; on a 96 MHz
 * Cortex-M4 with FPU the FFT completes in roughly 128 * log2(128) * 2 cycles
 * (~1,800 cycles, ~19 us) versus ~16,400 cycles (~171 us) for the DFT.
 *
 * Build requirements (STM32CubeIDE project properties):
 *   C/C++ Build > Settings > MCU GCC Compiler > Preprocessor:
 *     ARM_MATH_CM4, __FPU_PRESENT=1U
 *   C/C++ Build > Settings > MCU GCC Compiler > Include paths:
 *     Drivers/CMSIS/DSP/Include
 *   C/C++ Build > Settings > MCU GCC Linker > Libraries:
 *     Library name:        arm_cortexM4lf_math
 *     Library search path: Drivers/CMSIS/DSP/Lib/GCC
 */

#ifndef FFT_H
#define FFT_H

#include <stdint.h>
#include "arm_math.h"

/* I choose 128 because it is a power of two (required by arm_rfft_fast_f32),
 * fits comfortably in the F411's 128 KB SRAM, and at 100 Hz gives a
 * frequency resolution of 100/128 = 0.78 Hz - adequate for mechanical
 * vibration diagnostics at this sample rate. */
#define FFT_SIZE    128U

/**
 * FFT_GetPeakFrequency - Return the frequency of the dominant spectral peak.
 * @samples:     pointer to FFT_SIZE float time-domain samples
 * @count:       number of valid samples (must equal FFT_SIZE)
 * @sample_rate: sampling rate in Hz (100.0f for this node)
 *
 * Returns the frequency in Hz of the bin with the highest magnitude,
 * skipping DC (bin 0) because gravity always dominates it on the Z axis.
 */
float FFT_GetPeakFrequency(float *samples, uint16_t count, float sample_rate);

#endif /* FFT_H */
