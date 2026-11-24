// test_link.cpp - host test for the hub side of the serial link format: the CRC, the line
// assembly, both satellite parsers, the counters, the sequence and restart logic, the status
// bit mapping, the ping bookkeeping and the link states.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_link.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_link" && "${TMPDIR:-/tmp}/test_link"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_link.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_link_san" && "${TMPDIR:-/tmp}/test_link_san"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "../comms/link_protocol.h"
#include "../config.h"

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

// the example lines from the contract, with the checksums it gives.
static const char* NANO_BODY =
    "TEMP:25.1,HUM:50.7,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:0,SEQ:12,UP:26,VCC:4980";
static const char* BP_BODY =
    "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,"
    "ST:0,SEQ:7,UP:9,MT:0,RF:0,BR:0";

static std::string withCrc(const std::string& body) {
    char tail[16];
    std::snprintf(tail, sizeof tail, "*%04X\r\n",
                  (unsigned)crc16ccitt((const uint8_t*)body.data(), body.size()));
    return body + tail;
}

static std::string nanoBody(unsigned st, unsigned seq, unsigned up, unsigned vcc = 4980) {
    char b[200];
    std::snprintf(b, sizeof b,
                  "TEMP:25.1,HUM:50.7,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:%u,SEQ:%u,UP:%u,VCC:%u",
                  st, seq, up, vcc);
    return b;
}

static std::string bpBody(unsigned st, unsigned seq, unsigned up) {
    char b[220];
    std::snprintf(b, sizeof b,
                  "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,"
                  "ST:%u,SEQ:%u,UP:%u,MT:0,RF:0,BR:0", st, seq, up);
    return b;
}

// feeds a whole string and returns the last outcome that was not NONE.
static Outcome feed(LinkCore& c, const std::string& s, uint32_t now) {
    Outcome last = OUT_NONE;
    for (char ch : s) {
        Outcome o = lcFeedByte(&c, (uint8_t)ch, now);
        if (o != OUT_NONE) last = o;
    }
    return last;
}

static void testCrc() {
    CHECK(crc16ccitt((const uint8_t*)"123456789", 9) == 0x29B1);
    CHECK(crc16ccitt((const uint8_t*)"", 0) == 0xFFFF);
    // the checksums printed in the contract
    CHECK(crc16ccitt((const uint8_t*)NANO_BODY, std::strlen(NANO_BODY)) == 0xF6B1);
    CHECK(crc16ccitt((const uint8_t*)BP_BODY, std::strlen(BP_BODY)) == 0xAD94);
    CHECK(crc16ccitt((const uint8_t*)"PONG:5", 6) == 0xD246);
}

static void testNanoGoodLine() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    CHECK(feed(c, std::string(NANO_BODY) + "*F6B1\r\n", 1000) == OUT_GOOD);
    CHECK(c.stats.good == 1 && c.stats.crc == 0 && c.stats.format == 0);
    CHECK(c.hasReading && c.sawChecksum);
    CHECK(std::fabs(c.nano.temp - 25.1f) < 1e-4f);
    CHECK(std::fabs(c.nano.hum - 50.7f) < 1e-4f);
    CHECK(std::fabs(c.nano.pres - 1006.6f) < 1e-3f);
    CHECK(c.nano.light == 300.0f && c.nano.moist == 700.0f && !c.nano.water);
    CHECK(c.nano.st == 0 && c.nano.up == 26 && c.nano.vccMv == 4980);
    // a line ending in a bare line feed is fine too
    std::string bare = withCrc(nanoBody(0, 13, 28));
    bare.erase(bare.size() - 2, 1);        // drop the CR, leaving a bare line feed
    CHECK(feed(c, bare, 3000) == OUT_GOOD);
    CHECK(c.stats.good == 2);
}

static void testBlackPillGoodLine() {
    LinkCore c;
    lcInit(&c, LINK_STM32, 0);
    CHECK(feed(c, std::string(BP_BODY) + "*AD94\r\n", 1000) == OUT_GOOD);
    CHECK(c.stats.good == 1);
    const Stm32Reading& s = c.stm;
    CHECK(s.hasVib && s.extended);
    CHECK(std::fabs(s.vib[0] - 0.02f) < 1e-5f && std::fabs(s.vib[1] + 0.01f) < 1e-5f &&
          std::fabs(s.vib[2] - 1.01f) < 1e-5f);
    CHECK(std::fabs(s.mag - 1.01f) < 1e-5f && std::fabs(s.fft - 12.5f) < 1e-5f);
    CHECK(std::fabs(s.rms[0] - 0.012f) < 1e-5f && std::fabs(s.rms[1] - 0.010f) < 1e-5f &&
          std::fabs(s.rms[2] - 0.031f) < 1e-5f);
    CHECK(std::fabs(s.pk - 0.094f) < 1e-5f);
    CHECK(s.st == 0 && s.up == 9 && s.mt == 0 && s.rf == 0 && s.br == 0);
}

static void testCorruptLines() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    CHECK(feed(c, withCrc(NANO_BODY), 1000) == OUT_GOOD);
    float t = c.nano.temp;

    // one changed character: the checksum no longer matches
    std::string bad = withCrc(NANO_BODY);
    bad[5] = '9';
    CHECK(feed(c, bad, 1100) == OUT_REJECTED);
    CHECK(c.stats.crc == 1 && c.stats.good == 1 && c.nano.temp == t);

    // a truncated line (the end is cut, so no checksum) after the first checksummed line
    CHECK(feed(c, std::string(NANO_BODY).substr(0, 60) + "\r\n", 1200) == OUT_REJECTED);
    CHECK(c.stats.crc == 2);
    // the whole body with no checksum is also refused now
    CHECK(feed(c, std::string(NANO_BODY) + "\r\n", 1300) == OUT_REJECTED);
    CHECK(c.stats.crc == 3);

    // a star with a short checksum
    CHECK(feed(c, std::string(NANO_BODY) + "*F6B\r\n", 1400) == OUT_REJECTED);
    CHECK(c.stats.crc == 4);
    CHECK(feed(c, std::string(NANO_BODY) + "*\r\n", 1500) == OUT_REJECTED);
    CHECK(c.stats.crc == 5);
    // a star with a checksum that is too long
    CHECK(feed(c, std::string(NANO_BODY) + "*F6B1A\r\n", 1600) == OUT_REJECTED);
    CHECK(c.stats.crc == 6);
    // lower-case hex is refused even though the value is right
    CHECK(feed(c, std::string(NANO_BODY) + "*f6b1\r\n", 1700) == OUT_REJECTED);
    CHECK(c.stats.crc == 7);
    // a non-hex checksum
    CHECK(feed(c, std::string(NANO_BODY) + "*F6BG\r\n", 1800) == OUT_REJECTED);
    CHECK(c.stats.crc == 8);
    // two stars
    CHECK(feed(c, std::string(NANO_BODY) + "*F6B1*F6B1\r\n", 1900) == OUT_REJECTED);
    CHECK(c.stats.crc == 9);

    // none of that touched the good count or the stored reading
    CHECK(c.stats.good == 1 && c.nano.temp == t);
    // a good line is still taken afterwards
    CHECK(feed(c, withCrc(nanoBody(0, 13, 28)), 2000) == OUT_GOOD);
    CHECK(c.stats.good == 2);
}

