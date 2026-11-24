/**
 * test_uptime.c - host test for the seconds counter
 *
 * covers: counting from zero, partial seconds carried over between calls,
 * long gaps and the 32-bit millisecond tick wrapping after 49.7 days.
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_uptime.c ../Core/Src/uptime.c -o "${TMPDIR:-/tmp}/test_uptime" && "${TMPDIR:-/tmp}/test_uptime"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_uptime.c ../Core/Src/uptime.c -o "${TMPDIR:-/tmp}/test_uptime_san" && "${TMPDIR:-/tmp}/test_uptime_san"
 */

#include "uptime.h"
#include "test_common.h"
#include <stdint.h>

int main(void)
{
    Uptime u;

    /* ---- basic counting ---- */
    Uptime_Init(&u, 0);
    CHECK(Uptime_Update(&u, 0) == 0, "0 ms is 0 s");
    CHECK(Uptime_Update(&u, 999) == 0, "999 ms is still 0 s");
    CHECK(Uptime_Update(&u, 1000) == 1, "1000 ms is 1 s");
    CHECK(Uptime_Update(&u, 1999) == 1, "1999 ms is 1 s");
    CHECK(Uptime_Update(&u, 2000) == 2, "2000 ms is 2 s");

    /* ---- many small steps add up without drift ---- */
    {
        Uptime_Init(&u, 0);
        uint32_t t = 0, s = 0;
        for (int i = 0; i < 100000; i++)   /* 100000 steps of 10 ms = 1000 s */
        {
            t += 10U;
            s = Uptime_Update(&u, t);
        }
        CHECK(s == 1000, "100000 steps of 10 ms give 1000 s (got %lu)", (unsigned long)s);
    }

    /* ---- uneven steps keep the remainder ---- */
    {
        Uptime_Init(&u, 0);
        Uptime_Update(&u, 700);
        CHECK(Uptime_Update(&u, 1400) == 1, "700 then 1400 ms is 1 s");
        CHECK(Uptime_Update(&u, 2100) == 2, "and 2100 ms is 2 s (0.7 + 0.7 + 0.7 carried)");
    }

    /* ---- the tick wraps: 49 days 17 h 2 min 47.296 s is 2^32 ms ---- */
    {
        Uptime_Init(&u, 0);
        uint32_t t = 0;
        uint32_t s = 0;
        /* walk up to just before the wrap in steps of 1,000,000 ms (1000 s) */
        while (t < 4294000000U) { t += 1000000U; s = Uptime_Update(&u, t); }
        CHECK(s == 4294000U, "4294000 s reached just before the wrap (got %lu)", (unsigned long)s);

        t += 1000000U;   /* 4295000000 wraps to 32704 */
        s = Uptime_Update(&u, t);
        CHECK(t == 32704U, "the simulated tick has wrapped (now %lu)", (unsigned long)t);
        CHECK(s == 4295000U, "seconds carry on across the wrap (4295000, got %lu)", (unsigned long)s);

        s = Uptime_Update(&u, t + 1000U);
        CHECK(s == 4295001U, "and keep counting after it (4295001, got %lu)", (unsigned long)s);
    }

    /* ---- a step straddling the wrap ---- */
    {
        Uptime_Init(&u, 0xFFFFFF00U);   /* 255 ms before the wrap */
        CHECK(Uptime_Update(&u, 0xFFFFFFFFU) == 0, "255 ms before the wrap is 0 s");
        CHECK(Uptime_Update(&u, 0x000002E8U) == 1, "a tick across the wrap (to 744 ms) adds 1000 ms in total: 1 s");
        CHECK(Uptime_Update(&u, 0x000006CFU) == 1, "1999 ms after the start is still 1 s");
        CHECK(Uptime_Update(&u, 0x000006D0U) == 2, "2000 ms after the start is 2 s");
    }

    /* ---- a very long gap, the longest the counter can see ---- */
    {
        Uptime_Init(&u, 12345U);
        uint32_t s = Uptime_Update(&u, 12344U);   /* 2^32 - 1 ms later */
        CHECK(s == 4294967U, "a gap of 2^32 - 1 ms is 4294967 s (got %lu)", (unsigned long)s);
    }

    /* ---- many wraps ---- */
    {
        Uptime_Init(&u, 0);
        uint32_t t = 0, s = 0;
        /* 20 wraps worth of time in 1 s steps would take 86 million calls;
         * use 60 s steps instead: 1,433,000 steps is just over 20 wraps */
        for (uint64_t i = 1; i <= 1433000U; i++)
        {
            t = (uint32_t)(i * 60000U);
            s = Uptime_Update(&u, t);
        }
        CHECK(s == 1433000U * 60U, "20 wraps of the tick give %lu s (got %lu)", 1433000UL * 60UL, (unsigned long)s);
    }

    TEST_FINISH();
}
