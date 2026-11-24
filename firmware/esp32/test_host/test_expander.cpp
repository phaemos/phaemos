// test_expander.cpp - host test for the port expander driver (sensors/mcp23017_logic.h) against a
// scripted MCP23017. the scripted chip keeps the register file, both addressing modes, the address
// pointer and a reset and can be told to fail. nothing here proves anything about a real chip or a
// real board: no revised board has been made. it proves what the driver sends, what it decides and
// what it reports.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_expander.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_expander" && "${TMPDIR:-/tmp}/test_expander"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_expander.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_expander_san" && "${TMPDIR:-/tmp}/test_expander_san"
// the present board is the default build (HAS_EXPANDER 0). the same test also builds for the revised board:
//   c++ -std=c++17 -Wall -Wextra -DHAS_EXPANDER=1 -DHAS_SENSOR_RAIL_SWITCH=1 -I.. test_expander.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_expander_revb" && "${TMPDIR:-/tmp}/test_expander_revb"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "../sensors/mcp23017_logic.h"

using namespace mcp;

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

// ─── the scripted chip ────────────────────────────────────────────────────────────────────────
struct Txn { bool write; uint8_t reg; uint8_t value; uint8_t n; };

struct FakeChip : ExpanderBus {
    uint8_t  r[REG_COUNT];     // held under the BANK = 0 numbering
    bool     bank1 = false;
    bool     answering = true;
    BusResult deadKind = BUS_NACK;  // what a chip that is not answering looks like
    int      failNext = 0;          // fail this many transactions, then answer
    BusResult failNextKind = BUS_TIMEOUT;
    uint8_t  pinsA = 0xFF, pinsB = 0xFF;   // what the pins read when they are inputs
    uint8_t  ignoreMask[REG_COUNT];        // bits a write cannot change (a faulty chip)
    std::vector<Txn> log;
    int      transactions = 0;
    int      failedTransactions = 0;
    // the real binding returns BUS_FAIL for every failed read (requestFrom returns 0 for a refused
    // address and for a time-out alike). the chip fails that way too and only a write or the
    // address-only probe can say why
    bool     realisticReads = true;
    uint8_t  intf[2] = {0, 0};             // interrupt flags a chip may hold from older firmware

    FakeChip() { std::memset(ignoreMask, 0, sizeof ignoreMask); reset(); }
    void reset() {
        std::memset(r, 0, sizeof r);
        r[REG_IODIRA] = r[REG_IODIRB] = 0xFF;
        bank1 = false;
    }
    // the BANK = 1 map to the canonical index. -1 is an address that holds nothing.
    static int bank1Index(uint8_t a) {
        static const uint8_t order[11] = {0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20};
        if (a <= 0x0A) return order[a];
        if (a >= 0x10 && a <= 0x1A) return order[a - 0x10] + 1;
        return -1;
    }
    int idx(uint8_t a) const {
        if (!bank1) return a < REG_COUNT ? a : -1;
        return bank1Index(a);
    }
    uint8_t readOne(int i) const {
        if (i < 0) return 0xFF;
        uint8_t dir = (i & 1) ? r[REG_IODIRB] : r[REG_IODIRA];
        switch (i) {
            case REG_IOCON: case REG_IOCON_MIRROR: return r[REG_IOCON] & 0xFE;
            case REG_INTFA: return intf[0];
            case REG_INTFB: return intf[1];
            case REG_INTCAPA: case REG_INTCAPB: return 0;
            case REG_GPIOA: return (uint8_t)((pinsA & r[REG_IODIRA]) | (r[REG_OLATA] & ~dir));
            case REG_GPIOB: return (uint8_t)((pinsB & r[REG_IODIRB]) | (r[REG_OLATB] & ~dir));
            default: return r[i];
        }
    }
    void writeOne(int i, uint8_t v) {
        if (i < 0) return;
        if (i == REG_IOCON || i == REG_IOCON_MIRROR) {
            uint8_t keep = (uint8_t)(r[REG_IOCON] & ignoreMask[REG_IOCON]);
            r[REG_IOCON] = (uint8_t)((v & ~ignoreMask[REG_IOCON]) | keep);
            bank1 = (r[REG_IOCON] & 0x80) != 0;
            return;
        }
        if (i == REG_GPIOA) i = REG_OLATA;
        if (i == REG_GPIOB) i = REG_OLATB;
        if (i == REG_INTFA || i == REG_INTFB || i == REG_INTCAPA || i == REG_INTCAPB) return;
        r[i] = (uint8_t)((v & ~ignoreMask[i]) | (r[i] & ignoreMask[i]));
    }
    bool gate(BusResult* out, bool isRead = false) {
        transactions++;
        if (failNext > 0) { failNext--; failedTransactions++; *out = isRead && realisticReads ? BUS_FAIL : failNextKind; return false; }
        if (!answering) { failedTransactions++; *out = isRead && realisticReads ? BUS_FAIL : deadKind; return false; }
        return true;
    }
    BusResult probe() override {
        BusResult f;
        // an address-only transfer sees the true cause. a failNext failure is a read that failed, not a dead address
        transactions++;
        if (!answering) { failedTransactions++; return deadKind; }
        (void)f;
        return BUS_OK;
    }
    BusResult writeReg(uint8_t reg, uint8_t value) override {
        log.push_back({true, reg, value, 1});
        BusResult f;
        if (!gate(&f)) return f;
        writeOne(idx(reg), value);
        return BUS_OK;
    }
    BusResult readRegs(uint8_t reg, uint8_t* out, uint8_t n) override {
        log.push_back({false, reg, 0, n});
        BusResult f;
        if (!gate(&f, true)) return f;
        uint8_t a = reg;
        for (uint8_t k = 0; k < n; k++) {
            out[k] = readOne(idx(a));
            a++;
            if (!bank1 && a >= REG_COUNT) a = 0;
            if (bank1 && a > 0x1A) a = 0;
        }
        return BUS_OK;
    }
};

struct Sink : ExpanderSink {
    std::vector<std::string> lines;
    void say(const char* t) override { lines.push_back(t); }
    int count(const char* needle) const {
        int c = 0;
        for (const std::string& s : lines) if (s.find(needle) != std::string::npos) c++;
        return c;
    }
};

struct Clock : ExpanderClock {
    uint32_t t = 0;
    uint32_t nowMs() override { return t; }
    void delayMs(uint32_t ms) override { t += ms; }
};

// pin levels for the chip: rails high, button released
static void setPin(FakeChip& c, uint8_t index, bool high) {
    uint8_t& p = index < 8 ? c.pinsA : c.pinsB;
    uint8_t bit = (uint8_t)(1u << (index & 7));
    if (high) p |= bit; else p &= (uint8_t)~bit;
}
// present is true when the rail is up. the pin level it takes comes from the table: a transistor
// input reads low for a present rail and SENS_OK reads high.
static void setRail(FakeChip& c, Rail r, bool present) {
    setPin(c, (uint8_t)railPinIndex(r), present == railPresentIsHigh(r));
}
static void railsAllPresent(FakeChip& c) {
    c.pinsA = 0xFF; c.pinsB = 0xFF;
    for (uint8_t i = 0; i < RAIL_COUNT; i++) setRail(c, (Rail)i, true);
}
static void railsAllAbsent(FakeChip& c) {
    c.pinsA = 0xFF; c.pinsB = 0xFF;
    for (uint8_t i = 0; i < RAIL_COUNT; i++) setRail(c, (Rail)i, false);
}

// a cable sensor answers on every pass unless a test says otherwise. the sensor rail is called
// present only while one has
static bool g_sensors = true;

// runs the driver from t to t + span, one service call every step
static uint32_t run(Expander& e, uint32_t t, uint32_t span, uint32_t step = 5) {
    uint32_t end = t + span;
    for (; t < end; t += step) {
        if (g_sensors) e.noteSensorAnswered(t);
        e.service(t);
    }
    return t;
}

// ─── the pin table against the board's table ─────────────────────────────────────────────────
static std::string slurp(const char* path) {
    std::ifstream f(path);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}
static std::vector<std::string> cells(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    for (size_t i = 1; i < line.size(); i++) {   // skips the leading bar
        if (line[i] == '|') {
            size_t a = cur.find_first_not_of(' '), b = cur.find_last_not_of(' ');
            out.push_back(a == std::string::npos ? "" : cur.substr(a, b - a + 1));
            cur.clear();
        } else cur += line[i];
    }
    return out;
}
static bool starts(const std::string& s, const char* p) { return s.compare(0, std::strlen(p), p) == 0; }

static long mvFrom(const std::string& cell, const char* word) {
    // "V5_AUX from 4.2 V" or "under 2.6 V" to millivolts, 0 when the cell has no such figure
    size_t at = cell.find(word);
    if (at == std::string::npos) return 0;
    return std::lround(std::atof(cell.c_str() + at + std::strlen(word)) * 1000.0);
}