static void testFormatErrors() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    // a good checksum over a body that does not parse is a format error, not a checksum error
    CHECK(feed(c, withCrc("TEMP:1"), 100) == OUT_REJECTED);
    CHECK(c.stats.format == 1 && c.stats.crc == 0);
    CHECK(feed(c, withCrc("TEMP:nan,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:0,ST:0,SEQ:0,UP:0,VCC:1"), 200) == OUT_REJECTED);
    CHECK(c.stats.format == 2);
    // a missing key on a checksummed line
    CHECK(feed(c, withCrc("TEMP:1,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:0,ST:0,SEQ:0,UP:0"), 300) == OUT_REJECTED);
    CHECK(c.stats.format == 3);
    // a SEQ over 65535
    CHECK(feed(c, withCrc(nanoBody(0, 70000, 1)), 400) == OUT_REJECTED);
    CHECK(c.stats.format == 4);
    // -1 is a legal value (no BME280)
    CHECK(feed(c, withCrc("TEMP:-1,HUM:-1,PRES:-1,LIGHT:1,MOIST:1,WATER:0,ST:1,SEQ:0,UP:0,VCC:4900"), 500) == OUT_GOOD);
    CHECK(c.nano.temp == -1.0f && c.nano.st == 1);

    LinkCore b;
    lcInit(&b, LINK_STM32, 0);
    std::string noHz = bpBody(0, 0, 0);
    size_t at = noHz.find("12.5Hz");
    noHz.replace(at, 6, "12.5Hzz");
    CHECK(feed(b, withCrc(noHz), 100) == OUT_REJECTED);
    CHECK(b.stats.format == 1);
    // a checksummed Black Pill line without the new keys
    CHECK(feed(b, withCrc("VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,ST:0,SEQ:0,UP:0"), 200) == OUT_REJECTED);
    CHECK(b.stats.format == 2);
}

static void testLegacyRule() {
    // old-format lines work until the first checksummed line from the link
    LinkCore n;
    lcInit(&n, LINK_NANO, 0);
    CHECK(feed(n, "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n", 100) == OUT_GOOD);
    CHECK(n.stats.good == 1 && !n.sawChecksum && n.nano.st == 0 && n.nano.vccMv == 0);
    CHECK(feed(n, "TEMP:28.6,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:1\n", 200) == OUT_GOOD);
    CHECK(n.nano.water);
    // the first checksummed line ends the old format
    CHECK(feed(n, withCrc(nanoBody(0, 0, 4)), 300) == OUT_GOOD);
    CHECK(n.sawChecksum);
    CHECK(feed(n, "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n", 400) == OUT_REJECTED);
    CHECK(n.stats.crc == 1 && n.stats.good == 3);

    LinkCore b;
    lcInit(&b, LINK_STM32, 0);
    CHECK(feed(b, "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz\r\n", 100) == OUT_GOOD);
    CHECK(b.stm.hasVib && !b.stm.extended);
    // the old format is strict now: a line without the three axes is refused
    CHECK(feed(b, "MAG:2.5,FFT_PEAK:4.0Hz\r\n", 200) == OUT_REJECTED);
    CHECK(b.stm.hasVib);
    CHECK(b.stats.format == 1);
    CHECK(feed(b, withCrc(bpBody(0, 0, 3)), 300) == OUT_GOOD);
    CHECK(feed(b, "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz\r\n", 400) == OUT_REJECTED);
    CHECK(b.stats.crc == 1);
}

static void testStatusBits() {
    // Nano
    CHECK(nanoBmeState(0) == HS_OK);
    CHECK(nanoBmeState(NANO_BME_MISSING) == HS_MISSING);
    CHECK(nanoBmeState(NANO_BME_STUCK) == HS_STUCK);
    CHECK(nanoBmeState(NANO_BME_ASLEEP) == HS_MISSING);
    CHECK(nanoBmeState(NANO_BME_RANGE) == HS_OUT_OF_RANGE);
    CHECK(nanoBmeState(NANO_SUPPLY_RANGE) == HS_OK);
    CHECK(nanoBmeState(NANO_RESET_WDT | NANO_RESET_BROWN) == HS_OK);
    CHECK(nanoSupplyState(NANO_SUPPLY_RANGE) == HS_OUT_OF_RANGE);
    CHECK(nanoSupplyState(NANO_BME_MISSING | NANO_RESET_BROWN) == HS_OK);
    // missing wins over the other BME bits
    CHECK(nanoBmeState(NANO_BME_MISSING | NANO_BME_RANGE) == HS_MISSING);
    CHECK(nanoBmeState(NANO_BME_STUCK | NANO_BME_RANGE) == HS_STUCK);
    // the bit values themselves
    CHECK(NANO_BME_MISSING == 1 && NANO_BME_STUCK == 2 && NANO_BME_ASLEEP == 4 &&
          NANO_SUPPLY_RANGE == 8 && NANO_RESET_WDT == 16 && NANO_RESET_BROWN == 32 &&
          NANO_BME_RANGE == 64);
    // Black Pill
    CHECK(stm32MpuState(0) == HS_OK);
    CHECK(stm32MpuState(STM_SENSOR_MISSING) == HS_MISSING);
    CHECK(stm32MpuState(STM_ID_MISMATCH) == HS_MISSING);
    CHECK(stm32MpuState(STM_SENSOR_STUCK) == HS_STUCK);
    // clipping is a reading and not a fault. no window is intermittent
    CHECK(stm32MpuState(STM_CLIPPING) == HS_OK);
    CHECK(stm32Clipping(STM_CLIPPING) && !stm32Clipping(STM_WINDOW_DROPPED) && !stm32Clipping(0));
    CHECK(stm32MpuState(STM_NO_DATA) == HS_INTERMITTENT);
    CHECK(stm32MpuState(STM_NO_DATA | STM_SENSOR_MISSING) == HS_MISSING);
    CHECK(stm32MpuState(STM_NO_DATA | STM_SENSOR_STUCK) == HS_STUCK);
    CHECK(STM_NO_DATA == 128);
    CHECK(stm32MpuState(STM_WINDOW_DROPPED) == HS_OK);
    CHECK(stm32MpuState(STM_RESET_WDT | STM_RESET_BROWN) == HS_OK);
    CHECK(stm32MpuState(STM_SENSOR_MISSING | STM_CLIPPING) == HS_MISSING);
    CHECK(stm32MpuState(STM_CLIPPING | STM_WINDOW_DROPPED) == HS_OK);
    CHECK(STM_SENSOR_MISSING == 1 && STM_SENSOR_STUCK == 2 && STM_CLIPPING == 4 &&
          STM_ID_MISMATCH == 8 && STM_RESET_WDT == 16 && STM_WINDOW_DROPPED == 32 &&
          STM_RESET_BROWN == 64);

    // and through the parser: the bits arrive in the reading
    LinkCore n;
    lcInit(&n, LINK_NANO, 0);
    CHECK(feed(n, withCrc(nanoBody(1 | 8 | 32, 0, 5)), 100) == OUT_GOOD);
    CHECK(nanoBmeState(n.nano.st) == HS_MISSING && nanoSupplyState(n.nano.st) == HS_OUT_OF_RANGE);
}

