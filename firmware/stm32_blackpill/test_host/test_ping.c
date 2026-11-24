/**
 * test_ping.c - host test for the ping parser and the receive ring
 *
 * covers: a plain ping, CR LF and LF and CR endings, a ping split across
 * calls, garbage before and inside a line, over-long input and recovery
 * after it, "PING:" with no number, numbers at and over 65535, other
 * commands, empty lines, several pings in one stream and the ring's wrap,
 * full and empty behaviour.
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_ping.c ../Core/Src/ping.c -o "${TMPDIR:-/tmp}/test_ping" && "${TMPDIR:-/tmp}/test_ping"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_ping.c ../Core/Src/ping.c -o "${TMPDIR:-/tmp}/test_ping_san" && "${TMPDIR:-/tmp}/test_ping_san"
 */

#include "ping.h"
#include "test_common.h"
#include <stdint.h>

/* feed a string and report how many pings were found, keeping the last number */
static int feed(PingParser *p, const char *s, size_t len, uint16_t *last)
{
    int found = 0;
    for (size_t i = 0; i < len; i++)
    {
        uint16_t n;
        if (Ping_Feed(p, (uint8_t)s[i], &n))
        {
            found++;
            *last = n;
        }
    }
    return found;
}

#define FEED(p, lit, last) feed((p), (lit), sizeof(lit) - 1U, (last))