static void testPinTableMatchesFixture() {
    std::string text = slurp("fixtures/expander_pins.md");
    CHECK(!text.empty());
    // the rows first, so a row that says "as AUX" can be resolved
    std::vector<std::vector<std::string>> rowsCells;
    std::stringstream in(text);
    std::string line;
    while (std::getline(in, line)) if (starts(line, "| GP")) rowsCells.push_back(cells(line));
    CHECK(rowsCells.size() == 16);
    for (size_t rows = 0; rows < rowsCells.size() && rows < 16; rows++) {
        const std::vector<std::string>& c = rowsCells[rows];
        CHECK(c.size() == 9);
        if (c.size() != 9) continue;
        const PinInfo& p = pinTable()[rows];
        CHECK(c[0] == p.pin);                       // the row's position is its port pin
        CHECK(starts(c[2], p.net));
        const std::string& dir = c[3];
        const std::string& act = c[4];
        const std::string& circuit = c[5];
        if (dir == "in") CHECK(p.role == PIN_RAIL || p.role == PIN_BUTTON);
        if (dir == "spare") CHECK(p.role == PIN_SPARE_PULLUP);
        if (starts(dir, "output only")) CHECK(p.role == PIN_OUTPUT_ONLY);
        // the polarity of every input is read from the fixture. a rail's level is the one that means present
        if (p.role == PIN_RAIL) {
            CHECK(act == "low" || act == "HIGH");
            CHECK(p.activeHigh == (act == "HIGH"));
        }
        if (p.role == PIN_BUTTON) CHECK(act == "low" && !p.activeHigh);
        if (p.role == PIN_SPARE_PULLUP || p.role == PIN_OUTPUT_ONLY) CHECK(act == "none");
        // the circuit: a transistor, a plain divider, a switch or nothing
        bool hasQ = circuit.find(", Q") != std::string::npos;
        if (p.role == PIN_RAIL && hasQ) CHECK(p.circuit == CIRCUIT_NPN && !p.activeHigh);
        if (p.role == PIN_RAIL && !hasQ) CHECK(p.circuit == CIRCUIT_DIVIDER && p.activeHigh);
        if (p.role == PIN_BUTTON) CHECK(p.circuit == CIRCUIT_SWITCH && circuit.find("SW1") != std::string::npos);
        if (circuit == "none") CHECK(p.circuit == CIRCUIT_NONE);
        CHECK((p.role == PIN_RAIL) == (c[2].find("_OK") != std::string::npos));
        // the thresholds. "as AUX" and "as FEED3" point at another row
        if (p.role == PIN_RAIL) {
            std::vector<std::string> t = c;
            if (starts(c[6], "as ")) {
                std::string ref = c[6].substr(3) + "_OK";
                for (const std::vector<std::string>& o : rowsCells) if (starts(o[2], ref.c_str())) t = o;
            }
            long present = mvFrom(t[6], "from ") + mvFrom(t[7], "from ");
            long absent = mvFrom(t[6], "under ") + mvFrom(t[7], "under ");
            CHECK(present > 0 && absent > 0 && present > absent);
            CHECK((long)p.presentFromMv == present && (long)p.absentUnderMv == absent);
        } else {
            CHECK(p.presentFromMv == 0 && p.absentUnderMv == 0);
        }
    }
    // the interrupt pins, the headers and the wording of "present" are in the fixture the code follows
    CHECK(text.find("INTA (pin 20) is the net EXP_INT and reaches test pad TP33 only. INTB (pin 19) is not connected.") != std::string::npos);
    CHECK(text.find("J23 has 6 pins") != std::string::npos && text.find("J28 has 5 pins") != std::string::npos);
    CHECK(text.find("It does not mean the rail is in range") != std::string::npos);
    // the masks the driver writes follow from the table
    CHECK(pullupValue(0) == 0x70 && pullupValue(1) == 0x70);
    CHECK(dirValue(0) == 0x7F && dirValue(1) == 0x7F);
}

static std::string fmt2(uint32_t mv) {
    char b[24];
    std::snprintf(b, sizeof b, "%.2f", mv / 1000.0);
    return b;
}

static bool hasLine(const std::string& text, const char* a, const char* b) {
    std::stringstream in(text);
    std::string line;
    while (std::getline(in, line)) if (line.find(a) != std::string::npos && line.find(b) != std::string::npos) return true;
    return false;
}

static void testReadmeHasTheBands() {
    // the rail table in the README is the one in the code: polarity and both thresholds for every rail
    std::string text = slurp("../sensors/README.md");
    CHECK(!text.empty());
    for (uint8_t i = 0; i < RAIL_COUNT; i++) {
        Rail r = (Rail)i;
        std::stringstream in(text);
        std::string line;
        bool found = false;
        while (std::getline(in, line)) {
            if (!starts(line, "| ")) continue;
            std::vector<std::string> c = cells(line);
            if (c.size() != 7 || c[1] != railNet(r)) continue;
            found = true;
            CHECK(c[3] == (railPresentIsHigh(r) ? "high" : "low"));
            CHECK(c[4] == fmt2(railPresentFromMv(r)) + " V");
            CHECK(c[5] == fmt2(railAbsentUnderMv(r)) + " V");
            CHECK(c[6] == fmt2(railAbsentUnderMv(r)) + " V to " + fmt2(railPresentFromMv(r)) + " V");
        }
        CHECK(found);
    }
    CHECK(text.find("values under review") == std::string::npos);
    CHECK(text.find("estimates") != std::string::npos && text.find("measured at bring-up") != std::string::npos);
    CHECK(text.find("Present means the rail is up. It does not mean the rail is in range.") != std::string::npos);
    // the interrupt pins and the headers are documented as the board has them
    CHECK(hasLine(text, "INTA", "EXP_INT") && hasLine(text, "INTA", "TP33"));
    CHECK(hasLine(text, "INTB", "not connected") && !hasLine(text, "INTB", "TP33") && !hasLine(text, "INTA", "not connected"));
    CHECK(text.find("J23 has 6 pins") != std::string::npos && text.find("J28 has 5 pins") != std::string::npos);
}

static void testBands() {
    // the estimates from the board's table
    CHECK(railPresentFromMv(RAIL_AUX) == 4200 && railAbsentUnderMv(RAIL_AUX) == 2600);
    CHECK(railPresentFromMv(RAIL_FEED1) == 8100 && railAbsentUnderMv(RAIL_FEED1) == 5000);
    CHECK(railPresentFromMv(RAIL_SENS) == 2720 && railAbsentUnderMv(RAIL_SENS) == 650);
    CHECK(railPresentFromMv(RAIL_STRIP) == 4200 && railPresentFromMv(RAIL_ENABLE) == 4200);
    for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(railAbsentUnderMv((Rail)i) < railPresentFromMv((Rail)i));
    // six inputs are active low and the sensor rail is the one plain divider
    for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(railPresentIsHigh((Rail)i) == (i == RAIL_SENS));
}

// ─── the start ────────────────────────────────────────────────────────────────────────────────
static void testStartSequence() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    CHECK(e.state() == EXS_RUNNING);
    // the first two writes are IOCON at the BANK = 1 address and then at the BANK = 0 address
    CHECK(c.log.size() >= 17);
    CHECK(c.log[0].write && c.log[0].reg == 0x05 && c.log[0].value == 0x00);
    CHECK(c.log[1].write && c.log[1].reg == 0x0A && c.log[1].value == 0x00);
    // the output latches are low before the direction makes GPA7 and GPB7 outputs
    int latch = -1, dir = -1;
    for (size_t i = 0; i < c.log.size(); i++) {
        if (c.log[i].write && c.log[i].reg == REG_OLATA && latch < 0) latch = (int)i;
        if (c.log[i].write && c.log[i].reg == REG_IODIRA && dir < 0) dir = (int)i;
    }
    CHECK(latch > 1 && dir > latch);
    // the registers hold what the table says
    CHECK(c.r[REG_IODIRA] == 0x7F && c.r[REG_IODIRB] == 0x7F);
    CHECK(c.r[REG_GPPUA] == 0x70 && c.r[REG_GPPUB] == 0x70);
    CHECK(c.r[REG_IPOLA] == 0 && c.r[REG_IPOLB] == 0);
    CHECK(c.r[REG_GPINTENA] == 0 && c.r[REG_GPINTENB] == 0 && c.r[REG_OLATA] == 0 && c.r[REG_OLATB] == 0);
    CHECK(c.r[REG_IOCON] == 0x00 && !c.bank1);
    // GPA7 and GPB7 are outputs and never inputs, the pull-ups are only on the spare inputs
    CHECK((c.r[REG_IODIRA] & 0x80) == 0 && (c.r[REG_IODIRB] & 0x80) == 0);
    CHECK((c.r[REG_GPPUA] & 0x8F) == 0 && (c.r[REG_GPPUB] & 0x8F) == 0);
    // every write is one byte write, no write puts a 1 in bit 7 of a direction or latch or pull-up register
    for (const Txn& t : c.log) {
        if (!t.write) continue;
        if (t.reg == REG_IODIRA || t.reg == REG_IODIRB || t.reg == REG_OLATA || t.reg == REG_OLATB ||
            t.reg == REG_GPPUA || t.reg == REG_GPPUB) CHECK((t.value & 0x80) == 0);
    }
    // the last transaction is the 22 byte read back
    CHECK(!c.log.back().write && c.log.back().reg == 0x00 && c.log.back().n == REG_COUNT);
    CHECK(e.counters().startFailures == 0);
    CHECK(e.expanderHealth() == HS_OK);
}