static void testSequence() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    // the first line after the hub boots may carry any number: no gap
    CHECK(feed(c, withCrc(nanoBody(0, 500, 1000)), 1000) == OUT_GOOD);
    CHECK(c.stats.gaps == 0 && c.stats.restarts == 0);
    CHECK(feed(c, withCrc(nanoBody(0, 501, 1002)), 3000) == OUT_GOOD);
    CHECK(c.stats.gaps == 0);
    // a jump of more than one is a gap
    CHECK(feed(c, withCrc(nanoBody(0, 504, 1008)), 5000) == OUT_GOOD);
    CHECK(c.stats.gaps == 1 && c.stats.restarts == 0);
    // a satellite restart: SEQ back to a small number with a small UP. not a gap
    CHECK(feed(c, withCrc(nanoBody(0, 0, 2)), 7000) == OUT_GOOD);
    CHECK(c.stats.gaps == 1 && c.stats.restarts == 1);
    CHECK(feed(c, withCrc(nanoBody(0, 1, 4)), 9000) == OUT_GOOD);
    CHECK(c.stats.gaps == 1 && c.stats.restarts == 1);
    // a restart seen late (the first lines were missed) still shows UP going backwards
    CHECK(feed(c, withCrc(nanoBody(0, 3000, 6000)), 11000) == OUT_GOOD);   // gap
    CHECK(c.stats.gaps == 2);
    CHECK(feed(c, withCrc(nanoBody(0, 40, 80)), 13000) == OUT_GOOD);        // UP went back
    CHECK(c.stats.restarts == 2 && c.stats.gaps == 2);
}

static void testSequenceWrap() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    CHECK(feed(c, withCrc(nanoBody(0, 65534, 130000)), 1000) == OUT_GOOD);
    CHECK(feed(c, withCrc(nanoBody(0, 65535, 130002)), 2000) == OUT_GOOD);
    // the wrap to zero with UP still rising is neither a gap nor a restart
    CHECK(feed(c, withCrc(nanoBody(0, 0, 130004)), 3000) == OUT_GOOD);
    CHECK(c.stats.gaps == 0 && c.stats.restarts == 0);
    CHECK(feed(c, withCrc(nanoBody(0, 1, 130006)), 4000) == OUT_GOOD);
    CHECK(c.stats.gaps == 0 && c.stats.restarts == 0);
    // a gap across the wrap
    CHECK(feed(c, withCrc(nanoBody(0, 3, 130010)), 5000) == OUT_GOOD);
    CHECK(c.stats.gaps == 1);
}

static void testDroppedWindowIsNotAGap() {
    // the Black Pill sends no line for a window dropped by one failed read. SEQ counts lines
    // sent, so the numbers stay consecutive while UP jumps. the next line carries the bit.
    LinkCore c;
    lcInit(&c, LINK_STM32, 0);
    CHECK(feed(c, withCrc(bpBody(0, 7, 9)), 1000) == OUT_GOOD);
    CHECK(feed(c, withCrc(bpBody(STM_WINDOW_DROPPED, 8, 13)), 5000) == OUT_GOOD);
    CHECK(c.stats.gaps == 0 && c.stats.restarts == 0);
    CHECK(c.stm.st == STM_WINDOW_DROPPED);
    CHECK(stm32MpuState(c.stm.st) == HS_OK);
}

static void testLineLimit() {
    // a line of exactly 160 bytes including CR LF is accepted
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    std::string body = nanoBody(0, 0, 1);
    body += ",X:";
    size_t want = 160 - 7;                  // minus the star, four digits and CR LF
    while (body.size() < want) body += 'a';
    std::string line = withCrc(body);
    CHECK(line.size() == 160);
    CHECK(feed(c, line, 100) == OUT_GOOD);
    CHECK(c.stats.overlong == 0);

    // 161 bytes is refused and counted once
    std::string body2 = body + "a";
    std::string line2 = withCrc(body2);
    CHECK(line2.size() == 161);
    CHECK(feed(c, line2, 200) == OUT_REJECTED);
    CHECK(c.stats.overlong == 1 && c.stats.good == 1);
    // and the next good line is taken, so the stream recovers
    CHECK(feed(c, withCrc(nanoBody(0, 1, 3)), 300) == OUT_GOOD);
    CHECK(c.stats.good == 2);
}

static void testOverlongWithoutLineEnd() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    // ten thousand bytes with no line end must not grow the buffer or crash
    uint32_t rejected = 0;
    for (int i = 0; i < 10000; i++) {
        if (lcFeedByte(&c, 'A', 1000 + i) == OUT_REJECTED) rejected++;
    }
    // the first overflow is one failure and then one more for every further 159 bytes, so a
    // stream with no line end (wrong baud rate) keeps counting
    CHECK(rejected >= 60 && rejected <= 64);
    CHECK(c.buf.len <= LINK_LINE_MAX);
    CHECK(c.stats.overlong == rejected);
    CHECK(c.stats.good == 0);
    // the line end closes it and the next line is clean
    CHECK(lcFeedByte(&c, '\n', 20000) == OUT_NONE);
    CHECK(c.buf.len == 0 && !c.buf.overflow);
    CHECK(feed(c, withCrc(nanoBody(0, 0, 1)), 20100) == OUT_GOOD);
}

