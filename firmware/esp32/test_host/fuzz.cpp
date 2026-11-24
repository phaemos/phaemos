// fuzz.cpp - fuzz and mutation test of the hub link parser, with the address and undefined
// behaviour sanitizers on. it feeds random bytes, mutated copies of good lines and every one
// and two bit error of the example line. it checks that nothing crashes, that the line buffer never
// grows past its limit, noise is never accepted as a line and no single or double bit error is
// accepted once a checksummed line has been seen. a damaged line must not pass as an old-format
// line either, so the single bit errors are also run with the old-format window still open.
// the argument is the number of random bytes per kind (default 400000, a few seconds). the
// first version of this program was written by the review of the hub firmware.
//
// build and run from this folder:
//   c++ -std=c++17 -g -fsanitize=address,undefined -I.. fuzz.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/fuzz" && "${TMPDIR:-/tmp}/fuzz"
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "../comms/link_protocol.h"
#include "../config.h"

static uint64_t rng = 0x9E3779B97F4A7C15ull;
static uint32_t rnd() { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return (uint32_t)(rng >> 16); }

static std::string seal(const std::string& body) {
    char t[8]; snprintf(t, sizeof t, "*%04X", crc16ccitt((const uint8_t*)body.data(), body.size()));
    return body + t + "\r\n";
}
static Outcome feed(LinkCore* c, const std::string& s, uint32_t now) {
    Outcome last = OUT_NONE;
    for (unsigned char ch : s) { Outcome o = lcFeedByte(c, ch, now); if (o != OUT_NONE) last = o; 
        if (c->buf.len > LINK_LINE_MAX) { printf("INVARIANT: len %u\n", c->buf.len); abort(); } }
    return last;
}
static bool finiteNano(const NanoReading& n) { return std::isfinite(n.temp) && std::isfinite(n.hum) && std::isfinite(n.pres) && std::isfinite(n.light) && std::isfinite(n.moist); }

static const char* NANO = "TEMP:25.1,HUM:50.7,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:0,SEQ:12,UP:26,VCC:4980";
static const char* STM  = "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,ST:0,SEQ:7,UP:9,MT:0,RF:0,BR:0";