static void testStartInEitherAddressingMode() {
    // a chip left in BANK = 1 (the expander is not reset by the processor) and a fresh chip both end the same
    for (int bank = 0; bank < 2; bank++) {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        c.bank1 = bank == 1;
        c.r[REG_IOCON] = bank ? 0x80 : 0x00;
        e.start(0);
        CHECK(e.state() == EXS_RUNNING);
        CHECK(!c.bank1 && c.r[REG_IOCON] == 0x00);
        CHECK(c.r[REG_IODIRA] == 0x7F && c.r[REG_GPPUB] == 0x70);
        // in BANK = 1 the register that the first write lands on is IOCON and nothing before it wrote a latch
        if (bank == 1) CHECK(c.log[0].reg == 0x05);
        // no latch write happens before the chip is known to be in BANK = 0
        CHECK(c.log[0].reg != REG_OLATA && c.log[1].reg != REG_OLATA);
    }
    // a chip in BANK = 1 whose spare byte at 0x05 mattered: the latch of GPIOA at 0x0A in BANK = 1 stays untouched
    FakeChip c; Sink s; Expander e(c, s);
    c.bank1 = true; c.r[REG_IOCON] = 0x80;
    c.r[REG_OLATA] = 0x00;
    e.start(0);
    CHECK(e.state() == EXS_RUNNING);
}

static void testReadBackRefusesAChangedRegister() {
    // a pull-up register that ignores the write
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.ignoreMask[REG_GPPUA] = 0x70;
        e.start(0);
        CHECK(e.state() == EXS_UNTRUSTED && e.cause() == CAUSE_UNTRUSTED);
        CHECK(e.expanderHealth() == HS_OUT_OF_RANGE);
        CHECK(e.counters().untrusted == 1 && e.counters().startFailures == 1);
        CHECK(s.count("not trusted") == 1 && s.count("register 0C") == 1);
    }
    // direction bit 7 that cannot be made an output
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.ignoreMask[REG_IODIRB] = 0x80;
        e.start(0);
        CHECK(e.state() == EXS_UNTRUSTED && s.count("register 01") == 1);
    }
    // a latch bit that sticks high would drive GPA7 high
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.r[REG_OLATA] = 0x80; c.ignoreMask[REG_OLATA] = 0x80;
        e.start(0);
        CHECK(e.state() == EXS_UNTRUSTED && s.count("register 14") == 1);
    }
    // an untrusted chip is not read for rails or the button
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.ignoreMask[REG_IPOLA] = 0x01;
        c.r[REG_IPOLA] = 0x01;
        setRail(c, RAIL_AUX, false);
        e.start(0);
        run(e, 0, 3000);
        // nothing is read from an untrusted chip, so no rail is known and none is called ok or absent
        CHECK(e.railHealth(RAIL_AUX) == HS_STALE && e.expanderHealth() == HS_OUT_OF_RANGE);
        CHECK(!e.buttonDown());
    }
}

static void testPresentBoardDoesNothing() {
    // the present board: no expander on the bus. the driver is never started by the rule
    CHECK(!expanderMayStart(false, BOARD_OK));
    CHECK(!expanderMayStart(false, BOARD_UNKNOWN));
    CHECK(!expanderMayStart(false, BOARD_MISMATCH));
    // a revised image starts it only when the board check found it
    CHECK(expanderMayStart(true, BOARD_OK));
    CHECK(!expanderMayStart(true, BOARD_MISMATCH));
    CHECK(!expanderMayStart(true, BOARD_UNKNOWN));
    // never started means no transfer at all, however long the loop runs. on a revised image (a board
    // mismatch or an unknown board) nothing is known, so the expander and every rail are stale and
    // never ok. on the present image none of this is posted because the sync is not compiled in
    FakeChip c; Sink s; Expander e(c, s);
    run(e, 0, 10000);
    CHECK(c.transactions == 0 && s.lines.empty());
    CHECK(e.expanderHealth() == HS_STALE);
    for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_STALE);
    // the keys are not fitted-off and never set, so the present board's faults map stays empty
    healthInit();
    CHECK(!healthAnyFault());
#if !HAS_EXPANDER
    CHECK(HAS_EXPANDER == 0);
#endif
}

// ─── polling and bus traffic ──────────────────────────────────────────────────────────────────
static void testPollRateAndTraffic() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    int base = c.transactions;
    // 10 s with a call every 5 ms
    uint32_t t = run(e, 1, 10000);
    (void)t;
    int used = c.transactions - base;
    // 10 s / 20 ms = 500 polls and 10 config reads, give or take the edges
    CHECK(used >= 505 && used <= 515);
    // a call never makes more than two transactions
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    e2.start(0);
    int worst = 0;
    for (uint32_t tt = 1; tt < 5000; tt += 5) {
        int before = c2.transactions;
        e2.service(tt);
        int d = c2.transactions - before;
        if (d > worst) worst = d;
    }
    CHECK(worst <= 2);
    // the polling read is the two port bytes only
    bool sawTwo = false;
    for (size_t i = 20; i < c2.log.size(); i++) if (!c2.log[i].write && c2.log[i].reg == REG_GPIOA && c2.log[i].n == 2) sawTwo = true;
    CHECK(sawTwo);
}

// ─── the button ───────────────────────────────────────────────────────────────────────────────
static void testButtonDebounce() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 200);
    // a 20 ms glitch is not a press
    setPin(c, 8, false);
    t = run(e, t, 20, 20);
    setPin(c, 8, true);
    t = run(e, t, 200);
    CHECK(!e.takePress() && !e.buttonDown());
    // a bouncing press that is low 40 ms and more counts once
    for (int k = 0; k < 3; k++) { setPin(c, 8, false); t = run(e, t, 20, 20); setPin(c, 8, true); t = run(e, t, 20, 20); }
    CHECK(!e.takePress());
    setPin(c, 8, false);
    t = run(e, t, 100, 20);
    CHECK(e.buttonDown());
    CHECK(e.takePress());
    CHECK(!e.takePress());              // once per press
    // bounce on release: a short high does not release it
    setPin(c, 8, true); t = run(e, t, 20, 20);
    setPin(c, 8, false); t = run(e, t, 100, 20);
    CHECK(e.buttonDown());
    setPin(c, 8, true);
    t = run(e, t, 200, 20);
    CHECK(!e.buttonDown());
    CHECK(e.counters().presses == 1 && e.counters().longPresses == 0);
    // press time is 40 ms: low for exactly 3 polls (the first sets the edge, 40 ms later it commits)
    uint32_t pressAt = t + 20;
    setPin(c, 8, false);
    uint32_t seenAt = 0;
    for (uint32_t k = 0; k < 20; k++) { e.service(pressAt + k * 20); if (e.buttonDown() && !seenAt) seenAt = pressAt + k * 20; }
    CHECK(seenAt - pressAt == BUTTON_PRESS_MS);
}

static void testLongPress() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 200);
    setPin(c, 8, false);
    t = run(e, t, 4800);
    CHECK(e.buttonDown() && !e.takeLongPress());
    t = run(e, t, 400);
    CHECK(e.takeLongPress());
    CHECK(!e.takeLongPress());
    t = run(e, t, 6000);                // still held: one event only
    CHECK(!e.takeLongPress() && e.counters().longPresses == 1);
    setPin(c, 8, true);
    t = run(e, t, 300);
    CHECK(!e.buttonDown());
    // a second long press needs a release first
    setPin(c, 8, false);
    t = run(e, t, 5500);
    CHECK(e.takeLongPress() && e.counters().longPresses == 2);
}

static void testButtonStuckAtStartIsIgnored() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    setPin(c, 8, false);               // reads pressed from the first read
    e.start(0);
    uint32_t t = run(e, 1, 12000);
    CHECK(!e.buttonDown() && !e.takePress() && !e.takeLongPress());
    CHECK(s.count("reads pressed from the start") == 1);
    // once seen released it works
    setPin(c, 8, true);
    t = run(e, t, 300);
    setPin(c, 8, false);
    t = run(e, t, 6000);
    CHECK(e.takePress() && e.takeLongPress());
}

static void testLongHoldOverALongBlockIsNotCreditedInFull() {
    // a pass that holds the loop for 3 s between two polls counts for no more than the credit limit
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 200);
    setPin(c, 8, false);
    t = run(e, t, 100, 20);
    CHECK(e.buttonDown());
    e.takePress();
    t += 3000;                          // the loop was blocked
    e.service(t);
    t = run(e, t + 5, 100, 20);
    CHECK(e.buttonHeldMs() < 1000);
    CHECK(!e.takeLongPress());
}