static void testNoiseBytes() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    // a zero byte (a framing error) is not data
    uint32_t before = c.watch.lastByteMs;
    CHECK(lcFeedByte(&c, 0, 5000) == OUT_NONE);
    CHECK(c.watch.lastByteMs == before);
    // a blank line is ignored without a count
    CHECK(feed(c, "\r\n", 5100) == OUT_IGNORED);
    CHECK(feed(c, "\n", 5200) == OUT_IGNORED);
    CHECK(c.stats.crc == 0 && c.stats.format == 0 && c.failCount == 0);
    CHECK(c.watch.lastByteMs == before);
}

static void testPing() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    char out[16];
    CHECK(!lcPingDue(&c, 29999, out, sizeof out));
    CHECK(lcPingDue(&c, 30000, out, sizeof out));
    CHECK(std::strcmp(out, "PING:0\n") == 0);
    CHECK(c.stats.pingsSent == 1);
    CHECK(!lcPingDue(&c, 30001, out, sizeof out));
    // a pong for the right number
    CHECK(feed(c, withCrc("PONG:0"), 30100) == OUT_PONG);
    CHECK(c.stats.pongsRcvd == 1 && lcPingsUnanswered(&c, 30700) == 0);
    CHECK(c.sawChecksum);
    CHECK(lcPingDue(&c, 60000, out, sizeof out));
    CHECK(std::strcmp(out, "PING:1\n") == 0);
    // a pong for the wrong number is ignored
    CHECK(feed(c, withCrc("PONG:7"), 60100) == OUT_IGNORED);
    CHECK(c.stats.pongsRcvd == 1);
    // a pong with a wrong checksum is an error
    CHECK(feed(c, "PONG:1*0000\r\n", 60200) == OUT_REJECTED);
    CHECK(c.stats.crc == 1);
    // the same pong twice counts once
    CHECK(feed(c, withCrc("PONG:1"), 60300) == OUT_PONG);
    CHECK(feed(c, withCrc("PONG:1"), 60400) == OUT_IGNORED);
    CHECK(c.stats.pongsRcvd == 2);
    // the number wraps after 65535
    c.nextPing = 65535;
    CHECK(lcPingDue(&c, 90000, out, sizeof out));
    CHECK(std::strcmp(out, "PING:65535\n") == 0);
    CHECK(lcPingDue(&c, 120000, out, sizeof out));
    CHECK(std::strcmp(out, "PING:0\n") == 0);
}

// keeps the link alive with a checksummed line every 2 s and a pong policy
static void runLink(LinkCore& c, uint32_t from, uint32_t to, bool answerPings, unsigned* seq) {
    char out[16];
    for (uint32_t t = from; t <= to; t += 500) {
        if (t % 2000 == 0) {
            feed(c, withCrc(nanoBody(0, *seq, t / 1000)), t);
            (*seq)++;
        }
        if (lcPingDue(&c, t, out, sizeof out) && answerPings) {
            unsigned n = (unsigned)std::atoi(out + 5);
            char pong[24];
            std::snprintf(pong, sizeof pong, "PONG:%u", n);
            feed(c, withCrc(pong), t + 100);
        }
    }
}

static void testOneWay() {
    // data keeps arriving but nothing ever answers the pings
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    unsigned seq = 0;
    runLink(c, 0, 29500, false, &seq);
    runLink(c, 30000, 60500, false, &seq);      // pings 0 and 1 sent, two unanswered
    CHECK(lcPingsUnanswered(&c, 60500) == 2);
    CHECK(lcState(&c, 60500) == HS_OK);
    runLink(c, 61000, 90000, false, &seq);      // the third ping goes out at 90000
    CHECK(lcState(&c, 90000) == HS_OK);         // its window has not passed yet
    runLink(c, 90500, 91000, false, &seq);
    CHECK(lcPingsUnanswered(&c, 90600) == 3);
    CHECK(lcState(&c, 90600) == HS_ONE_WAY);
    // a pong clears it
    CHECK(feed(c, withCrc("PONG:2"), 91000) == OUT_PONG);
    CHECK(lcState(&c, 91000) == HS_OK);

    // the same link with answers never goes one_way
    LinkCore d;
    lcInit(&d, LINK_NANO, 0);
    seq = 0;
    runLink(d, 0, 200000, true, &seq);
    CHECK(lcState(&d, 200000) == HS_OK);
    CHECK(d.stats.pingsSent == d.stats.pongsRcvd || d.stats.pingsSent == d.stats.pongsRcvd + 1);

    // an old-format satellite never answers and must not be called one_way
    LinkCore e;
    lcInit(&e, LINK_NANO, 0);
    char out[16];
    for (uint32_t t = 0; t <= 200000; t += 500) {
        if (t % 2000 == 0) feed(e, "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n", t);
        lcPingDue(&e, t, out, sizeof out);
    }
    CHECK(e.stats.pingsSent >= 6);
    CHECK(lcState(&e, 200000) == HS_OK);
}

