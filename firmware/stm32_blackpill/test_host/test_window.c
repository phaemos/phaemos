/**
 * test_window.c - host test for the window statistics
 *
 * covers: RMS with the mean removed (a sine, a constant, a constant with one
 * spike, a constant with a large offset), the peak, stuck detection and
 * clipping detection at their edges and the window buffer itself.
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_window.c ../Core/Src/window_stats.c -lm -o "${TMPDIR:-/tmp}/test_window" && "${TMPDIR:-/tmp}/test_window"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_window.c ../Core/Src/window_stats.c -lm -o "${TMPDIR:-/tmp}/test_window_san" && "${TMPDIR:-/tmp}/test_window_san"
 */

#include "window_stats.h"
#include "imu_config.h"
#include "test_common.h"
#include <math.h>

#define LSB     ((float)IMU_ACCEL_LSB_PER_G)
#define TEST_PI 3.14159265358979323846

static WindowBuf s_w;
static WindowStats s_st;

static void fill_const(int16_t x, int16_t y, int16_t z)
{
    WinBuf_Clear(&s_w);
    for (unsigned i = 0; i < WINDOW_SIZE; i++) WinBuf_Add(&s_w, x, y, z);
}

/* a whole number of cycles in the window (cycles per window), so the mean of
 * the sine is zero and its RMS is amplitude over root two */
static void fill_sine(double amp_counts, unsigned cycles, int16_t off_x, int16_t off_y, int16_t off_z)
{
    WinBuf_Clear(&s_w);
    for (unsigned i = 0; i < WINDOW_SIZE; i++)
    {
        double s = amp_counts * sin(2.0 * TEST_PI * (double)cycles * (double)i / (double)WINDOW_SIZE);
        int16_t v = (int16_t)lrint(s);
        WinBuf_Add(&s_w, (int16_t)(off_x + v), (int16_t)(off_y + v / 2), (int16_t)(off_z + v / 4));
    }
}

static int near(float a, float b, float tol) { return fabsf(a - b) <= tol; }

