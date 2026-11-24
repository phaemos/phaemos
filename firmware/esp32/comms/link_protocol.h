// link_protocol.h - the hub side of the serial link format shared with the Nano and the
// Black Pill. plain C++ with no Arduino types, like sensors/health.cpp, so the host test in
// test_host/ covers all of it. comms/serial_parser.cpp is the thin caller that moves bytes.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "../sensors/health.h"

enum LinkKind : uint8_t {
    LINK_NANO = 0,
    LINK_STM32 = 1
};

// a line is at most this many bytes including CR LF.
#define LINK_LINE_MAX 160

// CRC-16/CCITT-FALSE: polynomial 0x1021, start 0xFFFF, no reflection, no final XOR.
// the check value for the ASCII string 123456789 is 0x29B1.
uint16_t crc16ccitt(const uint8_t* data, size_t len);

// ─── line assembly ───────────────────────────────────────────────────────────
enum LineEvent : uint8_t {
    LE_NONE,
    LE_LINE,      // a full line is in the buffer
    LE_OVERLONG   // the line ran past LINK_LINE_MAX. it is reported again for every further
                  // LINK_LINE_MAX bytes thrown away, so a stream with no line end (wrong baud
                  // rate) keeps counting as failures
};

struct LineBuf {
    char     data[LINK_LINE_MAX + 1];
    uint16_t len;
    bool     overflow;
    uint16_t skipped;   // bytes thrown away since the last overlong report
};

void      lineReset(LineBuf* b);
// feeds one byte. zero bytes are dropped because a framing error reads as one. the buffer
// never holds more than LINK_LINE_MAX bytes, whatever arrives.
LineEvent lineFeed(LineBuf* b, uint8_t c);

// ─── readings ────────────────────────────────────────────────────────────────
struct NanoReading {
    float    temp, hum, pres;   // -1 means the Nano has no value
    float    light, moist;
    bool     water;
    uint16_t st;                // status bits, 0 for an old-format line
    uint16_t vccMv;             // 0 for an old-format line
    uint32_t up;
    bool     checksummed;       // the line carried a checksum, so ST (and not the value -1)
                                // says whether a value is usable
};

struct Stm32Reading {
    float    vib[3];
    float    mag;
    float    fft;
    float    rms[3];
    float    pk;
    uint16_t st;
    uint32_t up;
    uint32_t mt, rf, br;
    bool     hasVib;            // the three axes were in the line
    bool     extended;          // RMS and PK were in the line
};

// Nano status bits
enum NanoBit : uint16_t {
    NANO_BME_MISSING  = 1,
    NANO_BME_STUCK    = 2,
    NANO_BME_ASLEEP   = 4,
    NANO_SUPPLY_RANGE = 8,
    NANO_RESET_WDT    = 16,
    NANO_RESET_BROWN  = 32,
    NANO_BME_RANGE    = 64
};
// Black Pill status bits
enum Stm32Bit : uint16_t {
    STM_SENSOR_MISSING = 1,
    STM_SENSOR_STUCK   = 2,
    STM_CLIPPING       = 4,
    STM_ID_MISMATCH    = 8,
    STM_RESET_WDT      = 16,
    STM_WINDOW_DROPPED = 32,
    STM_RESET_BROWN    = 64,
    STM_NO_DATA        = 128
};

// status bits to the hub's fault states. a reset bit is information and not a fault.
// CLIPPING is a reading and not a fault: the readings are forwarded and vib_clipping says so.
// NO_DATA (no complete window) is intermittent.
HealthState nanoBmeState(uint16_t st);
HealthState nanoSupplyState(uint16_t st);
HealthState stm32MpuState(uint16_t st);
bool        stm32Clipping(uint16_t st);

// ─── link quality over the last minute ───────────────────────────────────────
// twelve buckets of five seconds. good counts accepted lines and bad counts lines that failed
// a check plus lines lost to a sequence gap, so the sum is the lines that were expected.
#define LINK_RATE_BUCKETS   12
#define LINK_RATE_BUCKET_MS 5000UL

struct RateWindow {
    uint16_t good[LINK_RATE_BUCKETS];
    uint16_t bad[LINK_RATE_BUCKETS];
    uint8_t  head;
    uint32_t headStartMs;
};

void rwInit(RateWindow* w, uint32_t nowMs);
void rwAdd(RateWindow* w, uint32_t nowMs, uint16_t good, uint16_t bad);
void rwTotals(RateWindow* w, uint32_t nowMs, uint32_t* good, uint32_t* bad);
// more than a fifth of the expected lines were lost or failed, with at least minLines expected.
bool rwLossy(RateWindow* w, uint32_t nowMs, uint32_t minLines);