static void testLinkStates() {
    // nothing is reported inside the start-up window, whatever happened
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    for (int i = 0; i < 5; i++) feed(c, withCrc("TEMP:1"), 1000 + i * 100);
    CHECK(lcState(&c, 14999) == HS_OK);
    // bytes keep arriving and lines keep failing, with no good line: garbage
    for (uint32_t t = 15000; t <= 21000; t += 2000) {
        std::string bad = withCrc(nanoBody(0, 1, 1));
        bad[3] = 'Z';
        feed(c, bad, t);
    }
    CHECK(c.failCount == 3);
    CHECK(lcState(&c, 21000) == HS_GARBAGE);
    // a good line ends it at once
    CHECK(feed(c, withCrc(nanoBody(0, 2, 22)), 22000) == OUT_GOOD);
    // it is no longer garbage, but nine of ten lines in the last minute failed
    CHECK(lcState(&c, 22000) == HS_INTERMITTENT);
    // and a minute of good lines clears that too
    for (uint32_t t = 24000; t <= 90000; t += 2000) {
        feed(c, withCrc(nanoBody(0, (unsigned)(3 + (t - 24000) / 2000), 24 + (unsigned)((t - 24000) / 1000))), t);
    }
    CHECK(lcState(&c, 90000) == HS_OK);

    // no bytes at all: silent
    LinkCore s;
    lcInit(&s, LINK_NANO, 0);
    CHECK(lcState(&s, 14999) == HS_OK);
    CHECK(lcState(&s, 15000) == HS_SILENT);

    // two failed lines are not garbage
    LinkCore two;
    lcInit(&two, LINK_NANO, 0);
    feed(two, withCrc("TEMP:1"), 16000);
    feed(two, withCrc("TEMP:1"), 18000);
    CHECK(lcState(&two, 20000) == HS_SILENT);

    // failures older than the window do not count
    LinkCore old;
    lcInit(&old, LINK_NANO, 0);
    feed(old, withCrc("TEMP:1"), 1000);
    feed(old, withCrc("TEMP:1"), 2000);
    feed(old, withCrc("TEMP:1"), 3000);
    lcFeedByte(&old, 'x', 19000);   // a stray byte only
    CHECK(lcState(&old, 20000) == HS_SILENT);

    // line_low outranks silent and garbage
    LinkCore low;
    lcInit(&low, LINK_NANO, 0);
    feed(low, withCrc("TEMP:1"), 100);
    feed(low, withCrc("TEMP:1"), 200);
    feed(low, withCrc("TEMP:1"), 300);
    for (uint32_t t = 10000; t <= 16000; t += SERIAL_POLL_MS) lcNoteLevel(&low, false, t);
    CHECK(lcState(&low, 16000) == HS_LINE_LOW);
    // the reading is dropped with the link
    CHECK(!low.hasReading);
}

static void testSilentLatchAcrossRollover() {
    // a link that has been silent since boot must stay silent when millis() wraps
    uint32_t boot = 100;
    LinkCore c;
    lcInit(&c, LINK_STM32, boot);
    CHECK(feed(c, "VIB:0.1,0.2,1.0,MAG:1.0,FFT_PEAK:2.0Hz\r\n", boot + 1000) == OUT_GOOD);
    CHECK(c.hasReading);
    CHECK(lcState(&c, boot + 17000) == HS_SILENT);
    CHECK(!c.hasReading);
    // 49.7 days on, now has wrapped to just after the boot value
    uint32_t wrapped = boot + 99;
    CHECK(lcState(&c, wrapped) == HS_SILENT);
    CHECK(lcState(&c, wrapped + 20000) == HS_SILENT);
    // a new valid line brings it back
    CHECK(feed(c, "VIB:0.1,0.2,1.0,MAG:1.0,FFT_PEAK:2.0Hz\r\n", wrapped + 20100) == OUT_GOOD);
    CHECK(lcState(&c, wrapped + 20200) == HS_OK);
    CHECK(c.hasReading);
}


static void testStrictLegacy() {
    // the old format, strictly: keys in order, nothing after the last one, plain numbers
    const char* good = "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n";
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    CHECK(feed(c, good, 100) == OUT_GOOD);
    const char* bad[] = {
        "HUM:55.2,TEMP:28.5,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n",   // wrong order
        "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0,ST:0\r\n", // extra key
        "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210\r\n",           // key missing
        "TEMP:+28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n",  // plus sign
        "TEMP:2.85e1,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n", // exponent
        "TEMP:28.,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n",    // no digit after the point
        "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:2\r\n",   // water is 0 or 1
        "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0.5\r\n",
        "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0,\r\n",  // trailing comma
        "TEMP:28.5,,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0\r\n",  // empty token
    };
    for (const char* b : bad) {
        LinkCore d;
        lcInit(&d, LINK_NANO, 0);
        CHECK(feed(d, b, 100) == OUT_REJECTED);
        CHECK(d.stats.good == 0);
    }
    // the Black Pill, strictly
    LinkCore s;
    lcInit(&s, LINK_STM32, 0);
    CHECK(feed(s, "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz\r\n", 100) == OUT_GOOD);
    const char* badS[] = {
        "VIB:0.02,-0.01,MAG:1.01,FFT_PEAK:12.5Hz\r\n",                    // two axes
        "MAG:1.01,VIB:0.02,-0.01,1.01,FFT_PEAK:12.5Hz\r\n",               // wrong order
        "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5\r\n",                 // unit missing
        "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,ST:0\r\n",          // extra key
    };
    for (const char* b : badS) {
        LinkCore d;
        lcInit(&d, LINK_STM32, 0);
        CHECK(feed(d, b, 100) == OUT_REJECTED);
    }
    // the window is closed for good by the first checksummed line and from the start when
    // the link has already delivered one since power-up (kept in RTC memory across a warm reset)
    LinkCore e;
    lcInit(&e, LINK_NANO, 0, true);
    CHECK(!lcLegacyOpen(&e));
    CHECK(feed(e, good, 100) == OUT_REJECTED);
    CHECK(e.stats.crc == 1);
    CHECK(feed(e, withCrc(nanoBody(0, 0, 4)), 200) == OUT_GOOD);
    LinkCore f;
    lcInit(&f, LINK_NANO, 0, false);
    CHECK(lcLegacyOpen(&f));
    CHECK(feed(f, withCrc(nanoBody(0, 0, 4)), 100) == OUT_GOOD);
    CHECK(!lcLegacyOpen(&f) && f.seenSincePower);
}

static void testLegacySingleBitErrors() {
    // every single bit error of a checksummed line, with the window still open: none may be
    // accepted. a check found 8 of 720 passing as old-format lines with ST, UP and VCC
    // silently zero.
    std::string base = withCrc(NANO_BODY);
    base.resize(base.size() - 2);
    int accepted = 0, total = 0;
    for (size_t i = 0; i < base.size() * 8; i++) {
        std::string m = base;
        m[i / 8] ^= (char)(1 << (i % 8));
        LinkCore c;
        lcInit(&c, LINK_NANO, 0);
        uint32_t g = c.stats.good;
        feed(c, m + "\r\n", 1);
        total++;
        if (c.stats.good > g) accepted++;
    }
    CHECK(total == 720);
    CHECK(accepted == 0);
    // and for the Black Pill example
    std::string b2 = withCrc(BP_BODY);
    b2.resize(b2.size() - 2);
    int acceptedS = 0;
    for (size_t i = 0; i < b2.size() * 8; i++) {
        std::string m = b2;
        m[i / 8] ^= (char)(1 << (i % 8));
        LinkCore c;
        lcInit(&c, LINK_STM32, 0);
        feed(c, m + "\r\n", 1);
        if (c.stats.good > 0) acceptedS++;
    }
    CHECK(acceptedS == 0);
}

