// mcp23017_logic.h - the decisions of the port expander driver, with no Arduino types, so the host
// test drives them against a scripted chip (test_host/test_expander.cpp). sensors/mcp23017.cpp binds
// them to the real I2C bus on the revised board. nothing here has run on a board and no revised
// board has been made.
//
// the chip is the MCP23017 at 0x20. the pin table below is a copy of the board's port table (second
// issue, 22 November 2026) and test_host/fixtures/expander_pins.md is the copy the test compares it
// with, line for line. the hardware files are the source and win if the two disagree.
//
// the polarity of every input lives in that one table. six rail inputs go through an NPN transistor
// with a pull-up, so they read LOW when the rail is up and HIGH when it is absent. SENS_OK is a plain
// divider and reads HIGH when the rail is up. the button reads LOW when pressed. "present" means the
// rail is up and nothing more: it does not mean the rail is in range.
//
// what the driver does, in short:
//   - start: write the configuration register in the way that is right for either addressing mode,
//     write every other register explicitly, read all 22 back and refuse to trust the chip if any
//     differs from what was written.
//   - poll: one two-byte read of GPIOA and GPIOB every EXPANDER_POLL_MS. no interrupt line reaches
//     the module. every EXPANDER_CONFIG_CHECK_MS all 22 registers are read back again.
//   - the button and the seven rail inputs are debounced in firmware. a rail near its threshold
//     cannot flap: it reports only after RAIL_DEBOUNCE_MS of the same reading.
//   - every failure ends the call at the first failed transaction, so a call never holds the main
//     loop for more than one bus time-out, which the core sets at about 50 ms.
#pragma once

#include <stdint.h>
#include <stdio.h>

#include "../config.h"
#include "board_check.h"
#include "health.h"

