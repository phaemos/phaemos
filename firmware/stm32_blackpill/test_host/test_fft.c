/**
 * test_fft.c - host test for the FFT peak frequency code
 *
 * builds fft.c with the host compiler so no ARM toolchain or HAL header is
 * needed.  a sine of known frequency sampled at 100 Hz must give a peak
 * within half a bin (100/256 Hz) of the true value.
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_fft.c ../Core/Src/fft.c -lm -o "${TMPDIR:-/tmp}/test_fft" && "${TMPDIR:-/tmp}/test_fft"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_fft.c ../Core/Src/fft.c -lm -o "${TMPDIR:-/tmp}/test_fft_san" && "${TMPDIR:-/tmp}/test_fft_san"
 */

#include "fft.h"
#include <math.h>
#include <stdio.h>

#define RATE_HZ   100.0f
#define BIN_HZ    (RATE_HZ / (float)FFT_SIZE)
#define TEST_PI   3.14159265358979323846f

/* synthesise one or two tones plus an offset and check the reported peak.
 * tol_hz is the allowed error.  the second tone is skipped when amp2 is 0. */
static int check_tones(const char *name, float f1, float amp1, float f2, float amp2,
                       float offset, float expect_hz, float tol_hz)
{
    float samples[FFT_SIZE];

    for (unsigned i = 0; i < FFT_SIZE; i++)
    {
        float t = (float)i / RATE_HZ;
        samples[i] = offset + amp1 * sinf(2.0f * TEST_PI * f1 * t);
        if (amp2 != 0.0f)
        {
            samples[i] += amp2 * sinf(2.0f * TEST_PI * f2 * t);
        }
    }

    float peak = FFT_GetPeakFrequency(samples, FFT_SIZE, RATE_HZ);
    float err  = fabsf(peak - expect_hz);
    int   ok   = err <= tol_hz;

    printf("%s  %-28s -> peak %7.3f Hz (expected %6.3f, error %.4f, limit %.4f)\n",
           ok ? "PASS" : "FAIL", name, peak, expect_hz, err, tol_hz);
    return ok ? 0 : 1;
}

static int check_sine(float freq_hz, float offset, float amplitude)
{
    float samples[FFT_SIZE];

    /* the offset stands in for gravity on the Z axis */
    for (unsigned i = 0; i < FFT_SIZE; i++)
    {
        samples[i] = offset + amplitude * sinf(2.0f * TEST_PI * freq_hz * (float)i / RATE_HZ);
    }

    float peak = FFT_GetPeakFrequency(samples, FFT_SIZE, RATE_HZ);
    float err  = fabsf(peak - freq_hz);
    int   ok   = err <= (BIN_HZ / 2.0f);  /* half a bin: a one-bin shift fails */

    printf("%s  sine %5.1f Hz offset %.1f g -> peak %6.3f Hz (error %.3f Hz, limit %.3f Hz)\n",
           ok ? "PASS" : "FAIL", freq_hz, offset, peak, err, BIN_HZ / 2.0f);
    return ok ? 0 : 1;
}

int main(void)
{
    int failures = 0;

    failures += check_sine(10.0f, 0.0f, 0.5f);
    failures += check_sine(25.0f, 0.0f, 0.5f);
    failures += check_sine(10.0f, 1.0f, 0.2f);
    failures += check_sine(25.0f, 1.0f, 0.2f);

    /* tones centred on a bin must come back exactly: 12.5 Hz is bin 16 and
     * 25 Hz is bin 32 at 100 Hz with 128 points */
    failures += check_tones("12.5 Hz bin-centred",  12.5f, 0.5f, 0.0f, 0.0f, 1.0f, 12.5f, 0.001f);
    failures += check_tones("25 Hz bin-centred",    25.0f, 0.5f, 0.0f, 0.0f, 1.0f, 25.0f, 0.001f);
    failures += check_tones("3.125 Hz bin-centred",  3.125f, 0.5f, 0.0f, 0.0f, 1.0f, 3.125f, 0.001f);

    /* two tones: the larger one must win whichever order they come in */
    failures += check_tones("10 Hz (0.3) + 25 Hz (0.6)", 10.0f, 0.3f, 25.0f, 0.6f, 1.0f, 25.0f, BIN_HZ / 2.0f);
    failures += check_tones("25 Hz (0.3) + 10 Hz (0.6)", 25.0f, 0.3f, 10.0f, 0.6f, 1.0f, 10.0f, BIN_HZ / 2.0f);

    /* a wrong-sized window must be refused */
    float dummy[FFT_SIZE] = {0};
    if (FFT_GetPeakFrequency(dummy, FFT_SIZE - 1U, RATE_HZ) != 0.0f)
    {
        printf("FAIL  wrong-sized window was not refused\n");
        failures++;
    }
    else
    {
        printf("PASS  wrong-sized window refused\n");
    }

    printf("%s (%d failure(s))\n", failures ? "FAILED" : "ALL PASSED", failures);
    return failures ? 1 : 0;
}