static void testNumbers() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    // a value that fits a double but not a float
    CHECK(feed(c, withCrc("TEMP:1e39,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:0,ST:0,SEQ:0,UP:0,VCC:1"), 100) == OUT_REJECTED);
    CHECK(feed(c, withCrc("TEMP:1,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:1e30,ST:0,SEQ:0,UP:0,VCC:1"), 200) == OUT_REJECTED);
    CHECK(feed(c, withCrc("TEMP:1,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:0.9,ST:0,SEQ:0,UP:0,VCC:1"), 300) == OUT_REJECTED);
    CHECK(feed(c, withCrc("TEMP:1,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:2,ST:0,SEQ:0,UP:0,VCC:1"), 400) == OUT_REJECTED);
    CHECK(feed(c, withCrc("TEMP:1,HUM:1,PRES:1,LIGHT:1,MOIST:1,WATER:1,ST:0,SEQ:0,UP:0,VCC:1"), 500) == OUT_GOOD);
    CHECK(c.nano.water);
    CHECK(c.stats.format == 4 && c.stats.crc == 0);
    CHECK(lcParseFailures(&c) == 4);
}

static void testSentinel() {
    // on a checksummed line -1.0 is a temperature. the status bits say whether it is usable
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    CHECK(feed(c, withCrc("TEMP:-1.0,HUM:60.0,PRES:1000.0,LIGHT:1,MOIST:1,WATER:0,ST:0,SEQ:0,UP:2,VCC:4900"), 100) == OUT_GOOD);
    CHECK(c.nano.checksummed && c.nano.temp == -1.0f && nanoBmeState(c.nano.st) == HS_OK);
    CHECK(feed(c, withCrc("TEMP:-1,HUM:-1,PRES:-1,LIGHT:1,MOIST:1,WATER:0,ST:1,SEQ:1,UP:4,VCC:4900"), 200) == OUT_GOOD);
    CHECK(nanoBmeState(c.nano.st) == HS_MISSING);
    // an old-format line has no status bits and is not marked checksummed
    LinkCore d;
    lcInit(&d, LINK_NANO, 0);
    CHECK(feed(d, "TEMP:-1,HUM:-1,PRES:-1,LIGHT:1,MOIST:1,WATER:0\r\n", 100) == OUT_GOOD);
    CHECK(!d.nano.checksummed);
}

static void testDebounce() {
    // a status bit is a fault only when it is set on two lines in a row
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    feed(c, withCrc(nanoBody(0, 0, 2)), 1000);
    CHECK(c.stStable == 0);
    feed(c, withCrc(nanoBody(NANO_BME_ASLEEP, 1, 4)), 3000);
    CHECK(c.nano.st == NANO_BME_ASLEEP);          // the line itself says asleep
    CHECK(c.stStable == 0);                        // but it is a glitch until it repeats
    CHECK(nanoBmeState(c.stStable) == HS_OK);
    feed(c, withCrc(nanoBody(NANO_BME_ASLEEP, 2, 6)), 5000);
    CHECK(c.stStable == NANO_BME_ASLEEP);
    CHECK(nanoBmeState(c.stStable) == HS_MISSING);
    feed(c, withCrc(nanoBody(0, 3, 8)), 7000);
    CHECK(c.stStable == 0);
    // different bits on consecutive lines do not combine
    feed(c, withCrc(nanoBody(NANO_BME_ASLEEP, 4, 10)), 9000);
    feed(c, withCrc(nanoBody(NANO_SUPPLY_RANGE, 5, 12)), 11000);
    CHECK(c.stStable == 0);
    // clipping alone is never a fault and the reading stays usable
    LinkCore b;
    lcInit(&b, LINK_STM32, 0);
    feed(b, withCrc(bpBody(STM_CLIPPING, 0, 1)), 1000);
    feed(b, withCrc(bpBody(STM_CLIPPING, 1, 2)), 2000);
    CHECK(b.stStable == STM_CLIPPING && stm32MpuState(b.stStable) == HS_OK && stm32Clipping(b.stm.st));
    // no window is intermittent once it has repeated
    feed(b, withCrc(bpBody(STM_NO_DATA, 2, 3)), 3000);
    CHECK(stm32MpuState(b.stStable) == HS_OK);
    feed(b, withCrc(bpBody(STM_NO_DATA, 3, 4)), 4000);
    CHECK(stm32MpuState(b.stStable) == HS_INTERMITTENT);
}

static void testRestartRule() {
    // SEQ 0, 1, 3 with UP 2, 4, 8 is a gap of one line. nothing went back, so it is no restart
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    feed(c, withCrc(nanoBody(0, 0, 2)), 1000);
    feed(c, withCrc(nanoBody(0, 1, 4)), 3000);
    feed(c, withCrc(nanoBody(0, 3, 8)), 5000);
    CHECK(c.stats.gaps == 1 && c.stats.restarts == 0);
    // SEQ going back with UP going back is a restart
    LinkCore d;
    lcInit(&d, LINK_NANO, 0);
    feed(d, withCrc(nanoBody(0, 50, 100)), 1000);
    feed(d, withCrc(nanoBody(0, 0, 2)), 3000);
    CHECK(d.stats.restarts == 1 && d.stats.gaps == 0);
    // SEQ going forward with UP going back is not: a gap
    LinkCore e;
    lcInit(&e, LINK_NANO, 0);
    feed(e, withCrc(nanoBody(0, 50, 100)), 1000);
    feed(e, withCrc(nanoBody(0, 60, 90)), 3000);
    CHECK(e.stats.restarts == 0 && e.stats.gaps == 1);
}

static void testRateWindow() {
    RateWindow w;
    rwInit(&w, 0);
    CHECK(!rwLossy(&w, 0, 8));
    // exactly a fifth is not more than a fifth
    for (int i = 0; i < 8; i++) rwAdd(&w, 1000 + i * 100, 1, 0);
    rwAdd(&w, 2000, 0, 2);
    CHECK(!rwLossy(&w, 2000, 8));       // 2 of 10
    rwAdd(&w, 2100, 0, 1);
    CHECK(rwLossy(&w, 2100, 8));        // 3 of 11
    // too few lines expected: one failure on a quiet link is not enough
    RateWindow q;
    rwInit(&q, 0);
    rwAdd(&q, 100, 0, 1);
    rwAdd(&q, 200, 2, 0);
    CHECK(!rwLossy(&q, 300, 8));
    // everything falls out of the window after a minute
    CHECK(rwLossy(&w, 2100, 8));
    CHECK(!rwLossy(&w, 2100 + 61000, 8));
    // and the counts survive a millis() rollover
    RateWindow r;
    uint32_t t0 = 0xFFFFFF00u;
    rwInit(&r, t0);
    for (int i = 0; i < 10; i++) rwAdd(&r, t0 + i * 100, 0, 1);
    CHECK(rwLossy(&r, t0 + 1000, 8));
    CHECK(rwLossy(&r, t0 + 30000, 8));  // across the wrap
    CHECK(!rwLossy(&r, t0 + 70000, 8));
}