namespace mcp {

// ─── registers (IOCON.BANK = 0, the map this driver always leaves the chip in) ──────────────────
enum Reg : uint8_t {
    REG_IODIRA = 0x00, REG_IODIRB = 0x01,
    REG_IPOLA = 0x02, REG_IPOLB = 0x03,
    REG_GPINTENA = 0x04, REG_GPINTENB = 0x05,
    REG_DEFVALA = 0x06, REG_DEFVALB = 0x07,
    REG_INTCONA = 0x08, REG_INTCONB = 0x09,
    REG_IOCON = 0x0A, REG_IOCON_MIRROR = 0x0B,
    REG_GPPUA = 0x0C, REG_GPPUB = 0x0D,
    REG_INTFA = 0x0E, REG_INTFB = 0x0F,
    REG_INTCAPA = 0x10, REG_INTCAPB = 0x11,
    REG_GPIOA = 0x12, REG_GPIOB = 0x13,
    REG_OLATA = 0x14, REG_OLATB = 0x15
};
const uint8_t REG_COUNT = 0x16;
// where IOCON sits when BANK = 1 (data sheet DS20001952D table 3-4). writing the BANK = 0 value
// there first is what makes the start correct in either mode.
const uint8_t REG_IOCON_BANK1 = 0x05;
// BANK 0, MIRROR 0, SEQOP 0 (sequential reads on), DISSLW 0, HAEN 0, ODR 0, INTPOL 0.
const uint8_t IOCON_VALUE = 0x00;

// ─── the port table ───────────────────────────────────────────────────────────────────────────
enum PinRole : uint8_t {
    PIN_RAIL,         // a rail input. activeHigh says which level means the rail is present
    PIN_BUTTON,       // 10 k to 3V3, low means pressed
    PIN_SPARE_PULLUP, // spare header input that floats, so the chip's pull-up is on
    PIN_OUTPUT_ONLY   // GPA7 and GPB7: output only on the MCP23017, driven low, never read
};

enum Rail : uint8_t {
    RAIL_AUX = 0, RAIL_FEED1, RAIL_FEED2, RAIL_FEED3, RAIL_SENS, RAIL_STRIP, RAIL_ENABLE,
    RAIL_COUNT
};

enum PinCircuit : uint8_t {
    CIRCUIT_NONE,
    CIRCUIT_NPN,       // rail, base resistors, NPN transistor, 10 k pull-up to the supply. low means present
    CIRCUIT_DIVIDER,   // a plain resistor divider from the rail. high means present
    CIRCUIT_SWITCH     // a push button to ground with a 10 k pull-up
};

struct PinInfo {
    const char* pin;       // GPA0 to GPB7
    const char* net;       // the net name in the board's table
    PinRole     role;
    int8_t      rail;      // a Rail for PIN_RAIL, -1 otherwise
    PinCircuit  circuit;
    bool        activeHigh;       // the level that means present (rail) or pressed (button)
    uint32_t    presentFromMv;    // rail voltage from which the input reads as present. 0 for no rail
    uint32_t    absentUnderMv;    // rail voltage under which the input reads as absent. 0 for no rail
};

// index 0 to 7 is GPA0 to GPA7 and index 8 to 15 is GPB0 to GPB7.
// the thresholds are ESTIMATES (base-emitter 0.6 to 0.7 V and a forced gain of 100 for the
// transistors) until they are measured at bring-up: each input's low level against 0.66 V and each
// rail's switching points with a bench supply. between the two figures the reading is undefined.
// the pins test reads the levels, the circuits and these figures from the fixture, so a change in
// the board's table fails the test until this table is updated.
inline const PinInfo* pinTable() {
    static const PinInfo t[16] = {
        {"GPA0", "AUX_OK",    PIN_RAIL,         RAIL_AUX,    CIRCUIT_NPN,     false, 4200, 2600},
        {"GPA1", "FEED3_OK",  PIN_RAIL,         RAIL_FEED3,  CIRCUIT_NPN,     false, 8100, 5000},
        {"GPA2", "FEED2_OK",  PIN_RAIL,         RAIL_FEED2,  CIRCUIT_NPN,     false, 8100, 5000},
        {"GPA3", "FEED1_OK",  PIN_RAIL,         RAIL_FEED1,  CIRCUIT_NPN,     false, 8100, 5000},
        {"GPA4", "SPARE_A4",  PIN_SPARE_PULLUP, -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPA5", "SPARE_A5",  PIN_SPARE_PULLUP, -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPA6", "SPARE_A6",  PIN_SPARE_PULLUP, -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPA7", "SPARE_A7",  PIN_OUTPUT_ONLY,  -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPB0", "BUTTON",    PIN_BUTTON,       -1,          CIRCUIT_SWITCH,  false,    0,    0},
        {"GPB1", "SENS_OK",   PIN_RAIL,         RAIL_SENS,   CIRCUIT_DIVIDER, true,  2720,  650},
        {"GPB2", "STRIP_OK",  PIN_RAIL,         RAIL_STRIP,  CIRCUIT_NPN,     false, 4200, 2600},
        {"GPB3", "ENABLE_OK", PIN_RAIL,         RAIL_ENABLE, CIRCUIT_NPN,     false, 4200, 2600},
        {"GPB4", "SPARE_B4",  PIN_SPARE_PULLUP, -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPB5", "SPARE_B5",  PIN_SPARE_PULLUP, -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPB6", "SPARE_B6",  PIN_SPARE_PULLUP, -1,          CIRCUIT_NONE,    true,     0,    0},
        {"GPB7", "SPARE_B7",  PIN_OUTPUT_ONLY,  -1,          CIRCUIT_NONE,    true,     0,    0},
    };
    return t;
}

const uint8_t BUTTON_PIN_INDEX = 8;   // GPB0

inline int8_t railPinIndex(Rail r) {
    const PinInfo* t = pinTable();
    for (uint8_t i = 0; i < 16; i++) if (t[i].role == PIN_RAIL && t[i].rail == (int8_t)r) return (int8_t)i;
    return -1;
}

inline const char* railNet(Rail r)   { return pinTable()[railPinIndex(r)].net; }
// the level the input reads when the rail is up
inline bool railPresentIsHigh(Rail r) { return pinTable()[railPinIndex(r)].activeHigh; }
inline uint32_t railPresentFromMv(Rail r) { return pinTable()[railPinIndex(r)].presentFromMv; }
inline uint32_t railAbsentUnderMv(Rail r) { return pinTable()[railPinIndex(r)].absentUnderMv; }
inline const char* railWords(Rail r) {
    switch (r) {
        case RAIL_AUX:    return "5 V AUX rail";
        case RAIL_FEED1:  return "12 V feed 1";
        case RAIL_FEED2:  return "12 V feed 2";
        case RAIL_FEED3:  return "12 V feed 3";
        case RAIL_SENS:   return "sensor rail";
        case RAIL_STRIP:  return "strip rail";
        case RAIL_ENABLE: return "relay 5 V rail";
        default:          return "unknown rail";
    }
}
inline SensorKey railKey(Rail r) {
    return (SensorKey)((uint8_t)SK_RAIL_AUX + (uint8_t)r);
}

// bit masks for one port (port 0 is A, port 1 is B), from the table
inline uint8_t portMask(uint8_t port, PinRole role) {
    uint8_t m = 0;
    for (uint8_t b = 0; b < 8; b++) if (pinTable()[port * 8 + b].role == role) m |= (uint8_t)(1u << b);
    return m;
}
// direction: 1 is an input. every pin is an input except GPA7 and GPB7, which the data sheet makes
// output only on the MCP23017 (section 3.5.1: IO7 must be set to 0).
inline uint8_t dirValue(uint8_t port) { return (uint8_t)~portMask(port, PIN_OUTPUT_ONLY); }
// the chip's own weak pull-up (40 to 115 uA at 5 V, no resistance stated) is on only for the
// spare inputs that float.
inline uint8_t pullupValue(uint8_t port) { return portMask(port, PIN_SPARE_PULLUP); }

// ─── the input levels ─────────────────────────────────────────────────────────────────────────
// MCP23017 data sheet DS20001952D table 1-1 (page 4): VIL is 0.2 x VDD and VIH is 0.8 x VDD, with
// leakage of 1 uA either way. the supply is an AMS1117-3.3, 3.235 to 3.365 V. a transistor input
// has to read below 0.66 V to be low, which the bring-up measures. the rail thresholds are the
// estimates in the pin table above.

// ─── what the registers must hold ─────────────────────────────────────────────────────────────
struct RegSpec {
    uint8_t value;
    uint8_t mask;   // the bits that are compared. 0 for a register that is live
};

inline RegSpec expectedReg(uint8_t reg) {
    switch (reg) {
        case REG_IODIRA:  return {dirValue(0), 0xFF};
        case REG_IODIRB:  return {dirValue(1), 0xFF};
        case REG_GPPUA:   return {pullupValue(0), 0xFF};
        case REG_GPPUB:   return {pullupValue(1), 0xFF};
        case REG_GPIOA: case REG_GPIOB:       // live pins
        case REG_INTCAPA: case REG_INTCAPB:   // live capture
        case REG_INTFA: case REG_INTFB:       // live flags: older firmware may have left one set and
                                              // only a read of the pins or the capture clears it
            return {0, 0x00};
        default:          return {0, 0xFF};   // polarity as wired, no interrupts, no latch bits
    }
}

// the first register in an image of REG_COUNT bytes that differs from what the driver wrote or -1
inline int firstMismatch(const uint8_t* img) {
    for (uint8_t r = 0; r < REG_COUNT; r++) {
        RegSpec s = expectedReg(r);
        if ((img[r] & s.mask) != (s.value & s.mask)) return r;
    }
    return -1;
}

// ─── the bus, the clock and the words ─────────────────────────────────────────────────────────
enum BusResult : uint8_t {
    BUS_OK = 0,
    BUS_NACK,      // the chip did not acknowledge: nothing is answering at the address
    BUS_TIMEOUT,   // the bus did not complete: a line is held
    BUS_FAIL       // a read came back short. in the pinned core requestFrom returns 0 for a refused
                   // address and for a time-out alike, so the driver sends one address-only probe to
                   // tell the two apart
};

// Wire.endTransmission returns 0 for success, 2 or 3 for a missing acknowledge and anything else
// (1 too long, 4 other, 5 time-out) for a bus that did not complete. the binding uses this and the
// host test checks it.
inline BusResult busFromWire(uint8_t code) {
    if (code == 0) return BUS_OK;
    if (code == 2 || code == 3) return BUS_NACK;
    return BUS_TIMEOUT;
}

class ExpanderBus {
public:
    virtual ~ExpanderBus() {}
    virtual BusResult writeReg(uint8_t reg, uint8_t value) = 0;
    // reads n bytes from reg onward in one transaction. a failure is BUS_FAIL unless the cause is known
    virtual BusResult readRegs(uint8_t reg, uint8_t* out, uint8_t n) = 0;
    // an address-only transfer: BUS_NACK when nothing answers and BUS_TIMEOUT when the bus is held
    virtual BusResult probe() = 0;
};

class ExpanderSink {
public:
    virtual ~ExpanderSink() {}
    virtual void say(const char* text) = 0;
};

class ExpanderClock {
public:
    virtual ~ExpanderClock() {}
    virtual uint32_t nowMs() = 0;
    virtual void delayMs(uint32_t ms) = 0;
};

// ─── a debounce that counts only the time it can vouch for ───────────────────────────────────
// the level has to differ from the current state for need ms in a row. a sample that matches the
// state ends the attempt, so a reading that flaps never changes the state. dt is the time since the
// last sample, already capped by the caller.
struct Debounce {
    bool     known;
    bool     state;
    bool     pending;
    bool     cand;
    uint32_t candMs;
    uint32_t candSince;     // when the candidate was first seen
    uint32_t changeSince;   // when the current state began, at its first sample

