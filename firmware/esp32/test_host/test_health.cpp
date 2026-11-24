// test_health.cpp - host test for the pure fault logic: the health table, the link watch,
// the unplugged bands and the 12 V conversion.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_health.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_health" && "${TMPDIR:-/tmp}/test_health"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_health.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_health_san" && "${TMPDIR:-/tmp}/test_health_san"
// the water tests depend on HAS_PROBE_SERIES_R, so the same test is also built for the revised board:
//   c++ -std=c++17 -Wall -Wextra -DHAS_PROBE_SERIES_R=1 -DHAS_INPUT_PULLDOWNS=1 -I.. test_health.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_health_revb" && "${TMPDIR:-/tmp}/test_health_revb"

#include <cmath>
#include <cstdio>
#include <cstring>

#include "../sensors/analog_checks.h"
#include "../sensors/content_checks.h"
#include "../sensors/shaft_math.h"
#include "../sensors/board_check.h"
#include "../sensors/fitted.h"
#include "../sensors/stuck_check.h"
#include "../sensors/health.h"

static int g_checks = 0;
static int g_failed = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        g_checks++;                                                          \
        if (!(cond)) {                                                       \
            g_failed++;                                                      \
            std::printf("FAIL line %d: %s\n", __LINE__, #cond);              \
        }                                                                    \
    } while (0)

static void testNames() {
    CHECK(std::strcmp(healthKeyName(SK_BME280), "bme280") == 0);
    CHECK(std::strcmp(healthKeyName(SK_NANO_LINK), "nano_link") == 0);
    CHECK(std::strcmp(healthKeyName(SK_STM32_LINK), "stm32_link") == 0);
    CHECK(std::strcmp(healthKeyName(SK_SUPPLY), "supply") == 0);
    CHECK(std::strcmp(healthStateName(HS_MISSING), "missing") == 0);
    CHECK(std::strcmp(healthStateName(HS_OUT_OF_RANGE), "out_of_range") == 0);
    CHECK(std::strcmp(healthStateName(HS_WARMING_UP), "warming_up") == 0);
    CHECK(std::strcmp(healthStateName(HS_LINE_LOW), "line_low") == 0);
    CHECK(std::strcmp(healthStateName(HS_SILENT), "silent") == 0);
    CHECK(std::strcmp(healthStateName(HS_UNPLUGGED), "unplugged") == 0);
    CHECK(std::strcmp(healthKeyName(SK_FC28), "fc28") == 0);
    CHECK(std::strcmp(healthKeyName(SK_MAX4466), "max4466") == 0);
    CHECK(std::strcmp(healthKeyName(SK_NANO_BME280), "nano_bme280") == 0);
    CHECK(std::strcmp(healthKeyName(SK_NANO_SUPPLY), "nano_supply") == 0);
    CHECK(std::strcmp(healthKeyName(SK_STM32_MPU6050), "stm32_mpu6050") == 0);
    CHECK(std::strcmp(healthStateName(HS_STUCK), "stuck") == 0);
    CHECK(std::strcmp(healthStateName(HS_GARBAGE), "garbage") == 0);
    CHECK(std::strcmp(healthStateName(HS_ONE_WAY), "one_way") == 0);
    CHECK(SK_COUNT == 25);
    CHECK(std::strcmp(healthKeyName(SK_EXPANDER), "expander") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_AUX), "aux_rail") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_FEED1), "feed1_rail") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_FEED2), "feed2_rail") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_FEED3), "feed3_rail") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_SENS), "sens_rail") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_STRIP), "strip_rail") == 0);
    CHECK(std::strcmp(healthKeyName(SK_RAIL_ENABLE), "enable_rail") == 0);
    CHECK(std::strcmp(healthStateName(HS_INTERMITTENT), "intermittent") == 0);
}