// ─── the rails ────────────────────────────────────────────────────────────────────────────────
static void testRailAbsentAndBack() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 2000);
    CHECK(e.railHealth(RAIL_FEED2) == HS_OK && s.count("[rail]") == 0);
    uint32_t dropAt = t;
    setRail(c, RAIL_FEED2, false);
    t = run(e, t, 300);
    CHECK(e.railHealth(RAIL_FEED2) == HS_OK);        // not yet: 500 ms
    t = run(e, t, 400);
    CHECK(e.railHealth(RAIL_FEED2) == HS_MISSING);
    // it says which rail and since when. the time is the onset and not the time of the verdict
    CHECK(e.railSince(RAIL_FEED2) >= dropAt && e.railSince(RAIL_FEED2) < dropAt + EXPANDER_POLL_MS + 5);
    CHECK(s.count("12 V feed 2 is absent") == 1 && s.count("FEED2_OK reads high") == 1);
    CHECK(e.railHealth(RAIL_FEED1) == HS_OK && e.railHealth(RAIL_AUX) == HS_OK);
    // said once however long it lasts
    t = run(e, t, 20000);
    CHECK(s.count("[rail]") == 1);
    setRail(c, RAIL_FEED2, true);
    t = run(e, t, 700);
    CHECK(e.railHealth(RAIL_FEED2) == HS_OK && s.count("12 V feed 2 is present") == 1);
}

static void testRailAbsentAtBootAndAllSevenNamed() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllAbsent(c);                   // every rail absent, button released
    e.start(0);
    run(e, 1, 1500);
    for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_MISSING);
    CHECK(s.count("[rail]") == 7);
    CHECK(s.count("SENS_OK reads low") == 1 && s.count("AUX_OK reads high") == 1 && s.count("FEED1_OK reads high") == 1);
    CHECK(s.count("5 V AUX rail is absent") == 1 && s.count("sensor rail is absent") == 1 &&
          s.count("strip rail is absent") == 1 && s.count("relay 5 V rail is absent") == 1 &&
          s.count("12 V feed 1 is absent") == 1 && s.count("12 V feed 3 is absent") == 1);
    // the health keys carry the plain names
    CHECK(railKey(RAIL_AUX) == SK_RAIL_AUX && railKey(RAIL_ENABLE) == SK_RAIL_ENABLE);
    CHECK(std::strcmp(healthKeyName(railKey(RAIL_SENS)), "sens_rail") == 0);
}

static void testRailInTheUndefinedBandCannotFlap() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 2000);
    // a rail near its threshold reads high and low in turn on every poll for a long time
    bool level = true;
    for (int k = 0; k < 400; k++) {            // 8 s
        level = !level;
        setRail(c, RAIL_STRIP, level);
        e.service(t); t += EXPANDER_POLL_MS;
    }
    // it never passed the debounce, so it was never called absent or present again
    CHECK(e.railHealth(RAIL_STRIP) == HS_INTERMITTENT);
    CHECK(e.railKnownPresent(RAIL_STRIP));
    CHECK(s.count("strip rail is absent") == 0);
    CHECK(s.count("strip rail is unstable") == 1);     // said once
    // a rail that dithers every so often (a few hundred ms apart) also never reports absent
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    railsAllPresent(c2);
    e2.start(0);
    uint32_t t2 = run(e2, 1, 1000);
    for (int k = 0; k < 40; k++) {
        setRail(c2, RAIL_AUX, false); t2 = run(e2, t2, 300, 20);
        setRail(c2, RAIL_AUX, true);  t2 = run(e2, t2, 300, 20);
    }
    CHECK(s2.count("5 V AUX rail is absent") == 0);
    CHECK(e2.railHealth(RAIL_AUX) == HS_INTERMITTENT);
    // when it settles high the unstable report clears after the window
    t2 = run(e2, t2, RAIL_FLAP_WINDOW_MS + 1000);
    CHECK(e2.railHealth(RAIL_AUX) == HS_OK);
    // and one that settles low is absent
    setRail(c2, RAIL_AUX, false);
    t2 = run(e2, t2, 1200);
    CHECK(e2.railHealth(RAIL_AUX) == HS_MISSING);
}

static void testSpareAndPortSevenBitsAreNeverRead() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    // noise on the spare pins and on bit 7 of both ports changes nothing
    uint32_t t = 1;
    for (int k = 0; k < 300; k++) {
        c.pinsA = (uint8_t)((k * 37) & 0xF0);          // the four rails present (low), noise above
        c.pinsB = (uint8_t)(0x03 | ((k * 53) & 0xF0));    // button released, SENS_OK high, the transistor rails low
        e.noteSensorAnswered(t); e.service(t); t += 20;
    }
    for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_OK);
    CHECK(s.count("[rail]") == 0);
}

// ─── the sense of each input ──────────────────────────────────────────────────────────────────
static void testRailPolarityFollowsTheTable() {
    // the raw pin level for a present rail: low for the six transistor inputs and high for SENS_OK
    for (uint8_t i = 0; i < RAIL_COUNT; i++) {
        Rail r = (Rail)i;
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        uint8_t idx = (uint8_t)railPinIndex(r);
        uint8_t level = (uint8_t)(((idx < 8 ? c.pinsA : c.pinsB) >> (idx & 7)) & 1u);
        CHECK(level == (r == RAIL_SENS ? 1u : 0u));
        e.start(0);
        uint32_t t = run(e, 1, 1500);
        CHECK(e.railKnownPresent(r) && e.railHealth(r) == HS_OK);
        // the opposite level is an absent rail
        setPin(c, idx, level == 0);
        t = run(e, t, 800);
        CHECK(e.railHealth(r) == HS_MISSING);
        char want[40];
        std::snprintf(want, sizeof want, "%s reads %s", railNet(r), r == RAIL_SENS ? "low" : "high");
        CHECK(s.count(want) == 1);
        // and back again
        setPin(c, idx, level != 0);
        t = run(e, t, 800);
        CHECK(e.railHealth(r) == HS_OK && e.railKnownPresent(r));
        // the other six rails never moved
        for (uint8_t o = 0; o < RAIL_COUNT; o++) if (o != i) CHECK(e.railHealth((Rail)o) == HS_OK);
    }
}

static void testStartStatesAreNotMistakenForTheOtherSense() {
    // every pin reads high from the first read (a transistor input with its rail off or one that
    // floats). the six transistor rails are absent and SENS_OK is present, never the other way round
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.pinsA = 0xFF; c.pinsB = 0xFF;
        e.start(0);
        run(e, 1, 100);
        // nothing is reported before the 500 ms debounce, so a floating pin cannot be called present or absent at once
        for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_STALE && !e.railKnownPresent((Rail)i));
        run(e, 101, 1500);
        for (uint8_t i = 0; i < RAIL_COUNT; i++) {
            if (i == RAIL_SENS) CHECK(e.railKnownPresent(RAIL_SENS) && e.railHealth(RAIL_SENS) == HS_OK);
            else CHECK(e.railHealth((Rail)i) == HS_MISSING);
        }
        CHECK(s.count("[rail]") == 6 && s.count("sensor rail is absent") == 0);
    }
    // every pin reads low: six rails present and SENS_OK absent
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.pinsA = 0x00; c.pinsB = 0x01;
        e.start(0);
        run(e, 1, 1600);
        for (uint8_t i = 0; i < RAIL_COUNT; i++) {
            if (i == RAIL_SENS) CHECK(e.railHealth(RAIL_SENS) == HS_MISSING);
            else CHECK(e.railKnownPresent((Rail)i) && e.railHealth((Rail)i) == HS_OK);
        }
        CHECK(s.count("[rail]") == 1 && s.count("sensor rail is absent: SENS_OK reads low") == 1);
    }
}

static void testAbsentSinceIsTheFirstRawEdgeForAnInvertedInput() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 2000);
    uint32_t edgeAt = t + 3;
    // the transistor input goes high: absent. the since time is the first high read and not the verdict
    while (t < edgeAt) { e.service(t); t += 1; }
    setRail(c, RAIL_AUX, false);
    t = run(e, t, 700, 5);
    CHECK(e.railHealth(RAIL_AUX) == HS_MISSING);
    CHECK(e.railSince(RAIL_AUX) >= edgeAt && e.railSince(RAIL_AUX) <= edgeAt + EXPANDER_POLL_MS);
    // a pin that floats high for less than the debounce and returns low is never reported
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    railsAllPresent(c2);
    e2.start(0);
    uint32_t t2 = run(e2, 1, 2000);
    setRail(c2, RAIL_FEED1, false);
    t2 = run(e2, t2, 300, 20);
    setRail(c2, RAIL_FEED1, true);
    t2 = run(e2, t2, 1000);
    CHECK(s2.count("[rail]") == 0 && e2.railHealth(RAIL_FEED1) == HS_OK);
}