int main(void)
{
    PingParser p;
    uint16_t   n = 9999;

    Ping_Init(&p);

    /* ---- endings ---- */
    n = 9999; CHECK(FEED(&p, "PING:7\n", &n) == 1 && n == 7, "PING:7 with LF");
    n = 9999; CHECK(FEED(&p, "PING:8\r\n", &n) == 1 && n == 8, "PING:8 with CR LF (one ping, not two)");
    n = 9999; CHECK(FEED(&p, "PING:9\r", &n) == 1 && n == 9, "PING:9 with CR alone");
    n = 9999; CHECK(FEED(&p, "PING:0\n", &n) == 1 && n == 0, "PING:0 is valid");
    n = 9999; CHECK(FEED(&p, "PING:65535\n", &n) == 1 && n == 65535, "PING:65535 is valid");
    n = 9999; CHECK(FEED(&p, "PING:00012\n", &n) == 1 && n == 12, "leading zeros are accepted (00012 is 12)");

    /* ---- split across calls, one byte at a time ---- */
    {
        const char *msg = "PING:1234\r\n";
        int found = 0;
        n = 0;
        for (const char *c = msg; *c; c++)
        {
            uint16_t v;
            if (Ping_Feed(&p, (uint8_t)*c, &v)) { found++; n = v; }
        }
        CHECK(found == 1 && n == 1234, "PING:1234 delivered one byte per call");
    }
    {
        n = 0;
        int a = FEED(&p, "PI", &n);
        int b = FEED(&p, "NG:4", &n);
        int c = FEED(&p, "2\n", &n);
        CHECK(a == 0 && b == 0 && c == 1 && n == 42, "PING:42 split as PI / NG:4 / 2 LF");
    }

    /* ---- rejected lines ---- */
    n = 9999; CHECK(FEED(&p, "PING:\n", &n) == 0, "PING: with no number is ignored");
    n = 9999; CHECK(FEED(&p, "PING\n", &n) == 0, "PING with no colon is ignored");
    n = 9999; CHECK(FEED(&p, "PING:65536\n", &n) == 0, "a number over 65535 (65536) is ignored");
    n = 9999; CHECK(FEED(&p, "PING:99999\n", &n) == 0, "99999 is ignored");
    n = 9999; CHECK(FEED(&p, "PING:123456\n", &n) == 0, "six digits are ignored");
    n = 9999; CHECK(FEED(&p, "PING:-1\n", &n) == 0, "a negative number is ignored");
    n = 9999; CHECK(FEED(&p, "PING:12a\n", &n) == 0, "a non-digit in the number is ignored");
    n = 9999; CHECK(FEED(&p, "PING:1 2\n", &n) == 0, "a space in the number is ignored");
    n = 9999; CHECK(FEED(&p, "ping:5\n", &n) == 0, "lower case is ignored");
    n = 9999; CHECK(FEED(&p, "PONG:5\n", &n) == 0, "a PONG line is ignored");
    n = 9999; CHECK(FEED(&p, "HELLO\n", &n) == 0, "another word is ignored");
    n = 9999; CHECK(FEED(&p, "\n\r\n\n", &n) == 0, "empty lines are ignored");
    n = 9999; CHECK(FEED(&p, "XPING:5\n", &n) == 0, "garbage before PING on the same line makes it not a ping");

    /* ---- garbage inside a line, then a good ping ---- */
    n = 9999; CHECK(FEED(&p, "PI\x01NG:3\n", &n) == 0, "a byte of noise inside the word makes that line not a ping");
    n = 9999; CHECK(FEED(&p, "PING:3\n", &n) == 1 && n == 3, "the next good ping still works");
    n = 9999; CHECK(FEED(&p, "\xFF\xFE\x00\x80\n", &n) == 0, "high and NUL bytes are ignored");
    n = 9999; CHECK(FEED(&p, "PING:4\n", &n) == 1 && n == 4, "a ping after binary noise works");

    /* ---- over-long input ---- */
    {
        char longline[200];
        memset(longline, 'A', sizeof(longline));
        n = 9999;
        int a = feed(&p, longline, sizeof(longline), &n);
        CHECK(a == 0, "200 bytes with no line end give no ping");
        CHECK(FEED(&p, "\n", &n) == 0, "the end of the over-long line gives no ping");
        CHECK(FEED(&p, "PING:11\n", &n) == 1 && n == 11, "a ping after an over-long line works");

        /* the tail of an over-long line must not be taken for a line of its own */
        n = 9999;
        int b = FEED(&p, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPING:5\n", &n);
        CHECK(b == 0, "PING:5 at the end of an over-long line is not answered");
        CHECK(FEED(&p, "PING:6\n", &n) == 1 && n == 6, "the next line is parsed normally");

        /* exactly the buffer size and one more */
        n = 9999;
        CHECK(FEED(&p, "PING:1234567890\n", &n) == 0, "a 15 byte line is read and rejected");
        CHECK(FEED(&p, "PING:12345678901\n", &n) == 0, "a 16 byte line is rejected");
        CHECK(FEED(&p, "PING:123456789012\n", &n) == 0, "a 17 byte line overflows and is rejected");
        CHECK(FEED(&p, "PING:2\n", &n) == 1 && n == 2, "and the parser is healthy afterwards");
    }

    /* ---- several pings in one stream ---- */
    {
        int found;
        n = 0;
        found = FEED(&p, "PING:1\nPING:2\r\nnoise\nPING:3\n", &n);
        CHECK(found == 3 && n == 3, "three pings in one stream are all found");
    }

    /* ---- the ring ---- */
    {
        ByteRing r;
        uint8_t b;
        ByteRing_Init(&r);
        CHECK(!ByteRing_Pop(&r, &b), "an empty ring pops nothing");

        int ok = 1;
        for (unsigned i = 0; i < BYTE_RING_SIZE - 1U; i++) ok &= ByteRing_Push(&r, (uint8_t)i);
        CHECK(ok, "the ring takes %u bytes", BYTE_RING_SIZE - 1U);
        CHECK(!ByteRing_Push(&r, 0xEE), "a full ring refuses a byte instead of blocking");

        ok = 1;
        for (unsigned i = 0; i < BYTE_RING_SIZE - 1U; i++) ok &= ByteRing_Pop(&r, &b) && (b == (uint8_t)i);
        CHECK(ok, "bytes come out in order");
        CHECK(!ByteRing_Pop(&r, &b), "and it is empty again");

        /* wrap the indexes several times */
        ok = 1;
        for (unsigned i = 0; i < 1000U; i++)
        {
            ok &= ByteRing_Push(&r, (uint8_t)(i * 7U));
            ok &= ByteRing_Pop(&r, &b) && (b == (uint8_t)(i * 7U));
        }
        CHECK(ok, "1000 push and pop pairs across the index wrap stay in order");
    }

    /* ---- ring into parser, as the firmware does it ---- */
    {
        ByteRing r;
        PingParser pp;
        ByteRing_Init(&r);
        Ping_Init(&pp);
        const char *msg = "PING:300\n";
        for (const char *c = msg; *c; c++) ByteRing_Push(&r, (uint8_t)*c);
        uint8_t b;
        uint16_t v = 0;
        int found = 0;
        while (ByteRing_Pop(&r, &b)) if (Ping_Feed(&pp, b, &v)) found++;
        CHECK(found == 1 && v == 300, "a ping pushed into the ring and drained into the parser is found");
    }

    TEST_FINISH();
}