static void testMissingNeedsThreeInARow() {
    healthInit();
    CHECK(!healthAnyFault());
    CHECK(!healthObserveAbsent(SK_MPU6050, true, 1000));
    CHECK(!healthObserveAbsent(SK_MPU6050, true, 2000));
    CHECK(healthState(SK_MPU6050) == HS_OK);
    // a good probe in between restarts the run.
    CHECK(!healthObserveAbsent(SK_MPU6050, false, 3000));
    CHECK(!healthObserveAbsent(SK_MPU6050, true, 4000));
    CHECK(!healthObserveAbsent(SK_MPU6050, true, 5000));
    // not missing, but four failures inside a minute are intermittent
    CHECK(healthState(SK_MPU6050) == HS_INTERMITTENT);
    CHECK(healthObserveAbsent(SK_MPU6050, true, 6000));
    CHECK(healthState(SK_MPU6050) == HS_MISSING);
    CHECK(healthSince(SK_MPU6050) == 6000);
    CHECK(healthAnyFault());
    // the since time holds while the fault lasts.
    CHECK(healthObserveAbsent(SK_MPU6050, true, 9000));
    CHECK(healthSince(SK_MPU6050) == 6000);
    // a present probe does not clear it. the caller sets the sensor up and then clears it.
    CHECK(healthObserveAbsent(SK_MPU6050, false, 10000));
    CHECK(healthState(SK_MPU6050) == HS_MISSING);
    CHECK(healthSet(SK_MPU6050, HS_OK, 10500));
    // the recent failures still read as a flap until a minute has passed
    CHECK(healthState(SK_MPU6050) == HS_INTERMITTENT);
    // a second outage needs three more misses again.
    CHECK(!healthObserveAbsent(SK_MPU6050, true, 11000));
    CHECK(!healthObserveAbsent(SK_MPU6050, true, 12000));
    CHECK(healthObserveAbsent(SK_MPU6050, true, 13000));
    // other sensors are untouched.
    CHECK(healthState(SK_BME280) == HS_OK);
}

static void testSetReportsChange() {
    healthInit();
    CHECK(healthSet(SK_MQ2, HS_WARMING_UP, 100));
    CHECK(!healthSet(SK_MQ2, HS_WARMING_UP, 200));
    CHECK(healthSince(SK_MQ2) == 100);
    CHECK(healthSet(SK_MQ2, HS_OK, 300));
    CHECK(healthSince(SK_MQ2) == 300);
}

static HealthState link(const LinkWatch& wIn, uint32_t now) {
    LinkWatch w = wIn;      // linkState keeps its latch in the watch, so judge a copy
    return linkState(&w, now, LINK_LINE_LOW_MS, LINK_LINE_LOW_MIN_SAMPLES, LINK_SILENT_MS);
}

static void testLinkLineLow() {
    LinkWatch w;
    linkReset(&w, 0);
    // a line that rests low, sampled every 100 ms, once the start-up window has passed.
    uint32_t t = 20000;
    linkReset(&w, 0);
    linkNoteValid(&w, 20000);
    for (; t < 24900; t += SERIAL_POLL_MS) linkNoteLevel(&w, false, t);
    CHECK(link(w, 24900) == HS_OK);
    for (; t <= 25100; t += SERIAL_POLL_MS) linkNoteLevel(&w, false, t);
    CHECK(link(w, 25100) == HS_LINE_LOW);
    // one high sample ends the run.
    linkNoteLevel(&w, true, 25200);
    CHECK(link(w, 25200) == HS_OK);
}

static void testLinkLowNeedsSamples() {
    // two low samples seconds apart (a long blocking post between them) are not a run.
    LinkWatch w;
    linkReset(&w, 0);
    linkNoteLevel(&w, false, 21000);
    linkNoteLevel(&w, false, 27000);
    linkNoteValid(&w, 26000);
    CHECK(link(w, 27000) == HS_OK);
}

static void testLinkBytesBlockLineLow() {
    LinkWatch w;
    linkReset(&w, 0);
    uint32_t t = 10000;
    linkNoteValid(&w, 25000);
    for (; t < 26000; t += SERIAL_POLL_MS) linkNoteLevel(&w, false, t);
    CHECK(link(w, 26000) == HS_LINE_LOW);
    linkNoteByte(&w, 26000);
    CHECK(link(w, 26000) == HS_OK);
}

static void testLinkSilent() {
    LinkWatch w;
    linkReset(&w, 0);
    // idles high and carries nothing.
    uint32_t t = 0;
    for (; t < 14900; t += SERIAL_POLL_MS) linkNoteLevel(&w, true, t);
    CHECK(link(w, 14900) == HS_OK);
    CHECK(link(w, 15000) == HS_SILENT);
    // a valid line brings it back and the clock restarts.
    linkNoteByte(&w, 15100);
    linkNoteValid(&w, 15100);
    CHECK(link(w, 15100) == HS_OK);
    CHECK(link(w, 30000) == HS_OK);
    CHECK(link(w, 30100) == HS_SILENT);
    // bytes that never form a valid line still count as silent.
    linkNoteByte(&w, 31000);
    CHECK(link(w, 31000) == HS_SILENT);
}