static void testBrownOutReportsNothingAboutRailsWhileReconfiguring() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    setRail(c, RAIL_STRIP, false);       // one rail absent before the reset
    e.start(0);
    uint32_t t = run(e, 1, 3000);
    CHECK(e.railHealth(RAIL_STRIP) == HS_MISSING && s.count("[rail]") == 1);
    size_t before = s.lines.size();
    c.reset();                           // all inputs, pull-ups off. the transistor inputs still read their true levels
    t = run(e, t, 400);
    // the states hold and nothing is said about any rail until the read-back finds the loss
    CHECK(e.railHealth(RAIL_STRIP) == HS_MISSING && e.railHealth(RAIL_AUX) == HS_OK && e.railHealth(RAIL_SENS) == HS_OK);
    CHECK(s.count("[rail]") == 1);
    t = run(e, t, 1500);
    CHECK(e.counters().reconfigured == 1);
    // the only new line is the one about the chip and no rail changed state through the reconfigure
    CHECK(s.lines.size() == before + 1 && s.count("lost its configuration") == 1 && s.count("[rail]") == 1);
    CHECK(e.railHealth(RAIL_STRIP) == HS_MISSING && e.railHealth(RAIL_AUX) == HS_OK && e.expanderHealth() == HS_OK);
    CHECK(e.state() == EXS_RUNNING);
}

// ─── the failures ─────────────────────────────────────────────────────────────────────────────
static void testNotAnsweringAtStart() {
    FakeChip c; Sink s; Expander e(c, s);
    c.answering = false;
    e.start(100);
    CHECK(e.state() == EXS_DOWN && e.cause() == CAUSE_NO_ANSWER);
    CHECK(e.counters().startFailures == 1 && e.counters().lost == 0);
    CHECK(e.expanderHealth() == HS_MISSING);
    CHECK(c.transactions == 1);                       // the start ended at the first failed transfer
    CHECK(s.count("did not answer at start") == 1);
    // retries after 1 s, 2 s, 4 s and so on, one transfer each and says nothing more
    uint32_t t = 100;
    std::vector<uint32_t> tries;
    int last = c.transactions;
    for (uint32_t k = 0; k < 130000; k += 5) {
        e.service(t + k);
        if (c.transactions != last) { tries.push_back(k); last = c.transactions; }
    }
    CHECK(tries.size() >= 5);
    CHECK(tries[0] >= EXPANDER_RETRY_START_MS && tries[0] < EXPANDER_RETRY_START_MS + 10);
    CHECK(tries[1] - tries[0] >= 2000 && tries[1] - tries[0] < 2010);
    CHECK(tries[2] - tries[1] >= 4000 && tries[2] - tries[1] < 4010);
    // capped at 30 s
    CHECK(tries.back() - tries[tries.size() - 2] == EXPANDER_RETRY_MAX_MS);
    CHECK(s.lines.size() == 1);
    // the chip turns up: running again, counted as recovered
    c.answering = true; railsAllPresent(c);
    t += 200000;
    for (uint32_t k = 0; k < 40000; k += 5) e.service(t + k);
    CHECK(e.state() == EXS_RUNNING && e.counters().recovered == 1 && s.count("answering again") == 1);
}

static void testStopsAnsweringLater() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 2000);
    setRail(c, RAIL_SENS, false);
    t = run(e, t, 700);
    CHECK(e.railHealth(RAIL_SENS) == HS_MISSING && e.railHealth(RAIL_AUX) == HS_OK);
    c.answering = false;
    t = run(e, t, 4000);
    CHECK(e.state() == EXS_DOWN && e.cause() == CAUSE_NO_ANSWER);
    CHECK(e.counters().lost == 1);
    CHECK(e.expanderHealth() == HS_MISSING);
    // nobody knows the rails now, so every one is stale. none is ok and none is absent
    for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_STALE);
    // one message about the chip. an earlier lone failure may have said a read failed first
    CHECK(s.count("stopped answering") == 1 && s.count("stale") >= 1);
    // a long outage costs one transfer per retry and adds no message
    int tx = c.transactions;
    size_t lines = s.lines.size();
    t = run(e, t, 120000);
    CHECK(c.transactions - tx <= 12);
    CHECK(s.lines.size() == lines);
    // a rail that changed while the chip was away is found when it answers again: it is read from scratch
    setRail(c, RAIL_FEED1, false);
    c.answering = true; c.reset();
    t = run(e, t, 40000);
    CHECK(e.state() == EXS_RUNNING && e.counters().recovered == 1);
    CHECK(c.r[REG_GPPUA] == 0x70 && c.r[REG_IODIRB] == 0x7F);
    CHECK(e.railHealth(RAIL_FEED1) == HS_MISSING && e.railHealth(RAIL_AUX) == HS_OK && e.railHealth(RAIL_SENS) == HS_MISSING);
    CHECK(!e.buttonDown());
}

static void testAFailedReadIsOnlyCounted() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 1000);
    setRail(c, RAIL_AUX, false);
    t = run(e, t, 100);
    uint32_t samples = e.counters().samples;
    c.failNext = 1;
    t = run(e, t, 100);
    CHECK(e.state() == EXS_RUNNING);
    CHECK(e.counters().readFailures == 1 && e.counters().lost == 0);
    CHECK(s.count("a read failed") == 1);
    // a failed read is never a sample
    CHECK(e.counters().samples <= samples + 4 && e.counters().readFailures == 1);
    t = run(e, t, 1500);
    CHECK(e.railHealth(RAIL_AUX) == HS_MISSING && e.expanderHealth() == HS_OK);
    // another lone failure a moment later is counted and not said again
    c.failNext = 1;
    t = run(e, t, 700);
    CHECK(e.counters().readFailures == 2 && s.count("a read failed") == 1 && e.state() == EXS_RUNNING);
    // a third inside ten seconds is a loss, though good reads came between them
    c.failNext = 1;
    t = run(e, t, 700);
    CHECK(e.state() == EXS_DOWN && e.counters().lost == 1);
}

static void testFailuresInsideTheWindowAreNotOnlyConsecutive() {
    // every other read fails: the old rule of three in a row never fired and the loop paid for ever
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 1000);
    for (int k = 0; k < 6 && e.state() == EXS_RUNNING; k++) {
        c.failNext = 1;
        t = run(e, t, 700);
    }
    CHECK(e.state() == EXS_DOWN);
    CHECK(e.counters().readFailures == 3 && e.counters().lost == 1);
    // failures spread over more than the window are lone failures and the chip stays up
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    railsAllPresent(c2);
    e2.start(0);
    uint32_t t2 = run(e2, 1, 1000);
    for (int k = 0; k < 6; k++) { c2.failNext = 1; t2 = run(e2, t2, EXPANDER_FAIL_WINDOW_MS / 2 + 1000); }
    CHECK(e2.state() == EXS_RUNNING && e2.counters().readFailures == 6);
}

static void testStuckBus() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 1000);
    c.answering = false; c.deadKind = BUS_TIMEOUT;
    t = run(e, t, 4000);
    CHECK(e.state() == EXS_DOWN && e.cause() == CAUSE_BUS_STUCK);
    CHECK(e.counters().busStuck == 1 && e.counters().lost == 1);
    CHECK(s.count("I2C bus stuck") == 1 && s.count("stopped answering") == 0);
    // still stuck at the next tries: not counted again and not said again
    t = run(e, t, 60000);
    CHECK(e.counters().busStuck == 1 && s.count("I2C bus stuck") == 1);
    // at start it is the same
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    c2.answering = false; c2.deadKind = BUS_TIMEOUT;
    e2.start(0);
    CHECK(e2.cause() == CAUSE_BUS_STUCK && e2.counters().busStuck == 1 && e2.counters().startFailures == 1);
}

static void testARefusedAddressIsNotAStuckBus() {
    // a chip that does not answer is not a stuck bus. in the real binding a failed read is only
    // "failed" (requestFrom returns 0 for a refusal and a time-out alike), so the driver sends one
    // address-only probe to tell them apart and the scripted chip fails the same way
    FakeChip c; Sink s; Expander e(c, s);
    CHECK(c.realisticReads);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 1000);
    c.answering = false; c.deadKind = BUS_NACK;
    int before = c.transactions;
    t = run(e, t, 4000);
    CHECK(e.state() == EXS_DOWN && e.cause() == CAUSE_NO_ANSWER && e.counters().busStuck == 0);
    CHECK(s.count("does not answer") == 1 && s.count("I2C bus stuck") == 0);
    // each failed read is followed by exactly one probe
    CHECK(c.transactions - before >= 6);
    // the read itself returned BUS_FAIL and never a refusal
    uint8_t buf[2];
    BusResult r = c.readRegs(REG_GPIOA, buf, 2);
    CHECK(r == BUS_FAIL);
    CHECK(c.probe() == BUS_NACK);
    // a bus held low is the other fault
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    railsAllPresent(c2);
    e2.start(0);
    uint32_t t2 = run(e2, 1, 1000);
    c2.answering = false; c2.deadKind = BUS_TIMEOUT;
    t2 = run(e2, t2, 4000);
    CHECK(e2.cause() == CAUSE_BUS_STUCK && s2.count("I2C bus stuck") == 1);
    // a read that fails while the address is still acknowledged is a bus that does not complete
    FakeChip c3; Sink s3; Expander e3(c3, s3);
    railsAllPresent(c3);
    e3.start(0);
    uint32_t t3 = run(e3, 1, 1000);
    for (int k = 0; k < 3; k++) { c3.failNext = 1; t3 = run(e3, t3, 700); }
    CHECK(e3.cause() == CAUSE_BUS_STUCK);
    // the error mapping of the binding: 0 ok, 2 and 3 no acknowledge and the rest a held bus
    CHECK(busFromWire(0) == BUS_OK && busFromWire(2) == BUS_NACK && busFromWire(3) == BUS_NACK);
    CHECK(busFromWire(1) == BUS_TIMEOUT && busFromWire(4) == BUS_TIMEOUT && busFromWire(5) == BUS_TIMEOUT);
    // and the binding uses that mapping and reports a short read as BUS_FAIL, not as a time-out or a refusal
    std::string bind = slurp("../sensors/mcp23017.cpp");
    CHECK(!bind.empty());
    CHECK(bind.find("mcp::busFromWire(Wire.endTransmission())") != std::string::npos);
    CHECK(bind.find("mcp::busFromWire(code)") != std::string::npos);
    CHECK(bind.find("requestFrom((uint8_t)MCP23017_ADDR, n) != n) return mcp::BUS_FAIL;") != std::string::npos);
    CHECK(bind.find("mcp::BusResult probe() override") != std::string::npos);
}