    void reset() { known = false; state = false; pending = false; cand = false; candMs = 0; candSince = 0; changeSince = 0; }
    // returns true when the state became known or changed
    bool feed(bool raw, uint32_t now, uint32_t dt, uint32_t needTrue, uint32_t needFalse) {
        if (known && raw == state) { pending = false; return false; }
        if (!pending || raw != cand) {
            pending = true; cand = raw; candMs = 0; candSince = now;
            return false;
        }
        candMs += dt;
        if (candMs >= (raw ? needTrue : needFalse)) {
            state = raw; known = true; pending = false; changeSince = candSince;
            return true;
        }
        return false;
    }
};

// ─── one rail input ───────────────────────────────────────────────────────────────────────────
struct RailTrack {
    Debounce  deb;          // state true is present
    bool      haveLast;
    bool      lastRaw;
    uint32_t  edges[RAIL_FLAP_EDGES];
    uint8_t   edgeCount;
    uint8_t   edgeIdx;
    bool      flapping;
    uint32_t  flapSince;
    HealthState logged;     // the state the last message described

    void reset() {
        deb.reset(); haveLast = false; lastRaw = false; edgeCount = 0; edgeIdx = 0;
        flapping = false; flapSince = 0;
    }
};

// the credentials may be cleared by a long press of the expander button only in the first
// PROVISION_CLEAR_WINDOW_MS after a power-up. a warm reset (a brown-out or a watchdog) never opens
// the window, because a node reset next to a pressed button must not clear its credentials. once the
// window has closed it stays closed, so the 49.7 day millis() alias cannot reopen it.
inline bool buttonClearAllowed(bool coldPowerUp, uint32_t nowMs, bool* windowClosed) {
    if (!*windowClosed && (!coldPowerUp || nowMs > PROVISION_CLEAR_WINDOW_MS)) *windowClosed = true;
    return !*windowClosed;
}

// the driver starts only when the image has the expander and the board check says it answered. on
// the present board image the answer is always no and on a revised image that cannot tell the board
// it waits, so the present board never has a transfer sent to 0x20.
inline bool expanderMayStart(bool imageHasExpander, BoardVerdict v) {
    return imageHasExpander && v == BOARD_OK;
}

// ─── the push button ──────────────────────────────────────────────────────────────────────────
struct ButtonTrack {
    Debounce deb;           // state true is pressed
    bool     armed;         // a release has been seen, so a press is believed
    bool     down;
    uint32_t heldMs;
    bool     longFired;
    bool     pressEv;
    bool     longEv;
    bool     warnedStuck;
    void resetSampling() { deb.reset(); armed = false; down = false; heldMs = 0; longFired = false; }
};

enum ExState : uint8_t {
    EXS_OFF = 0,     // not started
    EXS_RUNNING,
    EXS_DOWN,        // not answering
    EXS_UNTRUSTED    // answers, but a register read back differs from what was written
};
enum ExCause : uint8_t { CAUSE_NONE = 0, CAUSE_NO_ANSWER, CAUSE_BUS_STUCK, CAUSE_UNTRUSTED };

struct ExCounters {
    uint32_t startFailures;   // a start attempt that failed
    uint32_t lost;            // the chip stopped answering while running
    uint32_t recovered;       // the chip answered again after a loss
    uint32_t reconfigured;    // a read-back showed the configuration was gone and it was written again
    uint32_t untrusted;       // a read-back differed
    uint32_t busStuck;        // times the bus was called stuck
    uint32_t readFailures;    // failed reads, including those that led to a loss
    uint32_t samples;         // good pin reads that were used. a failed read is never one
    uint32_t presses;
    uint32_t longPresses;
    uint32_t sensRailNotBack;
};

// what a call to service() can cost the loop, from the pinned core's Wire time-out (about 50 ms,
// not measured). the host test simulates it.
//   a call that reconfigures makes at most 19 transfers: one pin read, one read-back, then the 17 of
//   the start. that is about 9 ms at 100 kHz by calculation. any other call makes at most 2 and 3
//   when a failed read is followed by the address-only probe. a call ends at the first transfer that
//   fails, so it can hold the loop for two time-outs at worst.
const uint32_t EXPANDER_MAX_TRANSFERS_PER_CALL = 19;
const uint32_t EXPANDER_BUS_TIMEOUT_MS = 50;
// in any ten seconds the driver costs the loop at most this long. the bound is checked by
// test_expander.cpp, which tries every failure pattern it can think of.
const uint32_t EXPANDER_WORST_COST_PER_10S_MS = 500;

class Expander {
public:
    Expander(ExpanderBus& bus, ExpanderSink& sink) : bus_(bus), sink_(sink) { clear(); }

