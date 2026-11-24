/**
 * test_line.c - host test for the CRC and the line builder
 *
 * covers: the CRC-16/CCITT-FALSE check value, a fully worked line, a line
 * with the sensor lost, the length guard at the largest field values, the
 * clamping of out-of-range floats, buffers that are too small and the pong.
 *
 * the expected checksums were computed independently of the C code with
 * Python's CRC-CCITT (start value 0xFFFF), which is CRC-16/CCITT-FALSE:
 *
 *   import binascii
 *   body = "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,ST:0,SEQ:7,UP:9,MT:0,RF:0,BR:0"
 *   print("%04X" % binascii.crc_hqx(body.encode(), 0xFFFF))      # AD94
 *   print("%04X" % binascii.crc_hqx(b"123456789", 0xFFFF))       # 29B1
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_line.c ../Core/Src/line.c ../Core/Src/crc16.c -o "${TMPDIR:-/tmp}/test_line" && "${TMPDIR:-/tmp}/test_line"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_line.c ../Core/Src/line.c ../Core/Src/crc16.c -o "${TMPDIR:-/tmp}/test_line_san" && "${TMPDIR:-/tmp}/test_line_san"
 */

#include "line.h"
#include "crc16.h"
#include "test_common.h"
#include <math.h>
#include <stdint.h>

static LineFields worked_fields(void)
{
    LineFields f = {0};
    f.vib_x = 0.02f;  f.vib_y = -0.01f;  f.vib_z = 1.01f;
    f.magnitude = 1.01f;
    f.fft_peak_hz = 12.5f;
    f.rms_x = 0.012f; f.rms_y = 0.010f;  f.rms_z = 0.031f;
    f.peak = 0.094f;
    f.status = 0;  f.seq = 7;  f.up_s = 9;
    f.missed_ticks = 0;  f.read_failures = 0;  f.bus_recoveries = 0;
    return f;
}

/* check that a built line has the shape the contract requires: it ends in
 * CR LF, has exactly one asterisk and the four hex digits are the CRC of
 * everything before the asterisk */
static int line_is_well_formed(const char *line, size_t len)
{
    if (len < 8 || len > LINE_MAX_LEN) return 0;
    if (line[len - 2] != '\r' || line[len - 1] != '\n') return 0;
    if (line[len - 7] != '*') return 0;
    for (size_t i = 0; i < len - 7; i++)
    {
        if (line[i] == '*' || line[i] == '\r' || line[i] == '\n') return 0;
    }
    char want[5];
    snprintf(want, sizeof(want), "%04X", CRC16_Compute((const uint8_t *)line, len - 7));
    return memcmp(want, line + len - 6, 4) == 0;
}