int main(int argc, char** argv) {
    long iters = argc > 1 ? atol(argv[1]) : 400000;
    int failures = 0;
    // contract examples
    printf("contract nano example crc: %04X (contract says F6B1)\n", crc16ccitt((const uint8_t*)NANO, strlen(NANO)));
    printf("contract stm example crc:  %04X (contract says AD94)\n", crc16ccitt((const uint8_t*)STM, strlen(STM)));

    // 1. random byte fuzz, both kinds, with sanitizers
    for (int kind = 0; kind < 2; kind++) {
        LinkCore c; lcInit(&c, (LinkKind)kind, 0);
        uint32_t now = 0; uint32_t good0;
        for (long i = 0; i < iters; i++) {
            uint8_t b;
            uint32_t r = rnd();
            switch (r % 8) { case 0: b = '\n'; break; case 1: b = 0; break; case 2: b = '*'; break; case 3: b = ','; break; case 4: b = ':'; break;
                             default: b = (uint8_t)(r >> 8); }
            if ((r >> 20) % 97 == 0) now += rnd() % 40000;
            lcFeedByte(&c, b, now);
            if (c.buf.len > LINK_LINE_MAX - 1) { printf("INVARIANT len\n"); return 1; }
            if ((i & 0xFFFF) == 0) lcState(&c, now);
        }
        good0 = c.stats.good;
        printf("random fuzz kind %d: good %u crc %u format %u overlong %u (any good line from noise is a false accept)\n", kind, good0, c.stats.crc, c.stats.format, c.stats.overlong);
        if (good0 != 0) { printf("FAIL: noise accepted as a line\n"); failures++; }
    }

    // 2. mutation fuzz of valid checksummed lines: count accepted lines whose content differs
    for (int kind = 0; kind < 2; kind++) {
        for (int legacy = 0; legacy < 2; legacy++) {
            long accepted_diff = 0, accepted_same = 0, total = 0, nonfinite = 0;
            std::string base = seal(kind == 0 ? NANO : STM);
            for (long i = 0; i < iters / 4; i++) {
                LinkCore c; lcInit(&c, (LinkKind)kind, 0);
                if (!legacy) { feed(&c, base, 0); }       // sawChecksum latched
                std::string m = base;
                int nm = 1 + rnd() % 4;
                for (int k = 0; k < nm; k++) {
                    uint32_t r = rnd(); size_t pos = r % m.size();
                    switch ((r >> 16) % 6) {
                        case 0: m[pos] ^= (char)(1 << ((r >> 24) % 8)); break;     // bit flip
                        case 1: m.erase(pos, 1 + (r >> 24) % 5); break;             // deletion
                        case 2: m.insert(pos, 1, (char)(r >> 24)); break;           // insertion
                        case 3: m = m.substr(0, pos) + "\n"; break;                 // truncation with a line end
                        case 4: m[pos] = (char)(r >> 24); break;                    // byte replaced
                        case 5: m = m.substr(pos); break;                           // start lost
                    }
                    if (m.empty()) m = "\n";
                }
                if (m == base) continue;
                if (m.back() != '\n') m += "\n";
                uint32_t g0 = c.stats.good;
                feed(&c, m, 10);
                total++;
                if (c.stats.good > g0) {
                    bool same;
                    LinkCore ref; lcInit(&ref, (LinkKind)kind, 0); feed(&ref, base, 0);
                    if (kind == 0) same = memcmp(&c.nano, &ref.nano, sizeof c.nano) == 0; else same = memcmp(&c.stm, &ref.stm, sizeof c.stm) == 0;
                    if (same) accepted_same++; else { accepted_diff++; if (accepted_diff <= 6) { std::string show = m; for (auto& ch : show) if (ch == '\r' || ch == '\n') ch = '|'; printf("   accepted with different content: %s\n", show.c_str()); } }
                    if (kind == 0 && !finiteNano(c.nano)) nonfinite++;
                }
            }
            printf("mutation fuzz kind %d %s: %ld mutated, %ld accepted with DIFFERENT content, %ld accepted identical, nonfinite %ld\n", kind, legacy ? "before first checksummed line (legacy open)" : "after first checksummed line", total, accepted_diff, accepted_same, nonfinite);
        }
    }

    // 3. exhaustive 1 and 2 bit errors on the example line (body+star+crc), after checksum latched
    {
        std::string base = seal(NANO); base.resize(base.size() - 2);  // without CR LF
        long pass1 = 0, pass2 = 0, n1 = 0, n2 = 0;
        size_t bits = base.size() * 8;
        for (size_t i = 0; i < bits; i++) {
            std::string m = base; m[i / 8] ^= (char)(1 << (i % 8));
            LinkCore c; lcInit(&c, LINK_NANO, 0); feed(&c, seal(NANO), 0); uint32_t g = c.stats.good;
            feed(&c, m + "\r\n", 1); n1++; if (c.stats.good > g) pass1++;
        }
        for (size_t i = 0; i < bits; i++) for (size_t j = i + 1; j < bits; j++) {
            std::string m = base; m[i / 8] ^= (char)(1 << (i % 8)); m[j / 8] ^= (char)(1 << (j % 8));
            LinkCore c; lcInit(&c, LINK_NANO, 0); c.sawChecksum = true; uint32_t g = c.stats.good;
            feed(&c, m + "\r\n", 1); n2++; if (c.stats.good > g) pass2++;
        }
        printf("exhaustive: 1 bit errors %ld of %ld accepted, 2 bit errors %ld of %ld accepted (checksum latched)\n", pass1, n1, pass2, n2);
        if (pass1 != 0 || pass2 != 0) { printf("FAIL: a 1 or 2 bit error was accepted\n"); failures++; }
        // same, legacy still open (hub just booted)
        pass1 = 0; long passdiff = 0;
        for (size_t i = 0; i < bits; i++) {
            std::string m = base; m[i / 8] ^= (char)(1 << (i % 8));
            LinkCore c; lcInit(&c, LINK_NANO, 0); uint32_t g = c.stats.good;
            feed(&c, m + "\r\n", 1); if (c.stats.good > g) { pass1++; printf("   legacy window, 1 bit error accepted: %s  -> st %u up %u vcc %u sawChecksum %d\n", m.c_str(), c.nano.st, c.nano.up, c.nano.vccMv, c.sawChecksum); }
        }
        long pass2l = 0;
        for (size_t i = 0; i < bits; i++) for (size_t j = i + 1; j < bits; j++) {
            std::string m = base; m[i / 8] ^= (char)(1 << (i % 8)); m[j / 8] ^= (char)(1 << (j % 8));
            LinkCore c; lcInit(&c, LINK_NANO, 0); uint32_t g = c.stats.good;
            feed(&c, m + "\r\n", 1); if (c.stats.good > g) { pass2l++; LinkCore ref; lcInit(&ref, LINK_NANO, 0); feed(&ref, seal(NANO), 0);
                if (c.nano.temp != ref.nano.temp || c.nano.hum != ref.nano.hum || c.nano.pres != ref.nano.pres || c.nano.light != ref.nano.light || c.nano.moist != ref.nano.moist || c.nano.water != ref.nano.water) { passdiff++; if (passdiff <= 5) printf("   legacy window, 2 bit error accepted with a wrong reading: %s\n", m.c_str()); } }
        }
        printf("legacy window: 1 bit errors accepted %ld, 2 bit errors accepted %ld of which %ld carry a wrong reading\n", pass1, pass2l, passdiff);
        if (pass1 != 0) { printf("FAIL: a single bit error passed as an old-format line\n"); failures++; }
        if (passdiff != 0) { printf("FAIL: a double bit error passed as an old-format line with a wrong reading\n"); failures++; }
    }
    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