static void testLinkStartupWindow() {
    // nothing is reported until the link has had its full silent window since boot, for a
    // line that rests low and for one that idles high alike.
    LinkWatch low;
    linkReset(&low, 1000);
    for (uint32_t t = 1000; t < 1000 + LINK_SILENT_MS; t += SERIAL_POLL_MS) linkNoteLevel(&low, false, t);
    CHECK(link(low, 1000 + LINK_SILENT_MS - 1) == HS_OK);
    CHECK(link(low, 1000 + LINK_SILENT_MS) == HS_LINE_LOW);

    LinkWatch quiet;
    linkReset(&quiet, 1000);
    CHECK(link(quiet, 1000) == HS_OK);
    CHECK(link(quiet, 1000 + LINK_SILENT_MS - 1) == HS_OK);
    CHECK(link(quiet, 1000 + LINK_SILENT_MS) == HS_SILENT);

    // a valid line inside the window keeps it clean afterwards.
    LinkWatch fed;
    linkReset(&fed, 1000);
    linkNoteByte(&fed, 3000);
    linkNoteValid(&fed, 3000);
    CHECK(link(fed, 1000 + LINK_SILENT_MS) == HS_OK);
}

static void testLinkRollover() {
    // millis() wraps after about 49 days. the maths must still work across it.
    LinkWatch w;
    uint32_t start = 0xFFFFFF00u;
    linkReset(&w, start);
    CHECK(link(w, start + 1000) == HS_OK);
    CHECK(link(w, start + LINK_SILENT_MS) == HS_SILENT);
}

static void testMicBands() {
    CHECK(micState(0.0f) == HS_UNPLUGGED);
    CHECK(micState(MIC_UNPLUGGED_MAX_COUNTS) == HS_UNPLUGGED);
    CHECK(micState(MIC_UNPLUGGED_MAX_COUNTS + 1) == HS_OK);
    // a working module idles near half the supply, about 2000 counts.
    CHECK(micState(2000.0f) == HS_OK);
    CHECK(micState(4095.0f) == HS_OUT_OF_RANGE);
    CHECK(micState(MIC_RAIL_MIN_COUNTS - 1) == HS_OK);
}

static void testMoistureBands() {
    // a reading near zero is named only after MOISTURE_UNPLUGGED_PASSES passes in a row.
    uint8_t run = 0;
    CHECK(moistureState(0.0f, &run) == HS_OK);
    CHECK(moistureState(0.0f, &run) == HS_OK);
    CHECK(moistureState(0.0f, &run) == HS_UNPLUGGED);
    // one good pass clears the run.
    CHECK(moistureState(2000.0f, &run) == HS_OK);
    CHECK(run == 0);
    CHECK(moistureState(0.0f, &run) == HS_OK);
    // the edge of the band.
    run = 0;
    for (int i = 0; i < 3; i++) moistureState(MOISTURE_UNPLUGGED_BAND, &run);
    CHECK(moistureState(MOISTURE_UNPLUGGED_BAND, &run) == HS_UNPLUGGED);
    run = 0;
    for (int i = 0; i < 5; i++) CHECK(moistureState(MOISTURE_UNPLUGGED_BAND + 1, &run) == HS_OK);
    // a dry probe reads high, up to the top of the scale. is never a fault.
    run = 0;
    for (int i = 0; i < 5; i++) CHECK(moistureState(4095.0f, &run) == HS_OK);
    for (int i = 0; i < 5; i++) CHECK(moistureState(3700.0f, &run) == HS_OK);
}

static void testRecovery() {
    Recovery r;
    recoveryInit(&r);
    // never set up: a try is allowed at once.
    CHECK(recoveryMayTry(&r, 0, 10000));
    recoveryNoteTry(&r, true, 100);
    CHECK(r.ready);
    CHECK(!recoveryMayTry(&r, 99999, 10000));
    // ONE lost probe is enough to want a new set-up, not three.
    recoveryNoteLost(&r);
    CHECK(!r.ready);
    // but not before the rate limit allows it.
    CHECK(!recoveryMayTry(&r, 5000, 10000));
    CHECK(recoveryMayTry(&r, 10100, 10000));
    recoveryNoteTry(&r, true, 10100);
    CHECK(r.ready);
    // a failed set-up stays wanted and waits for the next interval.
    recoveryNoteLost(&r);
    recoveryNoteTry(&r, false, 20000);
    CHECK(!r.ready);
    CHECK(!recoveryMayTry(&r, 29999, 10000));
    CHECK(recoveryMayTry(&r, 30000, 10000));
    // a flapping part is tried at most once per interval however often it comes and goes.
    int tries = 0;
    for (uint32_t t = 30000; t < 60000; t += 500) {
        recoveryNoteLost(&r);
        if (recoveryMayTry(&r, t, 10000)) {
            recoveryNoteTry(&r, true, t);
            tries++;
        }
    }
    CHECK(tries == 3);
    // the rate limit holds across a millis() rollover.
    recoveryInit(&r);
    recoveryNoteTry(&r, false, 0xFFFFFF00u);
    CHECK(!recoveryMayTry(&r, 0xFFFFFF00u + 5000, 10000));
    CHECK(recoveryMayTry(&r, 0xFFFFFF00u + 10000, 10000));
}