static void testCallsNeverMakeMoreThanTwoFailedTransfers() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    c.answering = false; c.deadKind = BUS_TIMEOUT;
    int worstFailed = 0;
    for (uint32_t t = 1; t < 200000; t += 5) {
        int before = c.failedTransactions;
        e.service(t);
        int d = c.failedTransactions - before;
        if (d > worstFailed) worstFailed = d;
    }
    // a failed read and its probe are two transfers and the call ends there. a retry fails at its first write
    CHECK(worstFailed <= 2);
    // and over 200 s a dead chip cost only a few transfers
    CHECK(c.failedTransactions <= 2 * EXPANDER_FAIL_LIMIT + 12);
}

static void testTransfersPerCall() {
    // a call that reconfigures makes 19 transfers (a pin read, the read-back and the 17 of the start)
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 3000);
    c.reset();
    int worst = 0;
    for (int k = 0; k < 400; k++) {
        int before = c.transactions;
        e.service(t); t += 5;
        int d = c.transactions - before;
        if (d > worst) worst = d;
    }
    CHECK(e.counters().reconfigured == 1);
    CHECK(worst == (int)EXPANDER_MAX_TRANSFERS_PER_CALL && worst == 19);
    // every other call is two at most
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    railsAllPresent(c2);
    e2.start(0);
    int worst2 = 0;
    for (uint32_t tt = 1; tt < 20000; tt += 5) {
        int before = c2.transactions;
        e2.service(tt);
        int d = c2.transactions - before;
        if (d > worst2) worst2 = d;
    }
    CHECK(worst2 <= 2);
}

static void testChipResetMidRun() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 3000);
    setRail(c, RAIL_ENABLE, false);
    t = run(e, t, 700);
    CHECK(e.railHealth(RAIL_ENABLE) == HS_MISSING);
    // a brown-out: all inputs, pull-ups off, configuration zero
    c.reset();
    // reading the pins still works while it is unconfigured, so the rails go on being read
    t = run(e, t, 100);
    CHECK(e.railHealth(RAIL_ENABLE) == HS_MISSING && e.state() == EXS_RUNNING);
    t = run(e, t, 1200);
    CHECK(e.counters().reconfigured == 1);
    CHECK(s.count("lost its configuration") == 1);
    CHECK(c.r[REG_GPPUA] == 0x70 && c.r[REG_GPPUB] == 0x70 && c.r[REG_IODIRA] == 0x7F && c.r[REG_IODIRB] == 0x7F);
    CHECK(e.state() == EXS_RUNNING && e.expanderHealth() == HS_OK);
    // a chip that was in BANK = 1 after the reset of something else is also put right
    c.bank1 = true; c.r[REG_IOCON] = 0x80;
    t = run(e, t, 2500);
    CHECK(e.counters().reconfigured >= 2 && !c.bank1 && c.r[REG_GPPUA] == 0x70);
    // each reset is counted and said once
    c.reset();
    t = run(e, t, 1500);
    CHECK(e.counters().reconfigured >= 3 && s.count("lost its configuration") == (int)e.counters().reconfigured);
    // a single bit that drifts is found too
    uint32_t n = e.counters().reconfigured;
    c.r[REG_GPPUB] = 0x30;
    t = run(e, t, 1500);
    CHECK(e.counters().reconfigured == n + 1 && c.r[REG_GPPUB] == 0x70);
}

// ─── silence is never "up" ────────────────────────────────────────────────────────────────────
static void testNoRailIsUpWithoutAFreshReading() {
    // before anything has been read: the chip is up and the first 500 ms have not passed
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        run(e, 1, 200);
        for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_STALE);
        run(e, 201, 1500);
        for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_OK);
        CHECK(e.railsUnknownForMs(1700) == 0);
    }
    // a chip that never answered leaves seven of seven rails stale, however long it goes on
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.answering = false;
        e.start(0);
        run(e, 1, 120000, 20);
        for (uint8_t i = 0; i < RAIL_COUNT; i++) CHECK(e.railHealth((Rail)i) == HS_STALE);
        CHECK(e.expanderHealth() == HS_MISSING);
        // and how long they have been unknown is known
        CHECK(e.railsUnknownForMs(120001) >= 119000);
    }
    // a rail that went away while the chip was silent is not up an hour later
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        c.answering = false;
        setRail(c, RAIL_FEED1, false);
        t = run(e, t, 3600000, 20);
        CHECK(e.railHealth(RAIL_FEED1) == HS_STALE && e.railHealth(RAIL_AUX) == HS_STALE);
        // the last good reading is the time its state began, so the age is the outage
        CHECK(e.railSince(RAIL_AUX) < 5000);
        CHECK(e.railsUnknownForMs(t) > 3500000);
    }
    // an untrusted chip that was running: stale and not ok for ten minutes
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        c.ignoreMask[REG_GPPUA] = 0x70; c.reset(); setRail(c, RAIL_AUX, false);
        t = run(e, t, 600000, 20);
        CHECK(e.state() == EXS_UNTRUSTED && e.railHealth(RAIL_AUX) == HS_STALE);
    }
    // a good reading that is more than EXPANDER_FRESH_MS old is not fresh: a bus that fails for a while
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        CHECK(e.railHealth(RAIL_AUX) == HS_OK);
        c.failNext = 1000000;
        t = run(e, t, 200);
        CHECK(e.railHealth(RAIL_AUX) == HS_OK);                       // still fresh
        t = run(e, t, EXPANDER_FRESH_MS + 500);
        CHECK(e.railHealth(RAIL_AUX) == HS_STALE);
    }
    // the health table carries the word that the backend already knows
    CHECK(std::strcmp(healthStateName(HS_STALE), "stale") == 0);
    // a rail that is not watched is never reported at all
    CHECK(Expander::railExpected(RAIL_AUX));
}

// ─── the sensor rail is "not proven off" until a sensor answers ───────────────────────────────
static void testSensRailNeedsASensorToBeCalledPresent() {
    g_sensors = false;
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 3000);
    // SENS_OK reads high but no sensor has answered: not proven up, so stale and not ok
    CHECK(e.railKnownPresent(RAIL_SENS) && e.railHealth(RAIL_SENS) == HS_STALE);
    CHECK(e.railHealth(RAIL_AUX) == HS_OK);
    // the note is made once after a while
    t = run(e, t, EXPANDER_SENS_PROOF_MS + 1000);
    CHECK(s.count("not proven up") == 1);
    t = run(e, t, 20000);
    CHECK(s.count("not proven up") == 1);
    // a sensor answers: up
    e.noteSensorAnswered(t);
    CHECK(e.railHealth(RAIL_SENS) == HS_OK);
    // the sensors stop answering while SENS_OK stays high (the pull-ups hold it): stale again after a while
    t = run(e, t, EXPANDER_SENSOR_FRESH_MS - 1000);
    CHECK(e.railHealth(RAIL_SENS) == HS_OK);
    t = run(e, t, 2500);
    CHECK(e.railHealth(RAIL_SENS) == HS_STALE);
    // SENS_OK reading low is absent whether or not a sensor answered
    setRail(c, RAIL_SENS, false);
    t = run(e, t, 800);
    CHECK(e.railHealth(RAIL_SENS) == HS_MISSING);
    e.noteSensorAnswered(t);
    CHECK(e.railHealth(RAIL_SENS) == HS_MISSING);
    g_sensors = true;
}