// ─── per link state ──────────────────────────────────────────────────────────
struct LinkStats {
    uint32_t good;       // data lines accepted
    uint32_t crc;        // lines refused for a wrong, short, lower-case or missing checksum
    uint32_t format;     // lines with a good checksum that did not parse
    uint32_t overlong;   // lines past the length limit
    uint32_t gaps;       // sequence jumps
    uint32_t restarts;   // satellite restarts
    uint32_t pingsSent;
    uint32_t pongsRcvd;
};

enum Outcome : uint8_t {
    OUT_NONE,       // no line completed
    OUT_GOOD,       // a data line was accepted
    OUT_PONG,       // a pong for the outstanding ping
    OUT_REJECTED,   // counted and dropped
    OUT_IGNORED     // blank line or a stale pong, not counted
};

struct LinkCore {
    LinkKind  kind;
    LineBuf   buf;
    LinkStats stats;
    LinkWatch watch;            // line level, last byte and last valid line

    bool      sawChecksum;      // a checksummed line has passed since boot
    bool      seenSincePower;   // one has passed on this link since power-up. the caller keeps
                                // that in memory that survives a warm reset
    RateWindow rate;
    uint16_t  prevSt;           // status bits of the previous line, for the two-in-a-row rule
    uint16_t  stStable;         // bits set on this line and the one before it
    uint16_t  partHist[2];      // per part, the last ten lines: bit 0 is this line, set when the part had a status bit
    bool      haveSeq;
    uint16_t  lastSeq;
    uint32_t  lastUp;

    bool         hasReading;
    NanoReading  nano;
    Stm32Reading stm;

    // the three most recent failures, for the garbage rule
    uint32_t  failTimes[3];
    uint8_t   failCount;
    uint8_t   failIdx;

    // ping bookkeeping
    uint32_t  lastPingMs;
    uint16_t  nextPing;
    uint16_t  outstandingN;
    bool      pingOutstanding;
    uint8_t   missed;           // earlier pings that never got a pong

    // silent and garbage stay latched until a new valid line, so a millis() rollover
    // cannot turn a dead link back into a live one
    HealthState latched;
};

// a sequence number that goes back by itself with a small UP is a satellite restart.
#define LINK_RESTART_SEQ_MAX 10
#define LINK_RESTART_UP_MAX  30

// seenSincePower is true when this link has already delivered a checksummed line since the
// power came on (kept across warm resets). the old format is then refused from the start.
void lcInit(LinkCore* c, LinkKind kind, uint32_t nowMs, bool seenSincePower = false);
// the old format is accepted only while no checksummed line has been seen since power-up.
bool lcLegacyOpen(const LinkCore* c);
// lines that failed to parse or ran too long, which feed the garbage rule beside the checksum errors.
uint32_t lcParseFailures(const LinkCore* c);
// feeds one received byte and handles the line when it completes.
Outcome lcFeedByte(LinkCore* c, uint8_t byte, uint32_t nowMs);
// handles the line now held in the buffer. lcFeedByte calls this.
Outcome lcHandleLine(LinkCore* c, uint32_t nowMs);
// level of the receive pin, sampled on a steady cadence.
void lcNoteLevel(LinkCore* c, bool high, uint32_t nowMs);

// when a ping is due this fills `out` with "PING:<n>\n" and returns true. it never blocks.
bool lcPingDue(LinkCore* c, uint32_t nowMs, char* out, size_t cap);
// pings in a row that have had no pong, counting the outstanding one once its window passed.
uint8_t lcPingsUnanswered(const LinkCore* c, uint32_t nowMs);

// the link state, in this order: line_low, garbage, silent, one_way, intermittent, ok.
// garbage and silent are both a link with no valid line for LINK_SILENT_MS. it is garbage when
// bytes keep arriving and three lines failed in that time. otherwise it is silent. intermittent
// is more than a fifth of the lines lost or failed over the last minute. nothing is reported
// until the link has had LINK_SILENT_MS since lcInit. a link that is dead also drops its reading.
HealthState lcState(LinkCore* c, uint32_t nowMs);

// everything the health table needs from one link, judged together: the link itself and the
// parts behind it. for the Nano partA is nano_bme280 and partB is nano_supply. for the Black
// Pill partA is stm32_mpu6050 and partB is always ok. a satellite's status bits only count while
// its link still delivers lines. a bit also has to be set on two lines in a row.
struct LinkHealth {
    HealthState link;
    HealthState partA;
    HealthState partB;
};
LinkHealth lcHealth(LinkCore* c, uint32_t nowMs);

// a status bit set on three or more of the last ten lines (it comes and goes). the history is a ten
// bit shift register, bit 0 the newest line. a part whose bit is set on two lines in a row right now
// is in its debounced fault state and shows that instead, so the flapping is never reported late
// and never after it has stopped withholding values.
bool lcHistIntermittent(uint16_t hist);
// advances the one-minute rate window to now. lcState calls it, so the window moves on even while a
// link is dead.
void rwTick(RateWindow* w, uint32_t nowMs);