    void clear() {
        state_ = EXS_OFF; cause_ = CAUSE_NONE; reportedCause_ = CAUSE_NONE;
        havePoll_ = false; lastPoll_ = 0; lastCfg_ = 0;
        lastSample_ = 0; haveSample_ = false; nextRetry_ = 0; retryDelay_ = EXPANDER_RETRY_START_MS;
        lastLone_ = 0; haveLone_ = false; downSince_ = 0; startMs_ = 0; runningSince_ = 0;
        haveGood_ = false; lastGoodMs_ = 0; fresh_ = false;
        failCount_ = 0; failIdx_ = 0; backoff_ = false; backoffUntil_ = 0;
        haveAnswer_ = false; answerMs_ = 0; sensFresh_ = false; sensUnprovenSince_ = 0;
        sensUnproven_ = false; sensNoted_ = false;
        retArmed_ = false; retAt_ = 0; retLimit_ = 0; retUp_ = 0; retPolls_ = 0;
        ctr_ = ExCounters();
        for (uint8_t r = 0; r < RAIL_COUNT; r++) { rails_[r].reset(); rails_[r].logged = HS_OK; }
        btn_.resetSampling(); btn_.pressEv = btn_.longEv = false; btn_.warnedStuck = false;
    }

    // one start attempt. it is always safe to call and returns at the first failed transaction.
    void start(uint32_t now) {
        startMs_ = now;
        Init r = runInit();
        if (r.kind == INIT_OK) {
            enterRunning(now, true);
            return;
        }
        ctr_.startFailures++;
        goDown(causeOf(r), r, now, true);
    }

    // call it on every pass of the main loop. it does bus work only when a poll or a check is due.
    void service(uint32_t now) {
        if (state_ == EXS_OFF) return;
        if (state_ == EXS_RUNNING) {
            fresh_ = haveGood_ && (uint32_t)(now - lastGoodMs_) <= EXPANDER_FRESH_MS;
            sensFresh_ = haveAnswer_ && (uint32_t)(now - answerMs_) <= EXPANDER_SENSOR_FRESH_MS;
            runningStep(now);
        } else {
            fresh_ = false;
            if ((int32_t)(now - nextRetry_) >= 0) retry(now);
        }
        watchSensRail(now);
        returnCheck(now);
    }

    // a cable sensor answered on this pass. the sensor rail is called present only while one has
    // answered lately, because the I2C pull-ups can hold SENS_OK high with the rail off.
    void noteSensorAnswered(uint32_t now) {
        haveAnswer_ = true; answerMs_ = now; sensFresh_ = true;
    }

    // call it once the sensor rail has been switched back on and the bus is up again. it does not
    // hold the loop: the polls that follow read SENS_OK and the limit is judged in service(). it
    // proves the rail came back and never that it went off. the sensors that answered before the
    // switch say nothing about the rail now, so that proof is cleared.
    void armSensRailReturn(uint32_t now, uint32_t limitMs) {
        retArmed_ = true; retAt_ = now; retLimit_ = limitMs; retUp_ = 0; retPolls_ = 0;
        haveAnswer_ = false; sensFresh_ = false;
    }

    // ─── what the rest of the firmware reads ──────────────────────────────────────────────────
    ExState state() const { return state_; }
    ExCause cause() const { return cause_; }
    const ExCounters& counters() const { return ctr_; }
    bool running() const { return state_ == EXS_RUNNING; }
    bool sensRailReturnPending() const { return retArmed_; }

    // not started is not known: silence never means well
    HealthState expanderHealth() const {
        if (state_ == EXS_DOWN) return HS_MISSING;
        if (state_ == EXS_UNTRUSTED) return HS_OUT_OF_RANGE;
        if (state_ == EXS_OFF) return HS_STALE;
        return HS_OK;
    }
    uint32_t expanderSince() const { return state_ == EXS_OFF ? startMs_ : downSince_; }

    static bool railExpected(Rail r) { return (EXPANDER_RAIL_EXPECTED_MASK >> (uint8_t)r) & 1u; }