static void testRecoveryContent() {
    Recovery r;
    recoveryInit(&r);
    recoveryNoteTry(&r, true, 0);
    // bad content for the limit in a row clears ready.
    CHECK(!recoveryNoteContent(&r, true, 3));
    CHECK(!recoveryNoteContent(&r, true, 3));
    CHECK(r.ready);
    CHECK(recoveryNoteContent(&r, true, 3));
    CHECK(!r.ready);
    // a good pass in between restarts the count.
    recoveryNoteTry(&r, true, 100);
    CHECK(!recoveryNoteContent(&r, true, 3));
    CHECK(!recoveryNoteContent(&r, true, 3));
    CHECK(!recoveryNoteContent(&r, false, 3));
    CHECK(!recoveryNoteContent(&r, true, 3));
    CHECK(r.ready);
    // a limit of one acts at once (a NAN from the BME280, the MPU6050 sleep bit).
    CHECK(recoveryNoteContent(&r, true, 1));
    CHECK(!r.ready);
}

static void testContentChecks() {
    // MPU6050 sleep bit is bit 6 of PWR_MGMT_1. the set-up leaves 0x01.
    CHECK(mpuSleepBitSet(0x40));
    CHECK(mpuSleepBitSet(0x41));
    CHECK(!mpuSleepBitSet(0x01));
    CHECK(!mpuSleepBitSet(0x00));
    CHECK(mpuAllZero(0.0f, 0.0f, 0.0f));
    CHECK(!mpuAllZero(0.0f, 0.0f, 0.98f));
    CHECK(!mpuAllZero(0.001f, 0.0f, 0.0f));
    // INA219: the calibration register resets to zero. the set-up writes 4096.
    CHECK(inaLostSetup(0));
    CHECK(!inaLostSetup(4096));
    CHECK(inaOverflow(0x0001));
    CHECK(inaOverflow(0x1F43));
    CHECK(!inaOverflow(0x1F42));
    // AS5600: MD (0x20) must be set. MH 0x08 and ML 0x10 only note a marginal gap.
    CHECK(as5600MagnetState(0x20) == HS_OK);
    CHECK(as5600MagnetState(0x28) == HS_OK);
    CHECK(as5600MagnetState(0x30) == HS_OK);
    CHECK(as5600MagnetState(0x00) == HS_OUT_OF_RANGE);
    CHECK(as5600MagnetState(0x10) == HS_OUT_OF_RANGE);
    CHECK(!as5600MagnetMarginal(0x20));
    CHECK(as5600MagnetMarginal(0x28));
    CHECK(as5600MagnetMarginal(0x30));
}

static void testSupply() {
    // 12 V at the connector reads about 1.05 V at the pin. the divider is 100 k over 10 k.
    float v = inputVoltsFromPinMilliVolts(1050.0f);
    CHECK(std::fabs(v - 11.55f) < 0.001f);
    CHECK(std::fabs(inputVoltsFromPinMilliVolts(1000.0f) - 11.0f) < 0.001f);
    CHECK(std::fabs(inputVoltsFromPinMilliVolts(0.0f)) < 0.001f);
    CHECK(supplyState(11.55f) == HS_OK);
    CHECK(supplyState(9.0f) == HS_OK);
    CHECK(supplyState(8.99f) == HS_OUT_OF_RANGE);
    CHECK(supplyState(15.0f) == HS_OK);
    CHECK(supplyState(15.01f) == HS_OUT_OF_RANGE);
    CHECK(supplyState(0.0f) == HS_OUT_OF_RANGE);
}