static void testSensRailReturnIsJudgedOnThePollsAndNeverBlocks() {
    // it comes back: two polls in a row
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        int before = c.transactions;
        e.armSensRailReturn(t, SENSOR_RAIL_RETURN_LIMIT_MS);
        CHECK(c.transactions == before);                  // arming makes no transfer: nothing waits
        CHECK(e.sensRailReturnPending());
        // the sensors that answered before the switch say nothing about the rail now
        CHECK(e.railHealth(RAIL_SENS) == HS_STALE);
        g_sensors = false;
        t = run(e, t, 100);
        CHECK(!e.sensRailReturnPending() && s.count("reads high again") == 1 && s.count("did not come back") == 0);
        // present only once a sensor has answered since the switch
        CHECK(e.railHealth(RAIL_SENS) == HS_STALE);
        e.noteSensorAnswered(t);
        CHECK(e.railHealth(RAIL_SENS) == HS_OK);
        g_sensors = true;
    }
    // it does not: a plain fault at the limit and judged on polls, so the first call after the limit says it
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        setRail(c, RAIL_SENS, false);
        uint32_t armAt = t;
        e.armSensRailReturn(armAt, SENSOR_RAIL_RETURN_LIMIT_MS);
        t = run(e, t, SENSOR_RAIL_RETURN_LIMIT_MS - 40);
        CHECK(e.sensRailReturnPending() && s.count("did not come back") == 0);
        t = run(e, t, 100);
        CHECK(!e.sensRailReturnPending());
        CHECK(e.railHealth(RAIL_SENS) == HS_MISSING && e.railSince(RAIL_SENS) == armAt);
        CHECK(s.count("did not come back") == 1 && s.count("300 ms") == 1);
        CHECK(e.counters().sensRailNotBack == 1);
        // it turns up late: the normal debounce clears it and a sensor has to answer for ok
        setRail(c, RAIL_SENS, true);
        t = run(e, t, 800);
        CHECK(e.railHealth(RAIL_SENS) == HS_OK);
    }
    // a glitch high does not confirm it: two polls in a row
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        setRail(c, RAIL_SENS, false);
        e.armSensRailReturn(t, SENSOR_RAIL_RETURN_LIMIT_MS);
        // high on every third poll only
        for (int k = 0; k < 40; k++) {
            setRail(c, RAIL_SENS, (k % 3) == 0);
            e.noteSensorAnswered(t); e.service(t); t += EXPANDER_POLL_MS;
        }
        CHECK(s.count("did not come back") == 1 && s.count("reads high again") == 0);
    }
    // one late poll that finds the rail up still passes, as when initCableSensors held the loop
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        e.armSensRailReturn(t, SENSOR_RAIL_RETURN_LIMIT_MS);
        t += 4000;
        t = run(e, t, 100);
        CHECK(s.count("did not come back") == 0 && s.count("reads high again") == 1);
    }
    // the expander cannot be read: nothing is claimed about the rail
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        c.answering = false;
        e.armSensRailReturn(t, SENSOR_RAIL_RETURN_LIMIT_MS);
        t = run(e, t, 5000);
        CHECK(s.count("not confirmed") == 1 && s.count("did not come back") == 0 && !e.sensRailReturnPending());
        CHECK(e.counters().sensRailNotBack == 0);
    }
    // it never waits for the input to fall: a high input passes on the second poll
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(0);
        uint32_t t = run(e, 1, 2000);
        e.armSensRailReturn(t, SENSOR_RAIL_RETURN_LIMIT_MS);
        e.service(t); e.service(t + EXPANDER_POLL_MS);
        CHECK(!e.sensRailReturnPending());
    }
}

// ─── the INTF register ────────────────────────────────────────────────────────────────────────
static void testFlagRegistersAreLive() {
    // older firmware left interrupts on and a flag set. it is not compared, so the first read-back
    // passes and the periodic one does not reconfigure for ever
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    c.intf[0] = 0x05; c.intf[1] = 0x82;
    e.start(0);
    CHECK(e.state() == EXS_RUNNING && e.counters().untrusted == 0);
    run(e, 1, 5000);
    CHECK(e.state() == EXS_RUNNING && e.counters().reconfigured == 0);
    // an enable register left on is still a mismatch, because that one is written
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    c2.r[REG_GPINTENA] = 0x01; c2.ignoreMask[REG_GPINTENA] = 0x01;
    e2.start(0);
    CHECK(e2.state() == EXS_UNTRUSTED && s2.count("register 04") == 1);
    CHECK(expectedReg(REG_INTFA).mask == 0 && expectedReg(REG_INTFB).mask == 0);
}

// ─── a failed read counts for nothing ─────────────────────────────────────────────────────────
static void testAFailedReadDoesNotCountTowardsAChange() {
    // the rail goes absent and one read fails in the middle. the time around the failed read is not
    // credited, so the verdict comes after 500 ms of reads that did happen plus the back-off
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 1000, 20);
    uint32_t drop = t;
    setRail(c, RAIL_AUX, false);
    uint32_t seen = 0;
    for (int k = 0; k < 120; k++) {
        if (k == 5) c.failNext = 1;
        e.noteSensorAnswered(t); e.service(t);
        if (!seen && e.railHealth(RAIL_AUX) == HS_MISSING) seen = t;
        t += 20;
    }
    CHECK(seen != 0);
    CHECK(seen - drop >= 500 + EXPANDER_FAIL_BACKOFF_MS - 20);
    // samples are only the good reads
    CHECK(e.counters().readFailures == 1);
    // a failed read is never a sample of anything: reads that fail do not move the rails
    FakeChip c2; Sink s2; Expander e2(c2, s2);
    railsAllPresent(c2);
    e2.start(0);
    uint32_t t2 = run(e2, 1, 1000, 20);
    uint32_t good = e2.counters().samples;
    c2.failNext = 1;
    t2 = run(e2, t2, 100, 20);
    uint32_t afterFail = e2.counters().samples;
    CHECK(afterFail == good);                      // the failed poll added no sample
    CHECK(e2.railHealth(RAIL_AUX) == HS_OK && s2.count("[rail]") == 0);
}

// ─── how much the driver can cost the loop ────────────────────────────────────────────────────
struct PatternBus : ExpanderBus {
    FakeChip& c;
    uint32_t  now = 0;                 // the loop's clock, moved on by every failed transfer
    uint32_t  rng = 12345;
    int       mode = 0;
    double    p = 0.5;
    long      n = 0;
    std::vector<std::pair<uint32_t, uint32_t>> blocked;   // time and cost of each failed transfer
    PatternBus(FakeChip& cc) : c(cc) {}
    bool coin(double prob) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return (rng % 10000) < prob * 10000; }
    bool shouldFail(bool isProbe) {
        n++;
        switch (mode) {
            case 0: return now >= 1000;                                   // dead chip, time-outs
            case 1: return !isProbe && (n % 2 == 0);                      // every other read
            case 2: return true;                                          // every transfer
            case 3: return (n % 3) != 0;                                  // two in three
            case 4: return coin(p);                                       // random
            case 5: return (now % 3000) >= 1000;                          // up 1 s and down 2 s
            case 6: return (now % 6000) >= 5000;                          // up 5 s and down 1 s
            case 7: return !isProbe && ((n % 5) == 0);                    // one in five reads
            default: return false;
        }
    }
    BusResult fail(bool read) { blocked.push_back({now, EXPANDER_BUS_TIMEOUT_MS}); now += EXPANDER_BUS_TIMEOUT_MS; return read ? BUS_FAIL : BUS_TIMEOUT; }
    BusResult writeReg(uint8_t r, uint8_t v) override { if (shouldFail(false)) return fail(false); return c.writeReg(r, v); }
    BusResult readRegs(uint8_t r, uint8_t* o, uint8_t k) override { if (shouldFail(false)) return fail(true); return c.readRegs(r, o, k); }
    BusResult probe() override { if (shouldFail(true)) return fail(false); return BUS_OK; }
};

static uint32_t worstWindow(const PatternBus& b, uint32_t window) {
    uint32_t worst = 0;
    size_t lo = 0;
    uint32_t sum = 0;
    for (size_t hi = 0; hi < b.blocked.size(); hi++) {
        sum += b.blocked[hi].second;
        while (b.blocked[hi].first - b.blocked[lo].first >= window) { sum -= b.blocked[lo].second; lo++; }
        if (sum > worst) worst = sum;
    }
    return worst;
}