static void testLossyLink() {
    // one line in three corrupt for a minute
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    unsigned seq = 0;
    for (uint32_t t = 0; t <= 60000; t += 2000) {
        std::string line = withCrc(nanoBody(0, seq, t / 1000));
        if ((t / 2000) % 3 == 1) line[4] = 'Z';
        feed(c, line, t);
        seq++;
    }
    CHECK(c.stats.crc >= 9);
    CHECK(lcState(&c, 60000) == HS_INTERMITTENT);

    // lines lost to a sequence gap count against the link as well
    LinkCore g;
    lcInit(&g, LINK_NANO, 0);
    unsigned s = 0;
    for (uint32_t t = 0; t <= 60000; t += 2000) {
        feed(g, withCrc(nanoBody(0, s, t / 1000)), t);
        s += (t / 2000) % 2 ? 2 : 1;      // every other line skips one
    }
    CHECK(g.stats.gaps >= 10);
    CHECK(lcState(&g, 60000) == HS_INTERMITTENT);

    // one corrupt line in twenty is a healthy link
    LinkCore h;
    lcInit(&h, LINK_NANO, 0);
    s = 0;
    for (uint32_t t = 0; t <= 120000; t += 2000) {
        std::string line = withCrc(nanoBody(0, s, t / 1000));
        if ((t / 2000) % 20 == 5) line[4] = 'Z';
        feed(h, line, t);
        s++;
    }
    CHECK(lcState(&h, 120000) == HS_OK);
}

static void testPrecedence() {
    // line_low beats everything
    LinkCore a;
    lcInit(&a, LINK_NANO, 0);
    for (uint32_t t = 10000; t <= 17000; t += SERIAL_POLL_MS) lcNoteLevel(&a, false, t);
    CHECK(lcState(&a, 17000) == HS_LINE_LOW);

    // garbage is judged before silent
    LinkCore b;
    lcInit(&b, LINK_NANO, 0);
    for (uint32_t t = 15000; t <= 21000; t += 2000) feed(b, withCrc("TEMP:1"), t);
    CHECK(lcState(&b, 21000) == HS_GARBAGE);

    // one_way beats intermittent
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    unsigned seq = 0;
    char out[16];
    for (uint32_t t = 0; t <= 92000; t += 500) {
        if (t % 2000 == 0) {
            std::string line = withCrc(nanoBody(0, seq, t / 1000));
            if ((t / 2000) % 3 == 1) line[4] = 'Z';
            feed(c, line, t);
            seq++;
        }
        lcPingDue(&c, t, out, sizeof out);          // never answered
    }
    CHECK(lcPingsUnanswered(&c, 92000) >= 3);
    CHECK(lcState(&c, 92000) == HS_ONE_WAY);
}

static void testWrongBaudNoise() {
    // bytes arrive with no line end: wrong baud rate. that reads as garbage and not silent
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    for (uint32_t t = 0; t < 30000; t += 10) {
        for (int i = 0; i < 20; i++) lcFeedByte(&c, (uint8_t)('a' + i), t);
    }
    CHECK(c.stats.overlong >= 3);
    CHECK(lcState(&c, 30000) == HS_GARBAGE);
}

static void testLineLowLatchAcrossAlias() {
    // a dead low line must stay line_low when millis() wraps. the old start-up comparison
    // made it read ok for 15 s after the alias.
    uint32_t boot = 100;
    LinkCore c;
    lcInit(&c, LINK_NANO, boot);
    for (uint32_t t = boot + 16000; t <= boot + 22000; t += SERIAL_POLL_MS) lcNoteLevel(&c, false, t);
    CHECK(lcState(&c, boot + 22000) == HS_LINE_LOW);
    uint32_t wrapped = boot + 99;               // 49.7 days later
    CHECK(lcState(&c, wrapped) == HS_LINE_LOW);
    CHECK(lcState(&c, wrapped + 5000) == HS_LINE_LOW);
}

static void testRateWindowIsPartOfState() {
    // a link that is healthy again clears intermittent after a minute
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    unsigned seq = 0;
    for (uint32_t t = 0; t <= 30000; t += 2000) {
        std::string line = withCrc(nanoBody(0, seq++, t / 1000));
        if ((t / 2000) % 2) line[4] = 'Z';
        feed(c, line, t);
    }
    CHECK(lcState(&c, 30000) == HS_INTERMITTENT);
    for (uint32_t t = 32000; t <= 100000; t += 2000) feed(c, withCrc(nanoBody(0, seq++, t / 1000)), t);
    CHECK(lcState(&c, 100000) == HS_OK);
}


static void testHistIntermittent() {
    // three or more of the last ten lines. a part that is set on two lines in a row right now shows
    // its debounced fault state instead, so adjacent sets no longer hide the flapping
    CHECK(lcHistIntermittent(0x0000) == false);
    CHECK(lcHistIntermittent(0x0001) == false);
    CHECK(lcHistIntermittent(0x0005) == false);            // two sets only
    CHECK(lcHistIntermittent(0x0015) == true);             // three, alternating
    CHECK(lcHistIntermittent(0x0155) == true);             // five, alternating
    CHECK(lcHistIntermittent(0x0003) == false);            // two sets only
    CHECK(lcHistIntermittent(0x0035) == true);             // three, two of them adjacent
    CHECK(lcHistIntermittent(0x0249) == true);             // every third line
    CHECK(lcHistIntermittent(0x0405) == false);            // a bit past the tenth line is ignored
    CHECK(lcHistIntermittent(0x03FF) == true);
}