static void testFlap() {
    // three failed probes inside a minute that never run three in a row: intermittent
    healthInit();
    healthObserveAbsent(SK_BME280, true, 1000);
    CHECK(healthState(SK_BME280) == HS_OK);
    healthObserveAbsent(SK_BME280, false, 6000);
    healthObserveAbsent(SK_BME280, true, 11000);
    healthObserveAbsent(SK_BME280, false, 16000);
    CHECK(healthState(SK_BME280) == HS_OK);
    healthObserveAbsent(SK_BME280, true, 21000);
    CHECK(healthState(SK_BME280) == HS_INTERMITTENT);
    CHECK(healthSince(SK_BME280) == 21000);
    CHECK(healthAnyFault());
    // the sensor's own state is still ok underneath. the overlay holds while the window does
    healthObserveAbsent(SK_BME280, false, 26000);
    CHECK(healthState(SK_BME280) == HS_INTERMITTENT);
    healthSet(SK_BME280, HS_OK, 27000);
    CHECK(healthState(SK_BME280) == HS_INTERMITTENT);
    // it expires once the oldest of the three falls out of the minute
    healthObserveAbsent(SK_BME280, false, 60999);
    CHECK(healthState(SK_BME280) == HS_INTERMITTENT);
    healthObserveAbsent(SK_BME280, false, 61001);
    CHECK(healthState(SK_BME280) == HS_OK);
    CHECK(!healthAnyFault());

    // spread over more than a minute is not a flap
    healthInit();
    healthObserveAbsent(SK_MPU6050, true, 0);
    healthObserveAbsent(SK_MPU6050, false, 20000);
    healthObserveAbsent(SK_MPU6050, true, 40000);
    healthObserveAbsent(SK_MPU6050, false, 60000);
    healthObserveAbsent(SK_MPU6050, true, 80000);
    CHECK(healthState(SK_MPU6050) == HS_OK);

    // the sensor's own fault speaks first
    healthInit();
    healthObserveAbsent(SK_MPU6050, true, 1000);
    healthObserveAbsent(SK_MPU6050, false, 2000);
    healthObserveAbsent(SK_MPU6050, true, 3000);
    healthObserveAbsent(SK_MPU6050, false, 4000);
    healthObserveAbsent(SK_MPU6050, true, 5000);
    healthSet(SK_MPU6050, HS_OUT_OF_RANGE, 5000);
    CHECK(healthState(SK_MPU6050) == HS_OUT_OF_RANGE);
    // three in a row is missing, which also outranks the overlay
    healthInit();
    healthObserveAbsent(SK_INA219, true, 1000);
    healthObserveAbsent(SK_INA219, true, 2000);
    healthObserveAbsent(SK_INA219, true, 3000);
    CHECK(healthState(SK_INA219) == HS_MISSING);
    CHECK(std::strcmp(healthStateName(HS_INTERMITTENT), "intermittent") == 0);
}

static void testBmeLostSetup() {
    // ctrl_meas (0xF4) mode bits are 1 and 0. a reset part reads 0 (sleep). the set-up leaves
    // normal mode (3) and a forced conversion shows as 1 or 2 for a moment.
    CHECK(bmeLostSetup(0x00));
    CHECK(bmeLostSetup(0x24));            // oversampling set but mode 00
    CHECK(bmeLostSetup(0xFC));
    CHECK(!bmeLostSetup(0x27));           // normal mode, x1 and x1
    CHECK(!bmeLostSetup(0x03));
    CHECK(!bmeLostSetup(0x01));
    CHECK(!bmeLostSetup(0x02));
    CHECK(!bmeLostSetup(0xFF));
}

static void testDs18PowerOn() {
    // a reset part holds exactly 85.0 until its first conversion ends
    CHECK(ds18PowerOnValue(85.0f, 0.0f, false));
    CHECK(ds18PowerOnValue(85.0f, 22.0f, true));
    CHECK(ds18PowerOnValue(85.0f, 79.9f, true));
    // a real temperature climbing through 85.0 is believed
    CHECK(!ds18PowerOnValue(85.0f, 84.9f, true));
    CHECK(!ds18PowerOnValue(85.0f, 80.0f, true));
    CHECK(!ds18PowerOnValue(85.0f, 90.0f, true));
    // any other value is not the power-on value
    CHECK(!ds18PowerOnValue(84.9375f, 22.0f, true));
    CHECK(!ds18PowerOnValue(22.0f, 22.0f, true));
}