    // a rail is ok only from a fresh reading. while the chip is not running and trusted, before the
    // first reading has settled or when the last good reading is older than EXPANDER_FRESH_MS, a
    // watched rail is stale: the node cannot say. a rail that is not watched is never reported.
    // SENS_OK reading present is not enough for the sensor rail: a sensor on it has to have
    // answered lately too, so it is stale (not proven up) until one has.
    HealthState railHealth(Rail r) const {
        if (!railExpected(r)) return HS_OK;
        if (state_ != EXS_RUNNING || !fresh_) return HS_STALE;
        const RailTrack& t = rails_[r];
        if (t.deb.known && !t.deb.state) return HS_MISSING;
        if (t.flapping) return HS_INTERMITTENT;
        if (!t.deb.known) return HS_STALE;
        if (r == RAIL_SENS && !sensFresh_) return HS_STALE;
        return HS_OK;
    }
    // when the state began. for a stale rail that is the last good reading (or the start)
    uint32_t railSince(Rail r) const {
        HealthState h = railHealth(r);
        if (h == HS_STALE) {
            if (r == RAIL_SENS && state_ == EXS_RUNNING && fresh_ && rails_[r].deb.known && rails_[r].deb.state)
                return rails_[r].deb.changeSince;
            return haveGood_ ? lastGoodMs_ : startMs_;
        }
        const RailTrack& t = rails_[r];
        if (t.deb.known && !t.deb.state) return t.deb.changeSince;
        if (t.flapping) return t.flapSince;
        return t.deb.changeSince;
    }
    // how long the rails have not been known, 0 while the last good reading is fresh
    uint32_t railsUnknownForMs(uint32_t now) const {
        if (state_ == EXS_RUNNING && fresh_) return 0;
        return (uint32_t)(now - (haveGood_ ? lastGoodMs_ : startMs_));
    }
    bool railKnownPresent(Rail r) const { return rails_[r].deb.known && rails_[r].deb.state; }

    bool buttonDown() const { return btn_.down; }
    uint32_t buttonHeldMs() const { return btn_.heldMs; }
    bool takePress() { bool e = btn_.pressEv; btn_.pressEv = false; return e; }
    bool takeLongPress() { bool e = btn_.longEv; btn_.longEv = false; return e; }

private:
    enum InitKind : uint8_t { INIT_OK, INIT_NO_ANSWER, INIT_BUS_STUCK, INIT_UNTRUSTED };
    struct Init { InitKind kind; int8_t reg; uint8_t got; uint8_t want; };

    static ExCause causeOf(const Init& r) {
        switch (r.kind) {
            case INIT_NO_ANSWER: return CAUSE_NO_ANSWER;
            case INIT_BUS_STUCK: return CAUSE_BUS_STUCK;
            case INIT_UNTRUSTED: return CAUSE_UNTRUSTED;
            default:             return CAUSE_NONE;
        }
    }

    // a read that came back short does not say why. one address-only probe does: no acknowledge is a
    // chip that does not answer and a time-out is a bus that is held. an address that is
    // acknowledged while the data transfer fails is a bus that does not complete.
    BusResult classify(BusResult br) {
        if (br != BUS_FAIL) return br;
        BusResult p = bus_.probe();
        return p == BUS_NACK ? BUS_NACK : BUS_TIMEOUT;
    }

    Init fail(BusResult br) {
        br = classify(br);
        Init r; r.kind = (br == BUS_TIMEOUT) ? INIT_BUS_STUCK : INIT_NO_ANSWER; r.reg = -1; r.got = r.want = 0;
        return r;
    }

    // write one register and read all 22 back. the order is fixed and every write is a byte write,
    // because the data sheet advises byte writes while the BANK bit changes.
    //  1. IOCON = 0 at the BANK = 1 address. a chip in BANK = 1 now moves to BANK = 0. a chip already
    //     in BANK = 0 takes it as GPINTENB = 0, which is its reset value.
    //  2. IOCON = 0 at the BANK = 0 address. the chip is in BANK = 0 whichever mode it started in.
    //  3. the output latches are written low first, so GPA7 and GPB7 never come up high.
    //  4. direction, with GPA7 and GPB7 as outputs and everything else an input.
    //  5. polarity as wired (not inverted), no interrupts, the pull-ups for the spare inputs only.
    Init runInit() {
        BusResult br;
        if ((br = bus_.writeReg(REG_IOCON_BANK1, IOCON_VALUE)) != BUS_OK) return fail(br);
        if ((br = bus_.writeReg(REG_IOCON, IOCON_VALUE)) != BUS_OK) return fail(br);
        static const uint8_t order[] = {
            REG_OLATA, REG_OLATB, REG_IODIRA, REG_IODIRB, REG_IPOLA, REG_IPOLB,
            REG_GPINTENA, REG_GPINTENB, REG_DEFVALA, REG_DEFVALB, REG_INTCONA, REG_INTCONB,
            REG_GPPUA, REG_GPPUB
        };
        for (uint8_t i = 0; i < sizeof order; i++) {
            if ((br = bus_.writeReg(order[i], expectedReg(order[i]).value)) != BUS_OK) return fail(br);
        }
        uint8_t img[REG_COUNT];
        if ((br = bus_.readRegs(0x00, img, REG_COUNT)) != BUS_OK) return fail(br);
        int m = firstMismatch(img);
        Init r; r.kind = INIT_OK; r.reg = -1; r.got = r.want = 0;
        if (m >= 0) {
            r.kind = INIT_UNTRUSTED; r.reg = (int8_t)m; r.got = img[m]; r.want = expectedReg((uint8_t)m).value;
        }
        return r;
    }

    static void fmtTime(char* out, size_t n, uint32_t ms) {
        snprintf(out, n, "%lu.%lu s", (unsigned long)(ms / 1000u), (unsigned long)((ms % 1000u) / 100u));
    }