static void testBitComesAndGoes() {
    // BME_MISSING on alternate Nano lines never makes two in a row, so the debounce never raises
    // a fault. the values vanish from half the posts, so the part is intermittent instead
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    unsigned seq = 0;
    uint32_t t = 1000;
    LinkHealth h;
    for (int i = 0; i < 12; i++, t += 2000) {
        unsigned st = (i % 2 == 1) ? NANO_BME_MISSING : 0;
        feed(c, withCrc(nanoBody(st, seq++, t / 1000)), t);
        h = lcHealth(&c, t);
        if (i == 2) CHECK(h.partA == HS_OK);                // two sets are not enough
    }
    CHECK(c.stStable == 0);                                 // never two in a row
    CHECK(h.link == HS_OK);
    CHECK(h.partA == HS_INTERMITTENT);
    CHECK(h.partB == HS_OK);
    // it clears once ten clean lines have gone by
    for (int i = 0; i < 10; i++, t += 2000) feed(c, withCrc(nanoBody(0, seq++, t / 1000)), t);
    h = lcHealth(&c, t);
    CHECK(h.partA == HS_OK);

    // the supply bit is its own part
    LinkCore s;
    lcInit(&s, LINK_NANO, 0);
    seq = 0;
    t = 1000;
    for (int i = 0; i < 8; i++, t += 2000) {
        unsigned st = (i % 2 == 0) ? NANO_SUPPLY_RANGE : 0;
        feed(s, withCrc(nanoBody(st, seq++, t / 1000)), t);
    }
    h = lcHealth(&s, t);
    CHECK(h.partB == HS_INTERMITTENT && h.partA == HS_OK);

    // the Black Pill's no-window bit on alternate lines. clipping on alternate lines is a reading
    LinkCore b;
    lcInit(&b, LINK_STM32, 0);
    seq = 0;
    t = 1000;
    for (int i = 0; i < 8; i++, t += 1000) {
        unsigned st = (i % 2 == 1) ? STM_NO_DATA : STM_CLIPPING;
        feed(b, withCrc(bpBody(st, seq++, t / 1000)), t);
    }
    h = lcHealth(&b, t);
    CHECK(h.partA == HS_INTERMITTENT);
    LinkCore d;
    lcInit(&d, LINK_STM32, 0);
    seq = 0;
    t = 1000;
    for (int i = 0; i < 12; i++, t += 1000) {
        unsigned st = (i % 2 == 1) ? STM_CLIPPING : 0;
        feed(d, withCrc(bpBody(st, seq++, t / 1000)), t);
    }
    h = lcHealth(&d, t);
    CHECK(h.partA == HS_OK);
}

static void testOneWayAfterOutage() {
    // pings missed while the link was dead must not count once it comes back
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    unsigned seq = 0;
    char out[16];
    uint32_t t = 0;
    for (; t <= 18000; t += 2000) feed(c, withCrc(nanoBody(0, seq++, t / 1000)), t);
    // the link goes quiet for 100 s. pings go out and nothing answers
    for (; t <= 120000; t += 500) {
        lcPingDue(&c, t, out, sizeof out);
        if (t % 5000 == 0) lcState(&c, t);
    }
    CHECK(lcState(&c, 120000) == HS_SILENT);
    // the satellite comes back and answers every ping from now on
    feed(c, withCrc(nanoBody(0, seq++, t / 1000)), t);
    CHECK(lcState(&c, t) == HS_OK);                         // not one_way for up to 30 s
    for (int i = 0; i < 10; i++) {
        t += 2000;
        feed(c, withCrc(nanoBody(0, seq++, t / 1000)), t);
        CHECK(lcState(&c, t) == HS_OK);
    }
}

static void testRestartAfterSeqZero() {
    // the last SEQ the hub saw was 0 and the satellite restarts at 0 again
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    feed(c, withCrc(nanoBody(0, 0, 40)), 1000);
    feed(c, withCrc(nanoBody(0, 0, 2)), 3000);              // UP went back, SEQ is not forward
    CHECK(c.stats.restarts == 1 && c.stats.gaps == 0);
    // an ordinary forward step is neither
    feed(c, withCrc(nanoBody(0, 1, 4)), 5000);
    CHECK(c.stats.restarts == 1 && c.stats.gaps == 0);
}

static void testFailureRingForgets() {
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    feed(c, withCrc("TEMP:1"), 1000);
    feed(c, withCrc("TEMP:1"), 2000);
    feed(c, withCrc("TEMP:1"), 3000);
    CHECK(c.failCount == 3);
    lcState(&c, 4000);
    CHECK(c.failCount == 3);
    lcState(&c, 3000 + LINK_SILENT_MS + 1);                  // the newest is now older than the window
    CHECK(c.failCount == 0);
}

static void testGarbageNeedsRecentFailures() {
    // old failures are forgotten, so they never feed the garbage rule again
    LinkCore c;
    lcInit(&c, LINK_NANO, 0);
    for (uint32_t t = 1000; t <= 3000; t += 1000) feed(c, withCrc("TEMP:1"), t);
    lcFeedByte(&c, 'x', 100000);                              // bytes still arrive, nothing valid
    CHECK(lcState(&c, 100000) == HS_SILENT);
}


static void testRateWindowAdvancesWhileDead() {
    // the one-minute window moves on in lcState even while the link is dead, so old counts leave it
    RateWindow w;
    rwInit(&w, 0);
    rwAdd(&w, 1000, 5, 5);
    uint32_t good = 0, bad = 0;
    rwTotals(&w, 1000, &good, &bad);
    CHECK(good == 5 && bad == 5);
    rwTick(&w, 90000);
    rwTotals(&w, 90000, &good, &bad);
    CHECK(good == 0 && bad == 0);
}

int main() {
    testCrc();
    testNanoGoodLine();
    testBlackPillGoodLine();
    testCorruptLines();
    testFormatErrors();
    testLegacyRule();
    testStatusBits();
    testSequence();
    testSequenceWrap();
    testDroppedWindowIsNotAGap();
    testLineLimit();
    testOverlongWithoutLineEnd();
    testNoiseBytes();
    testPing();
    testOneWay();
    testLinkStates();
    testSilentLatchAcrossRollover();
    testStrictLegacy();
    testLegacySingleBitErrors();
    testNumbers();
    testSentinel();
    testDebounce();
    testRestartRule();
    testRateWindow();
    testLossyLink();
    testPrecedence();
    testWrongBaudNoise();
    testLineLowLatchAcrossAlias();
    testRateWindowIsPartOfState();
    testHistIntermittent();
    testRateWindowAdvancesWhileDead();
    testBitComesAndGoes();
    testOneWayAfterOutage();
    testRestartAfterSeqZero();
    testFailureRingForgets();
    testGarbageNeedsRecentFailures();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