static void testShaft() {
    // a shaft at 60 rpm turns 7.2 degrees per 20 ms sample
    ShaftWindow w;
    shaftInit(&w, 0);
    float deg = 10.0f;
    uint32_t t = 0;
    for (; t <= 5000; t += 20) {
        shaftNoteSample(&w, deg, t);
        deg = std::fmod(deg + 7.2f, 360.0f);
    }
    float rpm = 0;
    CHECK(shaftResult(&w, 5000, &rpm));
    CHECK(std::fabs(rpm - 60.0f) < 1.0f);

    // a blocked loop (a 400 ms gap with no samples) used to make the rpm read low by the share
    // of time lost. the covered time is used now, so it still reads 60
    shaftInit(&w, 0);
    deg = 10.0f;
    for (t = 0; t <= 5000; t += 20) {
        if (t >= 2000 && t < 2400) { deg = std::fmod(deg + 7.2f, 360.0f); continue; }
        shaftNoteSample(&w, deg, t);
        deg = std::fmod(deg + 7.2f, 360.0f);
    }
    CHECK(shaftResult(&w, 5000, &rpm));
    CHECK(std::fabs(rpm - 60.0f) < 2.0f);

    // a gap longer than the limit is dropped, movement and time together
    shaftInit(&w, 0);
    shaftNoteSample(&w, 0.0f, 0);
    shaftNoteSample(&w, 100.0f, 100);     // 100 ms gap: not counted
    CHECK(w.coveredMs == 0 && w.totalDeg == 0.0f);
    shaftNoteSample(&w, 107.2f, 120);
    CHECK(w.coveredMs == 20);

    // too little of the window covered: no rpm
    shaftInit(&w, 0);
    for (t = 0; t <= 1000; t += 20) shaftNoteSample(&w, 0.0f, t);   // one second of samples
    CHECK(!shaftResult(&w, 5000, &rpm));
    CHECK(rpm == 0.0f);

    // the wrap at 360 and a reverse shaft
    shaftInit(&w, 0);
    shaftNoteSample(&w, 359.0f, 0);
    shaftNoteSample(&w, 3.0f, 20);        // +4 across the wrap
    CHECK(std::fabs(w.totalDeg - 4.0f) < 1e-4f);
    shaftNoteSample(&w, 359.0f, 40);      // -4
    CHECK(std::fabs(w.totalDeg) < 1e-4f);
    // a millis() rollover mid-window
    shaftInit(&w, 0xFFFFFF00u);
    shaftNoteSample(&w, 0.0f, 0xFFFFFF00u);
    shaftNoteSample(&w, 7.2f, 0xFFFFFF14u);
    shaftNoteSample(&w, 14.4f, 0xFFFFFF28u);
    CHECK(w.coveredMs == 40);
}

static void testWaterAlarm() {
    // the counts the threshold is worked out from (see config.h): in water about 1270 to 1700,
    // the Nano's equivalent about 2130, damp about 2180 to 3040, dry about 3950
    CHECK(WATER_THRESHOLD == 2000);
    CHECK(WATER_THRESHOLD > 1700 + 250);               // above the top of the in-water band
    CHECK(WATER_THRESHOLD < 2130);                     // under the Nano's equivalent
    CHECK(WATER_THRESHOLD < 2180);                     // under the damp band
    CHECK(waterAlarm(1270) && waterAlarm(1700));       // in water
    CHECK(waterAlarm(1999) && !waterAlarm(2000));
    CHECK(!waterAlarm(2500) && !waterAlarm(3040));     // damp
    CHECK(!waterAlarm(3950) && !waterAlarm(4095));     // dry
    CHECK(waterAlarm(790));                            // flooded or shorted, about 0.6 V
#if HAS_PROBE_SERIES_R
    // with the series resistor an unplugged probe is told apart from a flooded one
    CHECK(!waterAlarm(0) && !waterAlarm(100) && !waterAlarm(PROBE_UNPLUGGED_MAX_COUNTS));
    CHECK(waterAlarm(PROBE_UNPLUGGED_MAX_COUNTS + 1));
    CHECK(PROBE_UNPLUGGED_MAX_COUNTS < 790 / 2);       // well under the flooded level
    uint8_t run = 0;
    CHECK(moistureState(0.0f, &run) == HS_OK);
    CHECK(moistureState(0.0f, &run) == HS_OK);
    CHECK(moistureState(0.0f, &run) == HS_UNPLUGGED);  // three passes
    // a flooded probe is never called unplugged and does alarm
    run = 0;
    for (int i = 0; i < 5; i++) CHECK(moistureState(790.0f, &run) == HS_OK);
    CHECK(waterAlarm(790));
    // the unplugged band edge
    run = 0;
    for (int i = 0; i < 3; i++) moistureState((float)PROBE_UNPLUGGED_MAX_COUNTS, &run);
    CHECK(moistureState((float)PROBE_UNPLUGGED_MAX_COUNTS, &run) == HS_UNPLUGGED);
    run = 0;
    for (int i = 0; i < 5; i++) CHECK(moistureState(PROBE_UNPLUGGED_MAX_COUNTS + 1.0f, &run) == HS_OK);
#else
    // without it the safe rule stays: near zero keeps the alarm on, because an unplugged input
    // and a flooded probe cannot be told apart
    CHECK(waterAlarm(0) && waterAlarm(10) && waterAlarm(49));
#endif
    CHECK(PROBE_FLOODED_NOMINAL_MV == 600 && PROBE_DRY_NOMINAL_MV == 3000);
    // one named constant and the proven flag starts at 0, so the hub says UNPROVEN at boot
    CHECK(WATER_ALARM_PROVEN == 0);
}