int main(void)
{
    char buf[LINE_BUF_SIZE];

    /* ---- CRC ---- */
    CHECK(CRC16_Compute((const uint8_t *)"123456789", 9) == 0x29B1,
          "CRC of \"123456789\" is 29B1 (got %04X)", CRC16_Compute((const uint8_t *)"123456789", 9));
    CHECK(CRC16_Compute((const uint8_t *)"", 0) == 0xFFFF, "CRC of nothing is the start value FFFF");

    /* ---- fully worked line ---- */
    {
        LineFields f = worked_fields();
        const char *want =
            "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,"
            "ST:0,SEQ:7,UP:9,MT:0,RF:0,BR:0*AD94\r\n";
        size_t len = Line_Build(buf, sizeof(buf), &f);
        CHECK(len == strlen(want) && memcmp(buf, want, len) == 0,
              "worked line matches the independently checksummed string (len %zu)", len);
        CHECK(len == 113, "worked line is 113 bytes");
        CHECK(line_is_well_formed(buf, len), "worked line is well formed");
    }

    /* ---- sensor lost: zeros and SENSOR_MISSING ---- */
    {
        LineFields f = {0};
        f.status = 1;  f.seq = 8;  f.up_s = 10;  f.read_failures = 5;  f.bus_recoveries = 1;
        const char *want =
            "VIB:0.00,0.00,0.00,MAG:0.00,FFT_PEAK:0.0Hz,RMS:0.000,0.000,0.000,PK:0.000,"
            "ST:1,SEQ:8,UP:10,MT:0,RF:5,BR:1*6AFC\r\n";
        size_t len = Line_Build(buf, sizeof(buf), &f);
        CHECK(len == strlen(want) && memcmp(buf, want, len) == 0,
              "sensor-lost line matches (zeros, ST:1)");
    }

    /* ---- length guard at the largest field values ---- */
    {
        LineFields f;
        f.vib_x = f.vib_y = f.vib_z = -9.99f;
        f.magnitude = 9.99f;
        f.fft_peak_hz = 99.9f;
        f.rms_x = f.rms_y = f.rms_z = 9.999f;
        f.peak = 9.999f;
        f.status = 255;  f.seq = 65535;  f.up_s = 4294967295U;
        f.missed_ticks = f.read_failures = f.bus_recoveries = 4294967295U;
        const char *want =
            "VIB:-9.99,-9.99,-9.99,MAG:9.99,FFT_PEAK:99.9Hz,RMS:9.999,9.999,9.999,PK:9.999,"
            "ST:255,SEQ:65535,UP:4294967295,MT:4294967295,RF:4294967295,BR:4294967295*7F39\r\n";
        size_t len = Line_Build(buf, sizeof(buf), &f);
        CHECK(len == strlen(want) && memcmp(buf, want, len) == 0, "largest line matches (checksum 7F39)");
        CHECK(len == LINE_WORST_CASE_LEN, "largest line is %zu bytes, LINE_WORST_CASE_LEN is %u", len, LINE_WORST_CASE_LEN);
        CHECK(len <= LINE_MAX_LEN, "largest line is within the %u byte limit (margin %zu)", LINE_MAX_LEN, LINE_MAX_LEN - len);
        CHECK(line_is_well_formed(buf, len), "largest line is well formed");
    }

    /* ---- ST at the values the new NO_DATA bit allows ---- */
    {
        LineFields f;
        f.vib_x = f.vib_y = f.vib_z = -9.99f;  f.magnitude = 9.99f;  f.fft_peak_hz = 99.9f;
        f.rms_x = f.rms_y = f.rms_z = 9.999f;  f.peak = 9.999f;
        f.seq = 65535;  f.up_s = 4294967295U;
        f.missed_ticks = f.read_failures = f.bus_recoveries = 4294967295U;
        size_t l128, l255;
        f.status = 128; l128 = Line_Build(buf, sizeof(buf), &f);
        CHECK(l128 > 0 && strstr(buf, ",ST:128,") != NULL && l128 <= LINE_MAX_LEN, "ST 128 (NO_DATA) prints and fits (%zu bytes)", l128);
        f.status = 255; l255 = Line_Build(buf, sizeof(buf), &f);
        CHECK(l255 == LINE_WORST_CASE_LEN && l255 <= LINE_MAX_LEN, "ST 255, the largest, gives the worst case %zu bytes (limit %u)", l255, LINE_MAX_LEN);
    }

    /* ---- absurd floats are clamped, so they cannot lengthen the line ---- */
    {
        LineFields f = {0};
        f.vib_x = -1.0e30f;  f.vib_y = 1.0e30f;  f.vib_z = -INFINITY;
        f.magnitude = NAN;   f.fft_peak_hz = 1.0e9f;
        f.rms_x = -5.0f;     f.rms_y = INFINITY;  f.rms_z = 1.0e30f;
        f.peak = -INFINITY;
        f.status = 255;  f.seq = 65535;  f.up_s = 4294967295U;
        f.missed_ticks = f.read_failures = f.bus_recoveries = 4294967295U;
        size_t len = Line_Build(buf, sizeof(buf), &f);
        CHECK(len > 0 && len <= LINE_WORST_CASE_LEN, "clamped absurd floats give %zu bytes", len);
        CHECK(line_is_well_formed(buf, len), "clamped line is well formed");
        CHECK(strstr(buf, "nan") == NULL && strstr(buf, "inf") == NULL, "no nan or inf in the line");
        CHECK(strstr(buf, "VIB:-9.99,9.99,-9.99,MAG:0.00,") == buf, "out-of-range values sit at their clamp limits");
    }

    /* ---- negative readings and a small status value ---- */
    {
        LineFields f = worked_fields();
        f.vib_x = -1.999f; f.vib_y = -0.004f; f.vib_z = -2.0f;
        f.status = 6;
        size_t len = Line_Build(buf, sizeof(buf), &f);
        CHECK(strstr(buf, "VIB:-2.00,-0.00,-2.00,") == buf, "negative values keep the existing %%.2f format");
        CHECK(line_is_well_formed(buf, len), "negative line is well formed");
    }

    /* ---- counter and sequence edges ---- */
    {
        LineFields f = worked_fields();
        f.seq = 0;
        size_t len = Line_Build(buf, sizeof(buf), &f);
        CHECK(strstr(buf, ",SEQ:0,") != NULL, "SEQ 0 prints");
        f.seq = 65535;
        len = Line_Build(buf, sizeof(buf), &f);
        CHECK(strstr(buf, ",SEQ:65535,") != NULL && line_is_well_formed(buf, len), "SEQ 65535 prints");
    }

    /* ---- the builder never writes past a buffer of exactly the right size ---- */
    {
        /* guard bytes after the buffer must survive.  a canary array follows
         * the buffer inside one struct so the check is meaningful. */
        struct { char b[LINE_BUF_SIZE]; unsigned char canary[16]; } w;
        memset(&w, 0xA5, sizeof(w));
        LineFields f;
        f.vib_x = f.vib_y = f.vib_z = -9.99f;  f.magnitude = 9.99f;  f.fft_peak_hz = 99.9f;
        f.rms_x = f.rms_y = f.rms_z = 9.999f;  f.peak = 9.999f;
        f.status = 255;  f.seq = 65535;  f.up_s = 4294967295U;
        f.missed_ticks = f.read_failures = f.bus_recoveries = 4294967295U;
        size_t len = Line_Build(w.b, sizeof(w.b), &f);
        int intact = 1;
        for (size_t i = 0; i < sizeof(w.canary); i++) if (w.canary[i] != 0xA5) intact = 0;
        CHECK(len > 0 && intact, "no write past the end of an exactly sized buffer");
    }

    /* ---- buffers that are too small are refused ---- */
    {
        LineFields f = worked_fields();
        CHECK(Line_Build(buf, LINE_BUF_SIZE - 1U, &f) == 0, "buffer one byte too small is refused");
        CHECK(Line_Build(buf, 0, &f) == 0, "zero-size buffer is refused");
        CHECK(Line_Build(NULL, LINE_BUF_SIZE, &f) == 0, "null buffer is refused");
        CHECK(Line_Build(buf, LINE_BUF_SIZE, NULL) == 0, "null fields are refused");
    }

    /* ---- pong ---- */
    {
        char pong[PONG_BUF_SIZE];
        size_t len = Line_BuildPong(pong, sizeof(pong), 0);
        CHECK(len == 13 && memcmp(pong, "PONG:0*82E3\r\n", 13) == 0, "PONG:0 is PONG:0*82E3");
        len = Line_BuildPong(pong, sizeof(pong), 42);
        CHECK(len == 14 && memcmp(pong, "PONG:42*881F\r\n", 14) == 0, "PONG:42 is PONG:42*881F");
        len = Line_BuildPong(pong, sizeof(pong), 65535);
        CHECK(len == 17 && memcmp(pong, "PONG:65535*8C7D\r\n", 17) == 0, "PONG:65535 is PONG:65535*8C7D");
        CHECK(Line_BuildPong(pong, PONG_BUF_SIZE - 1U, 1) == 0, "pong buffer too small is refused");
    }

    TEST_FINISH();
}