    void enterRunning(uint32_t now, bool atStart) {
        bool wasDown = (cause_ != CAUSE_NONE);
        state_ = EXS_RUNNING; cause_ = CAUSE_NONE;
        failCount_ = 0; backoff_ = false;
        havePoll_ = false; lastCfg_ = now; haveSample_ = false; runningSince_ = now;
        // what was read before the loss is no longer evidence: every rail is read again from scratch,
        // so a rail that changed while the chip was away is found and none is carried over. the
        // button must be seen released again before a press is believed.
        for (uint8_t r = 0; r < RAIL_COUNT; r++) { HealthState keep = rails_[r].logged; rails_[r].reset(); rails_[r].logged = keep; }
        btn_.resetSampling();
        char buf[190], t[20];
        fmtTime(t, sizeof t, now);
        if (wasDown) {
            ctr_.recovered++;
            snprintf(buf, sizeof buf, "[expander] answering again at %s, configured and every register read back (recovered %lu). the rails are read again and are reported not known until they have been",
                     t, (unsigned long)ctr_.recovered);
            sink_.say(buf);
        } else if (atStart) {
            snprintf(buf, sizeof buf, "[expander] started at %s: every register read back as written. the rails are reported not known until they have been read",
                     t);
            sink_.say(buf);
        }
        reportedCause_ = CAUSE_NONE;
    }

    void goDown(ExCause cause, const Init& r, uint32_t now, bool atStart) {
        bool fromRunning = (state_ == EXS_RUNNING);
        state_ = (cause == CAUSE_UNTRUSTED) ? EXS_UNTRUSTED : EXS_DOWN;
        if (fromRunning) {
            ctr_.lost++;
            // a chip that has run steadily gets the short retry again. one that keeps dropping out
            // carries on from where the back-off had got to, so a half-failing bus cannot be retried hard
            if ((uint32_t)(now - runningSince_) >= EXPANDER_STABLE_MS) retryDelay_ = EXPANDER_RETRY_START_MS;
        }
        if (cause == CAUSE_UNTRUSTED && reportedCause_ != CAUSE_UNTRUSTED) ctr_.untrusted++;
        if (cause == CAUSE_BUS_STUCK && reportedCause_ != CAUSE_BUS_STUCK) ctr_.busStuck++;
        if (cause_ == CAUSE_NONE || cause != cause_) downSince_ = now;
        cause_ = cause;
        fresh_ = false;
        btn_.resetSampling();
        nextRetry_ = now + retryDelay_;
        if (reportedCause_ != cause) {
            reportedCause_ = cause;
            char buf[240], t[20], age[20];
            fmtTime(t, sizeof t, now);
            fmtTime(age, sizeof age, haveGood_ ? lastGoodMs_ : startMs_);
            switch (cause) {
                case CAUSE_NO_ANSWER:
                    snprintf(buf, sizeof buf, "[expander] %s at %s: the port expander does not answer. every watched rail is now reported stale (not known, last good reading at %s) and the button cannot be read. sensors and posting carry on. trying again after %lu s or longer",
                             atStart ? "did not answer at start" : "stopped answering", t, age, (unsigned long)(retryDelay_ / 1000u));
                    break;
                case CAUSE_BUS_STUCK:
                    snprintf(buf, sizeof buf, "[expander] I2C bus stuck at %s: transfers time out. every device on the bus is affected. every watched rail is now reported stale (not known, last good reading at %s). trying again after %lu s or longer",
                             t, age, (unsigned long)(retryDelay_ / 1000u));
                    break;
                default:
                    snprintf(buf, sizeof buf, "[expander] not trusted at %s: register %02X read back %02X where %02X was written. its readings are ignored and every watched rail is reported stale (not known)",
                             t, (unsigned)(uint8_t)r.reg, (unsigned)r.got, (unsigned)r.want);
                    break;
            }
            sink_.say(buf);
        }
    }

    void retry(uint32_t now) {
        Init r = runInit();
        if (r.kind == INIT_OK) { enterRunning(now, false); return; }
        retryDelay_ = retryDelay_ * 2u;
        if (retryDelay_ > EXPANDER_RETRY_MAX_MS) retryDelay_ = EXPANDER_RETRY_MAX_MS;
        goDown(causeOf(r), r, now, false);
    }

    // a failed read counts for nothing: it is never a sample and the run of samples is broken so
    // the time around it is credited to no debounce. the next poll waits EXPANDER_FAIL_BACKOFF_MS, so
    // a bus that fails every other read cannot hold the loop. EXPANDER_FAIL_LIMIT failures inside
    // EXPANDER_FAIL_WINDOW_MS, in a row or not, call the chip down.
    void noteReadFail(BusResult br, uint32_t now) {
        br = classify(br);
        ctr_.readFailures++;
        haveSample_ = false;
        backoff_ = true; backoffUntil_ = now + EXPANDER_FAIL_BACKOFF_MS;
        // forget failures older than the window, then keep this one
        uint8_t n = 0;
        uint32_t keepT[EXPANDER_FAIL_LIMIT]; bool keepTo[EXPANDER_FAIL_LIMIT];
        for (uint8_t i = 0; i < failCount_; i++) {
            if ((uint32_t)(now - failT_[i]) <= EXPANDER_FAIL_WINDOW_MS) { keepT[n] = failT_[i]; keepTo[n] = failTimeout_[i]; n++; }
        }
        if (n == EXPANDER_FAIL_LIMIT) {            // full: drop the oldest
            for (uint8_t i = 1; i < n; i++) { keepT[i - 1] = keepT[i]; keepTo[i - 1] = keepTo[i]; }
            n--;
        }
        keepT[n] = now; keepTo[n] = (br == BUS_TIMEOUT); n++;
        for (uint8_t i = 0; i < n; i++) { failT_[i] = keepT[i]; failTimeout_[i] = keepTo[i]; }
        failCount_ = n;
        if (n == 1 && (!haveLone_ || (uint32_t)(now - lastLone_) >= EXPANDER_LONE_LOG_MS)) {
            haveLone_ = true; lastLone_ = now;
            char buf[150];
            snprintf(buf, sizeof buf, "[expander] a read failed (%lu so far). the last good readings are kept while they are fresh",
                     (unsigned long)ctr_.readFailures);
            sink_.say(buf);
        }
        if (n >= EXPANDER_FAIL_LIMIT) {
            uint8_t to = 0;
            for (uint8_t i = 0; i < n; i++) if (failTimeout_[i]) to++;
            Init r; r.kind = INIT_NO_ANSWER; r.reg = -1; r.got = r.want = 0;
            goDown((uint8_t)(2u * to) > n ? CAUSE_BUS_STUCK : CAUSE_NO_ANSWER, r, now, false);
        }
    }