static void testMq2Fault() {
    // after the warm-up an analogue reading near zero is a fault whatever the digital line says.
    // an unplugged module reads about 0 counts. clean air on a heated MQ-2 is about 200 to 530
    CHECK(mq2ReadingIsFault(0));
    CHECK(mq2ReadingIsFault(MQ2_FAULT_ADC_MAX - 1));
    CHECK(!mq2ReadingIsFault(MQ2_FAULT_ADC_MAX));
    CHECK(!mq2ReadingIsFault(200) && !mq2ReadingIsFault(530) && !mq2ReadingIsFault(4095));
    CHECK(MQ2_FAULT_ADC_MAX == 100);
}

static void testBoardCheck() {
    // every input combination. the verdict is the image against what the bus proves
    for (int img = 0; img < 2; img++)
    for (int idle = 0; idle < 2; idle++)
    for (int mcp = 0; mcp < 2; mcp++)
    for (int other = 0; other < 2; other++) {
        BoardVerdict v = boardVerdict(img, idle, mcp, other);
        // an answer from the expander proves the revised board whatever else is true
        if (mcp) CHECK(v == (img ? BOARD_OK : BOARD_MISMATCH));
        // absence is believed only on a bus that idles high and shows another device answering
        else if (idle && other) CHECK(v == (img ? BOARD_MISMATCH : BOARD_OK));
        else CHECK(v == BOARD_UNKNOWN);
        // GPIO14 is driven as relay 3 only by the present-board image with a proven present board
        CHECK(mayDriveGpio14AsRelay(img, v) == (!img && v == BOARD_OK));
        // the sensor supply is switched only by the revised-board image with a proven revised board
        CHECK(maySwitchSensorRail(img, v) == (img && v == BOARD_OK));
        // any doubt: neither
        if (v != BOARD_OK) CHECK(!mayDriveGpio14AsRelay(img, v) && !maySwitchSensorRail(img, v));
    }
    CHECK(BOARD_PROBE_TRIES >= 3 && BOARD_PROBE_GAP_MS > 0);
}

static void testFlapExpiresAcrossAlias() {
    // three old failures must never read as recent when millis() aliases 49.7 days on
    healthInit();
    uint32_t t0 = 1000;
    healthObserveAbsent(SK_VL53L0X, true, t0);
    healthObserveAbsent(SK_VL53L0X, false, t0 + 5000);
    healthObserveAbsent(SK_VL53L0X, true, t0 + 10000);
    healthObserveAbsent(SK_VL53L0X, false, t0 + 15000);
    healthObserveAbsent(SK_VL53L0X, true, t0 + 20000);
    CHECK(healthState(SK_VL53L0X) == HS_INTERMITTENT);
    // the sensor is probed every pass, so the failures are forgotten once they are a minute old
    for (uint32_t t = t0 + 25000; t < t0 + 100000; t += 5000) healthObserveAbsent(SK_VL53L0X, false, t);
    CHECK(healthState(SK_VL53L0X) == HS_OK);
    // then a long way on, across the alias, nothing comes back
    uint32_t alias = t0 + 20000 + 0xFFFFFFFFu - 4000;   // just under 2^32 ms later, by unsigned arithmetic
    healthObserveAbsent(SK_VL53L0X, false, alias);
    CHECK(healthState(SK_VL53L0X) == HS_OK);
    healthObserveAbsent(SK_VL53L0X, false, t0 + 25000 + 0xFFFFFFFFu);
    CHECK(healthState(SK_VL53L0X) == HS_OK);
}


