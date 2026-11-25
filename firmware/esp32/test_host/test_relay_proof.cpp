// test_relay_proof.cpp - host test for outputs/relay_proof.cpp. a relay commanded on is never taken
// as switched: it is confirmed only by a coil's worth of rise on the relay rail once it has had time
// to pull in, and reported unconfirmed otherwise, including on a board with no rail reading.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_relay_proof.cpp ../outputs/relay_proof.cpp -o "${TMPDIR:-/tmp}/test_relay_proof" && "${TMPDIR:-/tmp}/test_relay_proof"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_relay_proof.cpp ../outputs/relay_proof.cpp -o "${TMPDIR:-/tmp}/test_relay_proof_san" && "${TMPDIR:-/tmp}/test_relay_proof_san"

#include <cstdint>
#include <cstdio>

#include "../outputs/relay_proof.h"

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

static const RailReading kNone = {false, 0};
static RailReading rail(int32_t ma) { return RailReading{true, ma}; }

// a board with no rail reading: a relay commanded on is reported unconfirmed at once and stays so
static void test_with_no_rail_reading_a_relay_on_is_unconfirmed() {
    RelayProofTracker t;
    t.command(0, true, 1000, kNone);
    CHECK(t.proof(0) == RELAY_UNCONFIRMED);
    CHECK(!t.waiting(0));
    t.tick(0, 5000, kNone);
    CHECK(t.proof(0) == RELAY_UNCONFIRMED);
    CHECK(t.unconfirmedMask() == 0x01);
}

// a coil that pulls in raises the rail by about 70 mA: confirmed once the pull-in time has passed
static void test_a_coils_worth_of_rise_confirms_it() {
    RelayProofTracker t;
    t.command(1, true, 1000, rail(120));
    CHECK(t.proof(1) == RELAY_UNCONFIRMED);
    CHECK(t.waiting(1));
    t.tick(1, 1000 + RELAY_PULL_IN_MS, rail(190));
    CHECK(t.proof(1) == RELAY_CONFIRMED);
    CHECK(!t.waiting(1));
    CHECK(t.unconfirmedMask() == 0);
}

// an input current too weak to switch the module: the rail barely moves and the relay stays unconfirmed
static void test_a_rise_smaller_than_a_coil_leaves_it_unconfirmed() {
    RelayProofTracker t;
    t.command(2, true, 1000, rail(120));
    t.tick(2, 1000 + RELAY_PULL_IN_MS, rail(120 + RELAY_COIL_MIN_RISE_MA - 1));
    CHECK(t.proof(2) == RELAY_UNCONFIRMED);
    CHECK(t.unconfirmedMask() == 0x04);
}

// the exact threshold counts as a pull-in
static void test_the_threshold_itself_confirms() {
    RelayProofTracker t;
    t.command(0, true, 0, rail(0));
    t.tick(0, RELAY_PULL_IN_MS, rail(RELAY_COIL_MIN_RISE_MA));
    CHECK(t.proof(0) == RELAY_CONFIRMED);
}

// a reading taken before the coil has had time to pull in is not used
static void test_a_reading_before_the_pull_in_time_is_not_judged() {
    RelayProofTracker t;
    t.command(0, true, 1000, rail(100));
    t.tick(0, 1000 + RELAY_PULL_IN_MS - 1, rail(100));
    CHECK(t.waiting(0));
    CHECK(t.proof(0) == RELAY_UNCONFIRMED);
    t.tick(0, 1000 + RELAY_PULL_IN_MS, rail(180));
    CHECK(t.proof(0) == RELAY_CONFIRMED);
}

// the meter failing between the two readings leaves it unconfirmed
static void test_a_lost_second_reading_leaves_it_unconfirmed() {
    RelayProofTracker t;
    t.command(3, true, 1000, rail(100));
    t.tick(3, 1100, kNone);
    CHECK(t.proof(3) == RELAY_UNCONFIRMED);
    CHECK(!t.waiting(3));
}

// switching off clears the proof and a later switch-on is judged afresh
static void test_off_clears_and_on_is_judged_again() {
    RelayProofTracker t;
    t.command(0, true, 0, rail(100));
    t.tick(0, 50, rail(180));
    CHECK(t.proof(0) == RELAY_CONFIRMED);
    t.command(0, false, 100, rail(180));
    CHECK(t.proof(0) == RELAY_OFF);
    CHECK(t.unconfirmedMask() == 0);
    t.command(0, true, 200, rail(100));
    CHECK(t.proof(0) == RELAY_UNCONFIRMED);
    t.tick(0, 260, rail(110));
    CHECK(t.proof(0) == RELAY_UNCONFIRMED);
}

// the millisecond timer wrapping between the two readings does not stop the judgement
static void test_a_timer_wrap_between_readings() {
    RelayProofTracker t;
    t.command(0, true, 0xFFFFFFF0u, rail(100));
    t.tick(0, 0x00000010u, rail(180));
    CHECK(t.proof(0) == RELAY_CONFIRMED);
}

// the four relays are judged on their own and an out-of-range channel is ignored
static void test_channels_are_independent_and_range_checked() {
    RelayProofTracker t;
    t.command(0, true, 0, rail(100));
    t.command(1, true, 0, kNone);
    t.tick(0, 30, rail(200));
    CHECK(t.proof(0) == RELAY_CONFIRMED);
    CHECK(t.proof(1) == RELAY_UNCONFIRMED);
    CHECK(t.unconfirmedMask() == 0x02);
    t.command(7, true, 0, rail(0));
    t.tick(7, 100, rail(500));
    CHECK(t.proof(7) == RELAY_OFF);
    CHECK(!t.waiting(7));
    CHECK(t.unconfirmedMask() == 0x02);
}

int main() {
    test_with_no_rail_reading_a_relay_on_is_unconfirmed();
    test_a_coils_worth_of_rise_confirms_it();
    test_a_rise_smaller_than_a_coil_leaves_it_unconfirmed();
    test_the_threshold_itself_confirms();
    test_a_reading_before_the_pull_in_time_is_not_judged();
    test_a_lost_second_reading_leaves_it_unconfirmed();
    test_off_clears_and_on_is_judged_again();
    test_a_timer_wrap_between_readings();
    test_channels_are_independent_and_range_checked();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed == 0 ? 0 : 1;
}