    void runningStep(uint32_t now) {
        if (backoff_) {
            if ((int32_t)(now - backoffUntil_) < 0) return;
            backoff_ = false;
        }
        if (!havePoll_ || (uint32_t)(now - lastPoll_) >= EXPANDER_POLL_MS) {
            havePoll_ = true; lastPoll_ = now;
            uint8_t v[2];
            BusResult br = bus_.readRegs(REG_GPIOA, v, 2);
            if (br != BUS_OK) { noteReadFail(br, now); return; }
            haveGood_ = true; lastGoodMs_ = now; fresh_ = true;
            ctr_.samples++;
            processSample(now, v[0], v[1]);
        }
        if ((uint32_t)(now - lastCfg_) >= EXPANDER_CONFIG_CHECK_MS) {
            lastCfg_ = now;
            uint8_t img[REG_COUNT];
            BusResult br = bus_.readRegs(0x00, img, REG_COUNT);
            if (br != BUS_OK) { noteReadFail(br, now); return; }
            int m = firstMismatch(img);
            if (m < 0) return;
            // the chip no longer holds what was written. a brown-out resets it to all inputs, pull-ups
            // off. while it is unconfigured the pins still read their true levels, so the rails and the
            // button go on being read and nothing about them is reported or changed here.
            ctr_.reconfigured++;
            char buf[190], t[20];
            fmtTime(t, sizeof t, now);
            snprintf(buf, sizeof buf, "[expander] lost its configuration at %s: register %02X reads %02X where %02X was written. configuring it again (%lu so far)",
                     t, (unsigned)m, (unsigned)img[m], (unsigned)expectedReg((uint8_t)m).value, (unsigned long)ctr_.reconfigured);
            sink_.say(buf);
            Init r = runInit();
            if (r.kind == INIT_OK) { lastCfg_ = now; return; }
            goDown(causeOf(r), r, now, false);
        }
    }

    void processSample(uint32_t now, uint8_t a, uint8_t b) {
        uint32_t dt = 0;
        if (haveSample_) {
            dt = (uint32_t)(now - lastSample_);
            if (dt > EXPANDER_MAX_CREDIT_MS) dt = EXPANDER_MAX_CREDIT_MS;
        }
        haveSample_ = true; lastSample_ = now;
        for (uint8_t i = 0; i < RAIL_COUNT; i++) {
            Rail r = (Rail)i;
            if (!railExpected(r)) continue;
            int8_t idx = railPinIndex(r);
            uint8_t port = (uint8_t)(idx >> 3);
            bool level = ((port ? b : a) >> (idx & 7)) & 1u;
            // the polarity is in the table: a transistor input reads low when the rail is up and
            // SENS_OK reads high
            bool up = (level == railPresentIsHigh(r));
            if (r == RAIL_SENS && retArmed_) {
                if (retPolls_ < 255) retPolls_++;
                if (up) { if (retUp_ < 255) retUp_++; } else retUp_ = 0;
            }
            feedRail(r, up, now, dt);
        }
        // the button is low when pressed. only bit 0 of port B is looked at here.
        feedButton(((b & 1u) == 0), now, dt);
    }

    // present is true when the rail is up, whatever level that is on the pin
    void feedRail(Rail r, bool raw, uint32_t now, uint32_t dt) {
        RailTrack& t = rails_[r];
        // forget edges that are too old, so a stale entry is never compared again
        while (t.edgeCount > 0 &&
               (uint32_t)(now - t.edges[(t.edgeIdx + RAIL_FLAP_EDGES - t.edgeCount) % RAIL_FLAP_EDGES]) > RAIL_FLAP_WINDOW_MS) {
            t.edgeCount--;
        }
        if (t.haveLast && raw != t.lastRaw) {
            t.edges[t.edgeIdx] = now;
            t.edgeIdx = (uint8_t)((t.edgeIdx + 1) % RAIL_FLAP_EDGES);
            if (t.edgeCount < RAIL_FLAP_EDGES) t.edgeCount++;
        }
        t.haveLast = true; t.lastRaw = raw;
        bool flap = t.edgeCount >= RAIL_FLAP_EDGES &&
                    (uint32_t)(now - t.edges[t.edgeIdx]) <= RAIL_FLAP_WINDOW_MS;
        if (flap && !t.flapping) t.flapSince = now;
        t.flapping = flap;
        t.deb.feed(raw, now, dt, RAIL_DEBOUNCE_MS, RAIL_DEBOUNCE_MS);
        announceRail(r, now);
    }

    // says a rail's state when it changes between ok, absent and unstable. a stale rail is not
    // announced one by one: the chip's own message says that every watched rail is stale.
    void announceRail(Rail r, uint32_t now) {
        RailTrack& t = rails_[r];
        HealthState h = railHealth(r);
        if (h == HS_STALE || h == t.logged) return;
        t.logged = h;
        char buf[220], since[20], nowT[20];
        fmtTime(nowT, sizeof nowT, now);
        fmtTime(since, sizeof since, railSince(r));
        if (h == HS_MISSING) {
            snprintf(buf, sizeof buf, "[rail] %s is absent: %s reads %s, since %s after boot",
                     railWords(r), railNet(r), railPresentIsHigh(r) ? "low" : "high", since);
        } else if (h == HS_INTERMITTENT) {
            snprintf(buf, sizeof buf, "[rail] %s is unstable: %s keeps changing, so the rail may sit near its threshold, since %s after boot",
                     railWords(r), railNet(r), since);
        } else {
            snprintf(buf, sizeof buf, "[rail] %s is present (up, not checked for range): %s reads %s at %s after boot",
                     railWords(r), railNet(r), railPresentIsHigh(r) ? "high" : "low", nowT);
        }
        sink_.say(buf);
    }