int main(void)
{
    /* ---- buffer behaviour ---- */
    WinBuf_Clear(&s_w);
    CHECK(!WinBuf_Compute(&s_w, &s_st), "an empty window is refused");
    for (unsigned i = 0; i < WINDOW_SIZE - 1U; i++) WinBuf_Add(&s_w, 1, 2, 3);
    CHECK(!WinBuf_Compute(&s_w, &s_st), "a window one sample short is refused");
    CHECK(WinBuf_Add(&s_w, 1, 2, 3), "the 128th sample reports the window full");
    CHECK(WinBuf_Add(&s_w, 9, 9, 9) && s_w.count == WINDOW_SIZE, "a sample added to a full window is ignored");
    CHECK(WinBuf_Compute(&s_w, &s_st), "a full window computes");

    /* ---- constant: RMS and peak are exactly zero ---- */
    fill_const(1234, -567, 16384);
    WinBuf_Compute(&s_w, &s_st);
    CHECK(s_st.rms_x == 0.0f && s_st.rms_y == 0.0f && s_st.rms_z == 0.0f,
          "constant gives RMS exactly 0 on every axis (%g %g %g)", s_st.rms_x, s_st.rms_y, s_st.rms_z);
    CHECK(s_st.peak == 0.0f, "constant gives peak exactly 0 (%g)", s_st.peak);
    CHECK(near(s_st.mean_z, 1.0f, 1e-6f) && near(s_st.magnitude, sqrtf(1234.0f*1234.0f + 567.0f*567.0f + 16384.0f*16384.0f) / LSB, 1e-5f),
          "constant keeps its mean (z %.4f g) and magnitude (%.4f g)", s_st.mean_z, s_st.magnitude);

    /* ---- pure sine: RMS is amplitude over root two, mean removed ---- */
    {
        /* 0.5 g amplitude on X, half on Y, a quarter on Z, 8 whole cycles,
         * with 1 g of offset on Z that must not show in the RMS */
        double amp = 0.5 * LSB;
        fill_sine(amp, 8, 0, 0, 16384);
        WinBuf_Compute(&s_w, &s_st);
        float want_x = (float)(0.5 / sqrt(2.0));
        float want_y = want_x / 2.0f;
        float want_z = want_x / 4.0f;
        CHECK(near(s_st.rms_x, want_x, 1e-3f), "sine RMS x %.5f g, expected %.5f g", s_st.rms_x, want_x);
        CHECK(near(s_st.rms_y, want_y, 1e-3f), "sine RMS y %.5f g, expected %.5f g", s_st.rms_y, want_y);
        CHECK(near(s_st.rms_z, want_z, 1e-3f), "sine RMS z (1 g offset removed) %.5f g, expected %.5f g", s_st.rms_z, want_z);
        CHECK(near(s_st.peak, 0.5f, 2e-3f), "sine peak %.4f g, expected 0.5 g", s_st.peak);
        CHECK(near(s_st.mean_z, 1.0f, 2e-3f), "sine keeps the 1 g mean on z (%.4f g)", s_st.mean_z);
        CHECK(!s_st.stuck && !s_st.clipping, "a sine is neither stuck nor clipping");
    }

    /* ---- sine at a different amplitude and cycle count ---- */
    {
        fill_sine(0.2 * LSB, 13, 100, -100, 0);
        WinBuf_Compute(&s_w, &s_st);
        float want = (float)(0.2 / sqrt(2.0));
        CHECK(near(s_st.rms_x, want, 1e-3f), "0.2 g sine, 13 cycles: RMS %.5f g, expected %.5f g", s_st.rms_x, want);
    }

    /* ---- constant with one spike ---- */
    {
        /* 127 samples at 1000 and one at 1000 + 12800.  mean = 1000 + 100,
         * deviation of the spike is 12700 counts (0.7751 g) and of the rest
         * is 100 counts.  RMS = sqrt((127*100^2 + 12700^2) / 128) */
        WinBuf_Clear(&s_w);
        for (unsigned i = 0; i < WINDOW_SIZE; i++) WinBuf_Add(&s_w, (int16_t)(i == 40 ? 13800 : 1000), 0, 0);
        WinBuf_Compute(&s_w, &s_st);
        double rms = sqrt((127.0 * 100.0 * 100.0 + 12700.0 * 12700.0) / 128.0) / LSB;
        CHECK(near(s_st.rms_x, (float)rms, 1e-5f), "spike RMS %.6f g, expected %.6f g", s_st.rms_x, rms);
        CHECK(near(s_st.peak, 12700.0f / LSB, 1e-5f), "spike peak %.6f g, expected %.6f g", s_st.peak, 12700.0f / LSB);
        CHECK(s_st.rms_y == 0.0f && s_st.rms_z == 0.0f, "the other axes stay at zero RMS");
        CHECK(!s_st.stuck, "one different sample is not stuck");
    }

    /* ---- peak takes the largest axis and handles a negative spike ---- */
    {
        WinBuf_Clear(&s_w);
        for (unsigned i = 0; i < WINDOW_SIZE; i++) WinBuf_Add(&s_w, 0, (int16_t)(i == 7 ? -8192 : 0), (int16_t)(i == 9 ? 1024 : 0));
        WinBuf_Compute(&s_w, &s_st);
        float want = (8192.0f * 127.0f / 128.0f) / LSB;
        CHECK(near(s_st.peak, want, 1e-5f), "negative spike on y dominates the peak (%.5f g, expected %.5f g)", s_st.peak, want);
    }

    /* ---- stuck detection ---- */
    {
        fill_const(100, 200, 300);
        WinBuf_Compute(&s_w, &s_st);
        CHECK(s_st.stuck, "128 identical samples are stuck");

        fill_const(100, 200, 300);
        s_w.x[127] = 101;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.stuck, "a one-count change in the last x sample is not stuck");

        fill_const(100, 200, 300);
        s_w.y[0] = 201;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.stuck, "a one-count change in the first y sample is not stuck");

        fill_const(100, 200, 300);
        s_w.z[64] = 299;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.stuck, "a one-count change in a middle z sample is not stuck");

        /* x constant and y constant but z moving */
        WinBuf_Clear(&s_w);
        for (unsigned i = 0; i < WINDOW_SIZE; i++) WinBuf_Add(&s_w, 5, 6, (int16_t)(i & 1));
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.stuck, "two constant axes with one moving are not stuck");

        /* two raw counts that differ by one would give the same float after a
         * coarse conversion; the test is on the integers */
        fill_const(16384, 0, 1);
        s_w.x[3] = 16385;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.stuck, "counts one apart are told apart");
    }

    /* ---- clipping at its edges ---- */
    {
        fill_const(100, 200, 300);
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.clipping, "ordinary values do not clip");

        fill_const(100, 200, 300);
        s_w.x[10] = 32766;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.clipping, "32766 is one below the positive limit and does not clip");

        fill_const(100, 200, 300);
        s_w.x[10] = 32767;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(s_st.clipping, "32767 clips (positive full scale)");

        fill_const(100, 200, 300);
        s_w.y[127] = -32767;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(!s_st.clipping, "-32767 is one above the negative limit and does not clip");

        fill_const(100, 200, 300);
        s_w.y[127] = -32768;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(s_st.clipping, "-32768 clips (negative full scale)");

        fill_const(100, 200, 300);
        s_w.z[0] = -32768;
        WinBuf_Compute(&s_w, &s_st);
        CHECK(s_st.clipping, "clipping on z is found in the first sample");

        /* every sample at full scale: nothing overflows */
        WinBuf_Clear(&s_w);
        for (unsigned i = 0; i < WINDOW_SIZE; i++) WinBuf_Add(&s_w, (int16_t)((i & 1) ? 32767 : -32768), 32767, -32768);
        CHECK(WinBuf_Compute(&s_w, &s_st) && s_st.clipping, "a window at full scale computes and clips");
        float want_rms = 32767.5f / LSB;
        CHECK(near(s_st.rms_x, want_rms, 1e-3f), "alternating full-scale RMS %.4f g, expected %.4f g (no overflow)", s_st.rms_x, want_rms);
        CHECK(s_st.rms_y == 0.0f, "constant full-scale axis has zero RMS");
    }

    /* ---- the Z conversion for the FFT ---- */
    {
        float z[WINDOW_SIZE];
        fill_const(0, 0, 8192);
        s_w.z[5] = -16384;
        WinBuf_ZToFloat(&s_w, z);
        CHECK(z[0] == 0.5f && z[5] == -1.0f, "Z samples convert to g (0.5 and -1.0)");
    }

    TEST_FINISH();
}