static void testGasJudge() {
    // either path alarms. the analogue level has its own named threshold
    CHECK(GAS_ANALOGUE_ALARM_COUNTS > MQ2_CLEAN_AIR_MAX_COUNTS);
    CHECK(GAS_ALARM_PROVEN == 0);
    GasJudgement g = gasJudge(300, false);
    CHECK(!g.alarm && !g.fault && !g.disagree);
    g = gasJudge(GAS_ANALOGUE_ALARM_COUNTS, false);          // analogue only
    CHECK(g.alarm && g.analogueAlarm && !g.digitalAlarm && !g.disagree);
    g = gasJudge(GAS_ANALOGUE_ALARM_COUNTS - 1, false);
    CHECK(!g.alarm);
    g = gasJudge(1000, true);                                // digital only, analogue between the bands
    CHECK(g.alarm && g.digitalAlarm && !g.analogueAlarm && !g.disagree);
    g = gasJudge(2000, true);                                // both
    CHECK(g.alarm && g.digitalAlarm && g.analogueAlarm && !g.disagree);
    g = gasJudge(300, true);                                 // digital alarm on a clean analogue level: a disagreement, still alarming
    CHECK(g.alarm && g.disagree);
    g = gasJudge(MQ2_CLEAN_AIR_MAX_COUNTS + 1, true);
    CHECK(g.alarm && !g.disagree);
    g = gasJudge(0, true);                                   // near zero is a fault and raises nothing
    CHECK(g.fault && !g.alarm && !g.digitalAlarm && !g.analogueAlarm);
    g = gasJudge(MQ2_FAULT_ADC_MAX - 1, false);
    CHECK(g.fault && !g.alarm);
    // every raw value and both digital states: the alarm is exactly the union of the two paths
    for (int raw = 0; raw <= 4095; raw++) {
        for (int d = 0; d < 2; d++) {
            GasJudgement x = gasJudge(raw, d);
            bool fault = raw < MQ2_FAULT_ADC_MAX;
            CHECK(x.fault == fault);
            CHECK(x.alarm == (!fault && (d || raw >= GAS_ANALOGUE_ALARM_COUNTS)));
        }
    }
}

static void testStuckDetector() {
    StuckDetector d;
    stuckReset(&d);
    uint8_t a[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
    uint8_t b[8] = { 1, 2, 3, 4, 5, 6, 7, 9 };
    for (int i = 0; i < BME_STUCK_READS - 1; i++) CHECK(!stuckNote(&d, a, BME_STUCK_READS));
    CHECK(stuckNote(&d, a, BME_STUCK_READS));                // the 24th identical read
    CHECK(stuckNote(&d, a, BME_STUCK_READS));                // and it stays stuck
    CHECK(!stuckNote(&d, b, BME_STUCK_READS));               // one changed low bit ends it
    // a part whose lowest bit changes now and then is never stuck
    stuckReset(&d);
    bool any = false;
    for (int i = 0; i < 1000; i++) {
        uint8_t w[8] = { 1, 2, 3, 4, 5, 6, 7, (uint8_t)((i / 10) & 1) };
        any = any || stuckNote(&d, w, BME_STUCK_READS);
    }
    CHECK(!any);                                             // runs of ten never reach 24
    stuckReset(&d);
    CHECK(!stuckNote(&d, a, BME_STUCK_READS));
}

static void testFitted() {
    // the defaults are everything fitted
    CHECK(HAS_BME280 && HAS_MPU6050 && HAS_INA219 && HAS_MLX90614 && HAS_VL53L0X && HAS_AS5600);
    CHECK(HAS_DS18B20 && HAS_MQ2 && HAS_LDR && HAS_MAX4466);
    CHECK(sensorFitted(SK_BME280) == (HAS_BME280 != 0));
    CHECK(sensorFitted(SK_MQ2) == (HAS_MQ2 != 0));
    CHECK(sensorFitted(SK_DS18B20) == (HAS_DS18B20 != 0));
    CHECK(TEMP_ANY_FITTED);
}

int main() {
    testNames();
    testMissingNeedsThreeInARow();
    testSetReportsChange();
    testLinkLineLow();
    testLinkLowNeedsSamples();
    testLinkBytesBlockLineLow();
    testLinkSilent();
    testLinkStartupWindow();
    testLinkRollover();
    testMicBands();
    testMoistureBands();
    testRecovery();
    testRecoveryContent();
    testContentChecks();
    testFlap();
    testBmeLostSetup();
    testDs18PowerOn();
    testShaft();
    testWaterAlarm();
    testMq2Fault();
    testBoardCheck();
    testFlapExpiresAcrossAlias();
    testSupply();
    testGasJudge();
    testStuckDetector();
    testFitted();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