    // SENS_OK reading present does not prove the sensor rail is on, because the I2C pull-ups can hold
    // it high with the rail off. say so once if no sensor has answered for EXPANDER_SENS_PROOF_MS.
    void watchSensRail(uint32_t now) {
        bool unproven = state_ == EXS_RUNNING && fresh_ && railExpected(RAIL_SENS) &&
                        rails_[RAIL_SENS].deb.known && rails_[RAIL_SENS].deb.state && !sensFresh_;
        if (!unproven) { sensUnproven_ = false; sensNoted_ = false; return; }
        if (!sensUnproven_) { sensUnproven_ = true; sensUnprovenSince_ = now; return; }
        if (!sensNoted_ && (uint32_t)(now - sensUnprovenSince_) >= EXPANDER_SENS_PROOF_MS) {
            sensNoted_ = true;
            sink_.say("[rail] the sensor rail is not proven up: SENS_OK reads high but no sensor on it has answered lately and the I2C pull-ups can hold SENS_OK high with the rail off");
        }
    }

    // the check after a power cycle: SENS_OK has to read present on two polls in a row within the
    // limit. it is judged on the polls the loop makes anyway, so nothing here waits. one late poll
    // that finds the rail up still passes (initCableSensors can hold the loop for seconds). when no
    // poll could be made the rail's return is not confirmed and nothing is claimed about it.
    void returnCheck(uint32_t now) {
        if (!retArmed_) return;
        bool ok2 = state_ == EXS_RUNNING && retUp_ >= 2;
        bool late1 = state_ == EXS_RUNNING && retUp_ >= 1 && retPolls_ < 2 && (uint32_t)(now - retAt_) >= retLimit_;
        if (ok2 || late1) {
            retArmed_ = false;
            char buf[170];
            snprintf(buf, sizeof buf, "[rail] SENS_OK reads high again %lu ms after the sensor rail was switched back on. the rail is called present only once a sensor on it answers",
                     (unsigned long)(uint32_t)(now - retAt_));
            sink_.say(buf);
            return;
        }
        if ((uint32_t)(now - retAt_) < retLimit_) return;
        retArmed_ = false;
        if (state_ != EXS_RUNNING || retPolls_ == 0) {
            sink_.say("[rail] SENS_OK could not be read after the sensor rail was switched back on, so its return is not confirmed");
            return;
        }
        ctr_.sensRailNotBack++;
        RailTrack& t = rails_[RAIL_SENS];
        t.deb.known = true; t.deb.state = false; t.deb.pending = false; t.deb.changeSince = retAt_;
        t.haveLast = false; t.edgeCount = 0; t.flapping = false;
        t.logged = HS_MISSING;
        char buf[170];
        snprintf(buf, sizeof buf, "[rail] the sensor rail did not come back: SENS_OK still reads %s %lu ms after the switch was released",
                 railPresentIsHigh(RAIL_SENS) ? "low" : "high", (unsigned long)retLimit_);
        sink_.say(buf);
    }

    void feedButton(bool pressed, uint32_t now, uint32_t dt) {
        ButtonTrack& b = btn_;
        bool changed = b.deb.feed(pressed, now, dt, BUTTON_PRESS_MS, BUTTON_RELEASE_MS);
        if (changed) {
            if (b.deb.state) {
                if (b.armed) {
                    b.down = true; b.heldMs = 0; b.longFired = false;
                    b.pressEv = true; ctr_.presses++;
                } else if (!b.warnedStuck) {
                    b.warnedStuck = true;
                    sink_.say("[button] reads pressed from the start. it is ignored until it has been seen released");
                }
            } else {
                b.down = false; b.armed = true; b.heldMs = 0;
            }
            return;
        }
        if (b.down) {
            b.heldMs += dt;
            if (!b.longFired && b.heldMs >= BUTTON_LONG_PRESS_MS) {
                b.longFired = true; b.longEv = true; ctr_.longPresses++;
            }
        }
    }

    ExpanderBus&  bus_;
    ExpanderSink& sink_;
    ExState  state_;
    ExCause  cause_;
    ExCause  reportedCause_;
    bool     havePoll_;
    uint32_t lastPoll_;
    uint32_t lastCfg_;
    uint32_t lastSample_;
    bool     haveSample_;
    uint32_t nextRetry_;
    uint32_t retryDelay_;
    uint32_t lastLone_;
    bool     haveLone_;
    uint32_t downSince_;
    uint32_t startMs_;
    uint32_t runningSince_;
    bool     haveGood_;
    uint32_t lastGoodMs_;
    bool     fresh_;
    uint8_t  failCount_;
    uint8_t  failIdx_;
    uint32_t failT_[EXPANDER_FAIL_LIMIT];
    bool     failTimeout_[EXPANDER_FAIL_LIMIT];
    bool     backoff_;
    uint32_t backoffUntil_;
    bool     haveAnswer_;
    uint32_t answerMs_;
    bool     sensFresh_;
    bool     sensUnproven_;
    uint32_t sensUnprovenSince_;
    bool     sensNoted_;
    bool     retArmed_;
    uint32_t retAt_;
    uint32_t retLimit_;
    uint8_t  retUp_;
    uint8_t  retPolls_;
    ExCounters ctr_;
    RailTrack  rails_[RAIL_COUNT];
    ButtonTrack btn_;
};

}  // namespace mcp
