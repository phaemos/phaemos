/**
 * test_status.c - host test for the status word and the identity helpers
 *
 * covers: every bit value, the reset cause mapping (including the rule that a
 * power-on reset is not a brown-out), the dropped flag clearing once a line
 * has carried it and the WHO_AM_I and sleep-bit checks.
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -I../Core/Inc test_status.c ../Core/Src/status.c -o "${TMPDIR:-/tmp}/test_status" && "${TMPDIR:-/tmp}/test_status"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../Core/Inc test_status.c ../Core/Src/status.c -o "${TMPDIR:-/tmp}/test_status_san" && "${TMPDIR:-/tmp}/test_status_san"
 */

#include "status.h"
#include "imu_config.h"
#include "test_common.h"

int main(void)
{
    /* ---- bit values are the contract's ---- */
    CHECK(ST_NO_DATA == 128, "NO_DATA is 128");
    CHECK(Status_Compose(&(StatusState){0}, false, false, false, true) == 128, "NO_DATA alone gives 128");
    CHECK(ST_SENSOR_MISSING == 1 && ST_SENSOR_STUCK == 2 && ST_CLIPPING == 4 &&
          ST_ID_MISMATCH == 8 && ST_RESET_WATCHDOG == 16 && ST_WINDOW_DROPPED == 32 &&
          ST_RESET_BROWNOUT == 64, "bit values are 1 2 4 8 16 32 64");

    /* ---- reset cause ---- */
    CHECK(Status_ResetBits(false, false, false, false) == 0, "no flags: no reset bits");
    CHECK(Status_ResetBits(true,  false, false, false) == ST_RESET_WATCHDOG, "IWDG flag gives RESET_WATCHDOG");
    CHECK(Status_ResetBits(false, true,  false, false) == ST_RESET_WATCHDOG, "WWDG flag gives RESET_WATCHDOG");
    CHECK(Status_ResetBits(false, false, true,  false) == ST_RESET_BROWNOUT, "BOR without POR gives RESET_BROWNOUT");
    CHECK(Status_ResetBits(false, false, true,  true)  == 0, "BOR with POR is a cold start, not a brown-out");
    CHECK(Status_ResetBits(true,  false, true,  false) == (ST_RESET_WATCHDOG | ST_RESET_BROWNOUT), "both causes can be set together");

    /* ---- composition ---- */
    StatusState s;
    Status_Init(&s, 0);
    CHECK(Status_Compose(&s, false, false, false, false) == 0, "all well is 0");
    CHECK(Status_Compose(&s, true, false, false, false) == 1, "missing is 1");
    CHECK(Status_Compose(&s, false, true, false, false) == 2, "stuck is 2");
    CHECK(Status_Compose(&s, false, false, true, false)  == 4, "clipping is 4");
    CHECK(Status_Compose(&s, true, true, true, false)  == 7, "missing, stuck and clipping give 7");

    Status_SetIdMismatch(&s, true);
    CHECK(Status_Compose(&s, false, false, false, false) == 8, "ID_MISMATCH is held on every line until the next check");
    CHECK(Status_Compose(&s, false, false, false, false) == 8, "ID_MISMATCH is still set on the line after");
    Status_SetIdMismatch(&s, false);
    CHECK(Status_Compose(&s, false, false, false, false) == 0, "a good identity check clears ID_MISMATCH");

    /* ---- dropped is reported once ---- */
    Status_NoteDropped(&s);
    Status_NoteDropped(&s);
    CHECK(Status_Compose(&s, false, false, false, false) == 32, "WINDOW_DROPPED is set after discards");
    CHECK(Status_Compose(&s, false, false, false, false) == 0, "WINDOW_DROPPED clears after the line that reported it");

    /* ---- boot bits are held for the whole boot ---- */
    Status_Init(&s, ST_RESET_WATCHDOG);
    CHECK(Status_Compose(&s, false, false, false, false) == 16, "RESET_WATCHDOG on the first line");
    CHECK(Status_Compose(&s, false, false, false, false) == 16, "RESET_WATCHDOG still held on the next line");
    CHECK(Status_Compose(&s, true, true, true, false) == (16 | 7), "boot bits combine with live bits (23)");

    Status_Init(&s, ST_RESET_WATCHDOG | ST_RESET_BROWNOUT);
    Status_SetIdMismatch(&s, true);
    Status_NoteDropped(&s);
    CHECK(Status_Compose(&s, true, true, true, false) == 127, "all seven bits together give 127");
    Status_NoteDropped(&s);
    CHECK(Status_Compose(&s, true, true, true, true) == 255, "all eight bits together give 255");

    /* ---- identity and sleep helpers ---- */
    CHECK(IMU_IdIsExpected(0x68), "WHO_AM_I 0x68 is accepted");
    CHECK(!IMU_IdIsExpected(0x70), "0x70 (MPU6500) is a mismatch");
    CHECK(!IMU_IdIsExpected(0x71), "0x71 (MPU9250) is a mismatch");
    CHECK(!IMU_IdIsExpected(0x00) && !IMU_IdIsExpected(0xFF), "0x00 and 0xFF are mismatches");
    CHECK(IMU_IsAsleep(0x40), "PWR_MGMT_1 0x40 is asleep (the power-up value is 0x40)");
    CHECK(!IMU_IsAsleep(0x00), "PWR_MGMT_1 0x00 is awake");
    CHECK(IMU_IsAsleep(0x41), "sleep bit with a clock source bit set is still asleep");
    CHECK(!IMU_IsAsleep(0x3F), "every bit but sleep set is awake");

    TEST_FINISH();
}
