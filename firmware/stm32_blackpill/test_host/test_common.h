/**
 * test_common.h - tiny check helpers shared by the host tests
 *
 * every check prints one PASS or FAIL line so the run is readable and the
 * failure count becomes the exit status.
 */

#ifndef TEST_COMMON_H
#define TEST_COMMON_H

#include <stdio.h>
#include <string.h>

static int g_failures = 0;

#define CHECK(cond, ...)                                  \
    do {                                                  \
        if (cond) { printf("PASS  "); }                   \
        else      { printf("FAIL  "); g_failures++; }     \
        printf(__VA_ARGS__);                              \
        printf("\n");                                     \
    } while (0)

#define TEST_FINISH()                                                         \
    do {                                                                      \
        printf("%s (%d failure(s))\n", g_failures ? "FAILED" : "ALL PASSED",  \
               g_failures);                                                   \
        return g_failures ? 1 : 0;                                            \
    } while (0)

#endif /* TEST_COMMON_H */