static void testWorstCostToTheLoopInAnyTenSeconds() {
    // the loop calls service() every 2 ms and each failed transfer costs one Wire time-out of 50 ms
    struct Case { const char* name; int mode; double p; uint32_t seed; };
    Case cases[] = {
        {"dead chip", 0, 0, 1}, {"every other read", 1, 0, 1}, {"every transfer", 2, 0, 1}, {"two in three", 3, 0, 1},
        {"random 30 per cent", 4, 0.3, 7}, {"random 50 per cent", 4, 0.5, 9}, {"random 80 per cent", 4, 0.8, 11},
        {"random 10 per cent", 4, 0.1, 5}, {"up 1 s down 2 s", 5, 0, 1}, {"up 5 s down 1 s", 6, 0, 1},
        {"one read in five", 7, 0, 1}, {"random 60 per cent", 4, 0.6, 99}, {"random 20 per cent", 4, 0.2, 31},
    };
    uint32_t overall = 0;
    for (const Case& k : cases) {
        FakeChip c; Sink s;
        railsAllPresent(c);
        PatternBus b(c);
        b.mode = k.mode; b.p = k.p; b.rng = 1234567u + k.seed * 7919u;
        Expander e(b, s);
        b.mode = 99; e.start(0); b.mode = k.mode;       // a clean start, then the failures
        uint32_t startEnd = 1;
        b.now = startEnd;
        // 20 minutes of loop
        while (b.now < 1200000u) {
            e.noteSensorAnswered(b.now);
            e.service(b.now);
            b.now += 2;
        }
        uint32_t w = worstWindow(b, 10000);
        overall = w > overall ? w : overall;
        CHECK(w <= EXPANDER_WORST_COST_PER_10S_MS);
        if (w > EXPANDER_WORST_COST_PER_10S_MS) std::printf("  %s: %u ms in ten seconds\n", k.name, (unsigned)w);
    }
    if (std::getenv("EXPANDER_PRINT_COST")) std::printf("worst cost in any ten seconds: %u ms\n", (unsigned)overall);
    // the half-failing bus that used to cost 7,000 ms in 10,000 is now called down
    FakeChip c; Sink s;
    railsAllPresent(c);
    PatternBus b(c);
    Expander e(b, s);
    b.mode = 99; e.start(0); b.mode = 1; b.now = 1;
    while (b.now < 20000) { e.noteSensorAnswered(b.now); e.service(b.now); b.now += 2; }
    CHECK(e.counters().lost >= 1);
}

// ─── the 49.7 day boundary ────────────────────────────────────────────────────────────────────
static void testNothingBreaksAcrossTheMillisWrap() {
    const uint32_t nearWrap = 0xFFFFFFFFu - 5000u;
    // polling goes on at the same rate across the wrap
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        e.start(nearWrap);
        uint32_t t = nearWrap + 1;
        int before = c.transactions;
        for (int k = 0; k < 2000; k++) { e.noteSensorAnswered(t); e.service(t); t += 5; }        // 10 s across the wrap
        int used = c.transactions - before;
        CHECK(t < 6000 && used >= 505 && used <= 515);
        CHECK(e.railHealth(RAIL_AUX) == HS_OK);
        // a rail drop just after the wrap is found in 500 ms and its since is the onset
        uint32_t drop = t;
        setRail(c, RAIL_AUX, false);
        uint32_t seen = 0;
        for (int k = 0; k < 300; k++) { e.noteSensorAnswered(t); e.service(t); if (!seen && e.railHealth(RAIL_AUX) == HS_MISSING) seen = t; t += 5; }
        CHECK(seen - drop >= 500 && seen - drop <= 540 && e.railSince(RAIL_AUX) - drop <= EXPANDER_POLL_MS);
    }
    // a reset across the wrap is found by the read-back within a second or so
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        uint32_t t0 = 0xFFFFFFFFu - 600u;
        e.start(t0);
        uint32_t t = t0 + 1;
        for (int k = 0; k < 100; k++) { e.service(t); t += 5; }   // 500 ms, wrap not yet reached
        c.reset();
        for (int k = 0; k < 300; k++) { e.service(t); t += 5; }   // across the wrap
        CHECK(e.counters().reconfigured == 1 && c.r[REG_GPPUA] == 0x70);
        // and a second one entirely after it
        c.reset();
        for (int k = 0; k < 300; k++) { e.service(t); t += 5; }
        CHECK(e.counters().reconfigured == 2);
    }
    // the retry schedule across the wrap is 1, 2, 4 and 8 s
    {
        FakeChip c; Sink s; Expander e(c, s);
        c.answering = false;
        uint32_t u = 0xFFFFFFFFu - 1500u;
        e.start(u);
        int tries = 0; int last = c.transactions;
        for (int k = 0; k < 4000; k++) { e.service(u); if (c.transactions != last) { tries++; last = c.transactions; } u += 5; }
        CHECK(tries == 4);
    }
    // the debounce, the failure window and the long press all use differences
    {
        FakeChip c; Sink s; Expander e(c, s);
        railsAllPresent(c);
        uint32_t t0 = 0xFFFFFFFFu - 2000u;
        e.start(t0);
        uint32_t t = t0 + 1;
        for (int k = 0; k < 400; k++) { e.service(t); t += 5; }
        setPin(c, 8, false);
        for (int k = 0; k < 1200; k++) { e.noteSensorAnswered(t); e.service(t); t += 5; }
        CHECK(e.buttonDown() && e.takePress());
        // three failures spread across the wrap are a loss
        for (int j = 0; j < 3; j++) { c.failNext = 1; for (int k = 0; k < 140; k++) { e.service(t); t += 5; } }
        CHECK(e.state() == EXS_DOWN);
    }
}

// ─── the button comes back disarmed ───────────────────────────────────────────────────────────
static void testButtonMustBeReleasedAgainAfterARecovery() {
    FakeChip c; Sink s; Expander e(c, s);
    railsAllPresent(c);
    e.start(0);
    uint32_t t = run(e, 1, 300);
    setPin(c, 8, false);
    t = run(e, t, 200);
    CHECK(e.buttonDown() && e.takePress());
    // the chip stops answering with the button still held, then comes back with it still held
    c.answering = false;
    t = run(e, t, 4000);
    CHECK(e.state() == EXS_DOWN && !e.buttonDown());
    c.answering = true; c.reset();
    t = run(e, t, 40000);
    CHECK(e.state() == EXS_RUNNING);
    // held from before the loss: not a press and not a long press, however long it goes on
    CHECK(!e.buttonDown() && !e.takePress() && !e.takeLongPress());
    // released and pressed again works
    setPin(c, 8, true);
    t = run(e, t, 300);
    setPin(c, 8, false);
    t = run(e, t, 6000);
    CHECK(e.takePress() && e.takeLongPress());
}

// ─── the long-press window ────────────────────────────────────────────────────────────────────
static void testLongPressWindowIsTiedToPowerUp() {
    bool closed = false;
    CHECK(buttonClearAllowed(true, 1000, &closed));
    CHECK(buttonClearAllowed(true, PROVISION_CLEAR_WINDOW_MS, &closed));
    CHECK(!buttonClearAllowed(true, PROVISION_CLEAR_WINDOW_MS + 1, &closed));
    // once closed it stays closed, so the 49.7 day alias cannot reopen it
    CHECK(!buttonClearAllowed(true, 1000, &closed));
    // a warm reset (a brown-out or a watchdog) never opens it
    bool closed2 = false;
    CHECK(!buttonClearAllowed(false, 1000, &closed2) && closed2);
    CHECK(!buttonClearAllowed(false, 0, &closed2));
    // esp32.ino calls it with the power-up reset reason and nothing there clears credentials without it
    std::string ino = slurp("../esp32.ino");
    CHECK(!ino.empty());
    CHECK(ino.find("mcp::buttonClearAllowed(coldPowerUp, now, &windowClosed)") != std::string::npos);
    CHECK(ino.find("esp_reset_reason() == ESP_RST_POWERON") != std::string::npos);
    CHECK(ino.find("if (!allowed) {") != std::string::npos);
}

int main() {
    testPinTableMatchesFixture();
    testReadmeHasTheBands();
    testBands();
    testStartSequence();
    testStartInEitherAddressingMode();
    testReadBackRefusesAChangedRegister();
    testPresentBoardDoesNothing();
    testPollRateAndTraffic();
    testButtonDebounce();
    testLongPress();
    testButtonStuckAtStartIsIgnored();
    testLongHoldOverALongBlockIsNotCreditedInFull();
    testRailPolarityFollowsTheTable();
    testStartStatesAreNotMistakenForTheOtherSense();
    testAbsentSinceIsTheFirstRawEdgeForAnInvertedInput();
    testBrownOutReportsNothingAboutRailsWhileReconfiguring();
    testRailAbsentAndBack();
    testRailAbsentAtBootAndAllSevenNamed();
    testRailInTheUndefinedBandCannotFlap();
    testSpareAndPortSevenBitsAreNeverRead();
    testNotAnsweringAtStart();
    testStopsAnsweringLater();
    testAFailedReadIsOnlyCounted();
    testStuckBus();
    testARefusedAddressIsNotAStuckBus();
    testFailuresInsideTheWindowAreNotOnlyConsecutive();
    testCallsNeverMakeMoreThanTwoFailedTransfers();
    testTransfersPerCall();
    testChipResetMidRun();
    testNoRailIsUpWithoutAFreshReading();
    testSensRailNeedsASensorToBeCalledPresent();
    testSensRailReturnIsJudgedOnThePollsAndNeverBlocks();
    testFlagRegistersAreLive();
    testAFailedReadDoesNotCountTowardsAChange();
    testWorstCostToTheLoopInAnyTenSeconds();
    testNothingBreaksAcrossTheMillisWrap();
    testButtonMustBeReleasedAgainAfterARecovery();
    testLongPressWindowIsTiedToPowerUp();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
