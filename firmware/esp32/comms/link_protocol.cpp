#include "link_protocol.h"

#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../config.h"

// ─── CRC ─────────────────────────────────────────────────────────────────────
uint16_t crc16ccitt(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t b = 0; b < 8; b++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

// ─── line assembly ───────────────────────────────────────────────────────────
void lineReset(LineBuf* b) {
    b->len      = 0;
    b->overflow = false;
    b->skipped  = 0;
    b->data[0]  = 0;
}

LineEvent lineFeed(LineBuf* b, uint8_t c) {
    if (c == 0) return LE_NONE;
    if (c == '\n') {
        bool wasOver = b->overflow;
        uint16_t len = b->len;
        if (wasOver) {
            lineReset(b);
            return LE_NONE;         // the overlong line was reported when it overflowed
        }
        b->data[len] = 0;
        return LE_LINE;             // the caller handles the line and then calls lineReset
    }
    if (b->overflow) {
        // keep counting failures while the bytes keep coming with no line end
        if (++b->skipped >= LINK_LINE_MAX - 1) {
            b->skipped = 0;
            return LE_OVERLONG;
        }
        return LE_NONE;
    }
    // 159 bytes of content plus the line feed is the 160 byte limit.
    if (b->len >= LINK_LINE_MAX - 1) {
        b->overflow = true;
        b->len      = 0;
        b->skipped  = 0;
        return LE_OVERLONG;
    }
    b->data[b->len++] = (char)c;
    return LE_NONE;
}

// ─── status bits ─────────────────────────────────────────────────────────────
HealthState nanoBmeState(uint16_t st) {
    if (st & (NANO_BME_MISSING | NANO_BME_ASLEEP)) return HS_MISSING;
    if (st & NANO_BME_STUCK) return HS_STUCK;
    if (st & NANO_BME_RANGE) return HS_OUT_OF_RANGE;
    return HS_OK;
}

HealthState nanoSupplyState(uint16_t st) {
    return (st & NANO_SUPPLY_RANGE) ? HS_OUT_OF_RANGE : HS_OK;
}

HealthState stm32MpuState(uint16_t st) {
    if (st & (STM_SENSOR_MISSING | STM_ID_MISMATCH)) return HS_MISSING;
    if (st & STM_SENSOR_STUCK) return HS_STUCK;
    if (st & STM_NO_DATA) return HS_INTERMITTENT;
    return HS_OK;
}

bool stm32Clipping(uint16_t st) {
    return (st & STM_CLIPPING) != 0;
}

// ─── link quality window ─────────────────────────────────────────────────────
static void rwAdvance(RateWindow* w, uint32_t nowMs) {
    uint32_t steps = (uint32_t)(nowMs - w->headStartMs) / LINK_RATE_BUCKET_MS;
    if (steps == 0) return;
    if (steps > LINK_RATE_BUCKETS) steps = LINK_RATE_BUCKETS;
    for (uint32_t i = 0; i < steps; i++) {
        w->head = (uint8_t)((w->head + 1) % LINK_RATE_BUCKETS);
        w->good[w->head] = 0;
        w->bad[w->head]  = 0;
    }
    // move the bucket start on by whole buckets only, so the cadence never drifts
    uint32_t whole = (uint32_t)(nowMs - w->headStartMs) / LINK_RATE_BUCKET_MS;
    w->headStartMs += whole * (uint32_t)LINK_RATE_BUCKET_MS;
}

void rwTick(RateWindow* w, uint32_t nowMs) {
    rwAdvance(w, nowMs);
}

void rwInit(RateWindow* w, uint32_t nowMs) {
    memset(w, 0, sizeof *w);
    w->headStartMs = nowMs;
}

void rwAdd(RateWindow* w, uint32_t nowMs, uint16_t good, uint16_t bad) {
    rwAdvance(w, nowMs);
    uint32_t g = (uint32_t)w->good[w->head] + good;
    uint32_t b = (uint32_t)w->bad[w->head] + bad;
    w->good[w->head] = g > 65535 ? 65535 : (uint16_t)g;
    w->bad[w->head]  = b > 65535 ? 65535 : (uint16_t)b;
}

void rwTotals(RateWindow* w, uint32_t nowMs, uint32_t* good, uint32_t* bad) {
    rwAdvance(w, nowMs);
    uint32_t g = 0, b = 0;
    for (uint8_t i = 0; i < LINK_RATE_BUCKETS; i++) {
        g += w->good[i];
        b += w->bad[i];
    }
    *good = g;
    *bad  = b;
}

bool rwLossy(RateWindow* w, uint32_t nowMs, uint32_t minLines) {
    uint32_t g, b;
    rwTotals(w, nowMs, &g, &b);
    uint32_t total = g + b;
    return total >= minLines && b * 5u > total;
}

// ─── parsing ─────────────────────────────────────────────────────────────────
namespace {

const uint8_t MAX_FIELDS = 24;

struct Field {
    const char* key;
    const char* val[3];
    uint8_t     n;
};

struct Fields {
    Field   f[MAX_FIELDS];
    uint8_t n;
};

// splits "KEY:v,v,v,KEY:v" in place. a token with a colon starts a key and a token without
// one adds a value to the key before it, which is how VIB and RMS carry three numbers.
bool tokenise(char* body, Fields* out) {
    out->n = 0;
    char* p = body;
    while (true) {
        char* comma = strchr(p, ',');
        if (comma) *comma = 0;
        if (*p == 0) return false;                     // empty token
        char* colon = strchr(p, ':');
        if (colon) {
            if (out->n >= MAX_FIELDS) return false;
            *colon = 0;
            Field& f = out->f[out->n++];
            f.key    = p;
            f.val[0] = colon + 1;
            f.n      = 1;
            if (*f.val[0] == 0) return false;
        } else {
            if (out->n == 0) return false;
            Field& f = out->f[out->n - 1];
            if (f.n >= 3) return false;
            f.val[f.n++] = p;
        }
        if (!comma) break;
        p = comma + 1;
    }
    return true;
}

const Field* findField(const Fields& fs, const char* key) {
    const Field* hit = nullptr;
    for (uint8_t i = 0; i < fs.n; i++) {
        if (strcmp(fs.f[i].key, key) == 0) hit = &fs.f[i];   // the last one wins
    }
    return hit;
}

bool parseFloat(const char* s, float* out) {
    if (*s == 0) return false;
    for (const char* c = s; *c; c++) {
        if (!((*c >= '0' && *c <= '9') || *c == '-' || *c == '+' || *c == '.' ||
              *c == 'e' || *c == 'E')) return false;
    }
    char* end = nullptr;
    double v = strtod(s, &end);
    // a double that is finite can still overflow a float and become infinity when stored.
    if (*end != 0 || !isfinite(v) || fabs(v) > (double)FLT_MAX) return false;
    *out = (float)v;
    return true;
}

// the old format's numbers: an optional minus, digits then an optional fraction. no plus, no
// exponent and no other character, so a bit error cannot turn one into another number.
bool parseStrictNumber(const char* s, float* out) {
    const char* c = s;
    if (*c == '-') c++;
    if (*c < '0' || *c > '9') return false;
    while (*c >= '0' && *c <= '9') c++;
    if (*c == '.') {
        c++;
        if (*c < '0' || *c > '9') return false;
        while (*c >= '0' && *c <= '9') c++;
    }
    if (*c != 0 || (c - s) > 16) return false;
    return parseFloat(s, out);
}

bool parseUInt(const char* s, uint32_t maxValue, uint32_t* out) {
    if (*s == 0) return false;
    uint64_t v = 0;
    for (const char* c = s; *c; c++) {
        if (*c < '0' || *c > '9') return false;
        v = v * 10 + (uint64_t)(*c - '0');
        if (v > maxValue) return false;
    }
    *out = (uint32_t)v;
    return true;
}

bool getFloat(const Fields& fs, const char* key, float* out) {
    const Field* f = findField(fs, key);
    return f && f->n == 1 && parseFloat(f->val[0], out);
}

bool getFloat3(const Fields& fs, const char* key, float out[3]) {
    const Field* f = findField(fs, key);
    if (!f || f->n != 3) return false;
    for (uint8_t i = 0; i < 3; i++) {
        if (!parseFloat(f->val[i], &out[i])) return false;
    }
    return true;
}

bool getUInt(const Fields& fs, const char* key, uint32_t maxValue, uint32_t* out) {
    const Field* f = findField(fs, key);
    return f && f->n == 1 && parseUInt(f->val[0], maxValue, out);
}

// FFT_PEAK carries a unit, as in 12.5Hz.
bool stripHz(const char* in, char* out, size_t cap) {
    size_t n = strlen(in);
    if (n >= cap) return false;
    memcpy(out, in, n + 1);
    if (n >= 2 && out[n - 2] == 'H' && out[n - 1] == 'z') {
        out[n - 2] = 0;
        return true;
    }
    return false;
}

bool getHz(const Fields& fs, const char* key, float* out) {
    const Field* f = findField(fs, key);
    if (!f || f->n != 1) return false;
    char tmp[24];
    stripHz(f->val[0], tmp, sizeof tmp);   // the unit is optional on a checksummed line
    if (strlen(f->val[0]) >= sizeof tmp) return false;
    return parseFloat(tmp, out);
}

// the keys every checksummed line carries
bool getCommon(const Fields& fs, uint16_t* st, uint16_t* seq, uint32_t* up) {
    uint32_t s, q, u;
    if (!getUInt(fs, "ST", 65535, &s)) return false;
    if (!getUInt(fs, "SEQ", 65535, &q)) return false;
    if (!getUInt(fs, "UP", 0xFFFFFFFFu, &u)) return false;
    *st = (uint16_t)s;
    *seq = (uint16_t)q;
    *up = u;
    return true;
}

// a checksummed Nano line. the keys may come in any order and unknown keys are ignored.
bool parseNano(const Fields& fs, NanoReading* r, uint16_t* seq) {
    NanoReading n;
    memset(&n, 0, sizeof n);
    uint32_t water, vcc;
    if (!getFloat(fs, "TEMP", &n.temp) || !getFloat(fs, "HUM", &n.hum) ||
        !getFloat(fs, "PRES", &n.pres) || !getFloat(fs, "LIGHT", &n.light) ||
        !getFloat(fs, "MOIST", &n.moist) || !getUInt(fs, "WATER", 1, &water)) return false;
    n.water = (water != 0);
    if (!getCommon(fs, &n.st, seq, &n.up)) return false;
    if (!getUInt(fs, "VCC", 65535, &vcc)) return false;
    n.vccMv = (uint16_t)vcc;
    n.checksummed = true;
    *r = n;
    return true;
}

bool parseStm32(const Fields& fs, Stm32Reading* r, uint16_t* seq) {
    Stm32Reading s;
    memset(&s, 0, sizeof s);
    if (!getFloat(fs, "MAG", &s.mag) || !getHz(fs, "FFT_PEAK", &s.fft)) return false;
    s.hasVib = getFloat3(fs, "VIB", s.vib);
    if (!s.hasVib) return false;
    if (!getFloat3(fs, "RMS", s.rms) || !getFloat(fs, "PK", &s.pk)) return false;
    if (!getCommon(fs, &s.st, seq, &s.up)) return false;
    s.extended = true;
    uint32_t v;
    if (getUInt(fs, "MT", 0xFFFFFFFFu, &v)) s.mt = v;
    if (getUInt(fs, "RF", 0xFFFFFFFFu, &v)) s.rf = v;
    if (getUInt(fs, "BR", 0xFFFFFFFFu, &v)) s.br = v;
    *r = s;
    return true;
}

// ─── the old format ──────────────────────────────────────────────────────────
// accepted only until the first checksummed line, so it is parsed strictly: the keys in their
// exact order, nothing after the last one, then numbers in their plain form. a damaged
// checksummed line (a bit error on the star leaves it looking like an old line) then has too
// many keys to pass.
bool nextToken(char** cursor, char** out) {
    if (!*cursor) return false;
    *out = *cursor;
    char* comma = strchr(*cursor, ',');
    if (comma) {
        *comma = 0;
        *cursor = comma + 1;
    } else {
        *cursor = nullptr;
    }
    return **out != 0;
}

// expects "KEY:" at the start of the token and returns the value part.
const char* afterKey(const char* tok, const char* key) {
    size_t n = strlen(key);
    if (strncmp(tok, key, n) != 0 || tok[n] != ':') return nullptr;
    return tok + n + 1;
}

bool parseNanoLegacy(char* line, NanoReading* r) {
    static const char* const KEYS[6] = { "TEMP", "HUM", "PRES", "LIGHT", "MOIST", "WATER" };
    float v[6];
    char* cursor = line;
    for (uint8_t i = 0; i < 6; i++) {
        char* tok;
        if (!nextToken(&cursor, &tok)) return false;
        const char* val = afterKey(tok, KEYS[i]);
        if (!val || !parseStrictNumber(val, &v[i])) return false;
    }
    if (cursor) return false;                       // anything after WATER
    if (v[5] != 0.0f && v[5] != 1.0f) return false;
    NanoReading n;
    memset(&n, 0, sizeof n);
    n.temp = v[0]; n.hum = v[1]; n.pres = v[2]; n.light = v[3]; n.moist = v[4];
    n.water = v[5] != 0.0f;
    *r = n;
    return true;
}

bool parseStm32Legacy(char* line, Stm32Reading* r) {
    char* cursor = line;
    char* tok;
    Stm32Reading s;
    memset(&s, 0, sizeof s);
    if (!nextToken(&cursor, &tok)) return false;
    const char* v0 = afterKey(tok, "VIB");
    if (!v0 || !parseStrictNumber(v0, &s.vib[0])) return false;
    for (uint8_t i = 1; i < 3; i++) {
        if (!nextToken(&cursor, &tok) || !parseStrictNumber(tok, &s.vib[i])) return false;
    }
    if (!nextToken(&cursor, &tok)) return false;
    const char* m = afterKey(tok, "MAG");
    if (!m || !parseStrictNumber(m, &s.mag)) return false;
    if (!nextToken(&cursor, &tok)) return false;
    const char* f = afterKey(tok, "FFT_PEAK");
    char tmp[24];
    if (!f || !stripHz(f, tmp, sizeof tmp) || !parseStrictNumber(tmp, &s.fft)) return false;
    if (cursor) return false;
    s.hasVib = true;
    *r = s;
    return true;
}

bool upperHex4(const char* s) {
    for (uint8_t i = 0; i < 4; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) return false;
    }
    return true;
}

uint16_t hex4(const char* s) {
    uint16_t v = 0;
    for (uint8_t i = 0; i < 4; i++) {
        char c = s[i];
        v = (uint16_t)((v << 4) | (c <= '9' ? c - '0' : c - 'A' + 10));
    }
    return v;
}

// the status bits that belong to each part, for the history of a bit that comes and goes
uint16_t partMask(LinkKind kind, uint8_t part) {
    if (kind == LINK_NANO) {
        return part == 0 ? (uint16_t)(NANO_BME_MISSING | NANO_BME_STUCK | NANO_BME_ASLEEP | NANO_BME_RANGE)
                         : (uint16_t)NANO_SUPPLY_RANGE;
    }
    return part == 0 ? (uint16_t)(STM_SENSOR_MISSING | STM_SENSOR_STUCK | STM_ID_MISMATCH | STM_NO_DATA)
                     : (uint16_t)0;
}

void noteFailure(LinkCore* c, uint32_t nowMs) {
    c->failTimes[c->failIdx] = nowMs;
    c->failIdx = (uint8_t)((c->failIdx + 1) % 3);
    if (c->failCount < 3) c->failCount++;
    rwAdd(&c->rate, nowMs, 0, 1);
}

Outcome reject(LinkCore* c, uint32_t nowMs, uint32_t* counter) {
    (*counter)++;
    noteFailure(c, nowMs);
    return OUT_REJECTED;
}

// sequence and restart bookkeeping for one checksummed data line
void trackSequence(LinkCore* c, uint16_t seq, uint32_t up, uint32_t nowMs) {
    if (c->haveSeq) {
        uint16_t expected = (uint16_t)(c->lastSeq + 1);
        if (seq != expected) {
            // a restart needs SEQ to have gone back. UP going back or both small says the
            // satellite itself restarted and did not just miss lines.
            bool restart = seq <= c->lastSeq &&
                           (up < c->lastUp ||
                            (seq <= LINK_RESTART_SEQ_MAX && up <= LINK_RESTART_UP_MAX));
            if (restart) {
                c->stats.restarts++;
            } else {
                c->stats.gaps++;
                // the lines that went missing count against the link's quality
                uint16_t lost = (uint16_t)(seq - expected);
                rwAdd(&c->rate, nowMs, 0, lost <= 1000 ? lost : 1);
            }
        }
    }
    c->haveSeq = true;
    c->lastSeq = seq;
    c->lastUp  = up;
}

}  // namespace

bool lcLegacyOpen(const LinkCore* c) {
    return !c->sawChecksum && !c->seenSincePower;
}

uint32_t lcParseFailures(const LinkCore* c) {
    return c->stats.format + c->stats.overlong;
}

void lcInit(LinkCore* c, LinkKind kind, uint32_t nowMs, bool seenSincePower) {
    memset(c, 0, sizeof *c);
    c->kind = kind;
    c->seenSincePower = seenSincePower;
    lineReset(&c->buf);
    linkReset(&c->watch, nowMs);
    rwInit(&c->rate, nowMs);
    c->lastPingMs = nowMs;
    c->latched    = HS_OK;
}

void lcNoteLevel(LinkCore* c, bool high, uint32_t nowMs) {
    linkNoteLevel(&c->watch, high, nowMs);
}

Outcome lcFeedByte(LinkCore* c, uint8_t byte, uint32_t nowMs) {
    // a printable byte is data from the far end. a zero byte or a bare line end is not.
    if (byte >= 0x20) linkNoteByte(&c->watch, nowMs);
    LineEvent ev = lineFeed(&c->buf, byte);
    if (ev == LE_OVERLONG) return reject(c, nowMs, &c->stats.overlong);
    if (ev == LE_LINE) {
        Outcome o = lcHandleLine(c, nowMs);
        lineReset(&c->buf);
        return o;
    }
    return OUT_NONE;
}

Outcome lcHandleLine(LinkCore* c, uint32_t nowMs) {
    char*  line = c->buf.data;
    size_t len  = strlen(line);
    while (len > 0 && line[len - 1] == '\r') line[--len] = 0;
    if (len == 0) return OUT_IGNORED;

    char* star = strchr(line, '*');
    bool  checksummed = false;
    if (star) {
        size_t bodyLen = (size_t)(star - line);
        const char* tail = star + 1;
        // exactly four upper-case hex digits and nothing after them.
        if (strlen(tail) != 4 || !upperHex4(tail)) return reject(c, nowMs, &c->stats.crc);
        if (crc16ccitt((const uint8_t*)line, bodyLen) != hex4(tail)) {
            return reject(c, nowMs, &c->stats.crc);
        }
        *star = 0;
        checksummed = true;
        c->sawChecksum = true;
        c->seenSincePower = true;
    } else if (!lcLegacyOpen(c)) {
        // once a checksummed line has been seen a bare line cannot pass as an old one.
        return reject(c, nowMs, &c->stats.crc);
    }

    // a pong answers the outstanding ping and is not a data line
    if (checksummed && strncmp(line, "PONG:", 5) == 0) {
        uint32_t n;
        if (!parseUInt(line + 5, 65535, &n)) return reject(c, nowMs, &c->stats.format);
        if (c->pingOutstanding && n == c->outstandingN) {
            c->pingOutstanding = false;
            c->missed = 0;
            c->stats.pongsRcvd++;
            return OUT_PONG;
        }
        return OUT_IGNORED;
    }

    uint16_t seq = 0;
    bool ok;
    if (checksummed) {
        Fields fs;
        if (!tokenise(line, &fs)) return reject(c, nowMs, &c->stats.format);
        ok = (c->kind == LINK_NANO) ? parseNano(fs, &c->nano, &seq)
                                    : parseStm32(fs, &c->stm, &seq);
    } else {
        ok = (c->kind == LINK_NANO) ? parseNanoLegacy(line, &c->nano)
                                    : parseStm32Legacy(line, &c->stm);
    }
    if (!ok) return reject(c, nowMs, &c->stats.format);

    c->stats.good++;
    c->hasReading = true;
    if (c->latched != HS_OK) c->missed = 0;   // pings missed while the link was dead do not count
    c->latched    = HS_OK;
    linkNoteValid(&c->watch, nowMs);
    rwAdd(&c->rate, nowMs, 1, 0);
    if (checksummed) {
        uint16_t st = (c->kind == LINK_NANO) ? c->nano.st : c->stm.st;
        uint32_t up = (c->kind == LINK_NANO) ? c->nano.up : c->stm.up;
        // a bit counts as a fault only when it is set on two lines in a row
        c->stStable = st & c->prevSt;
        c->prevSt   = st;
        for (uint8_t part = 0; part < 2; part++) {
            uint16_t mask = partMask(c->kind, part);
            c->partHist[part] = (uint16_t)(((c->partHist[part] << 1) | ((st & mask) ? 1 : 0)) & 0x3FF);
        }
        trackSequence(c, seq, up, nowMs);
    }
    return OUT_GOOD;
}

// ─── pings ───────────────────────────────────────────────────────────────────
bool lcPingDue(LinkCore* c, uint32_t nowMs, char* out, size_t cap) {
    if ((uint32_t)(nowMs - c->lastPingMs) < LINK_PING_INTERVAL_MS) return false;
    // the previous ping, if it is still outstanding, never got an answer.
    if (c->pingOutstanding && c->missed < 255) c->missed++;
    c->lastPingMs      = nowMs;
    c->outstandingN    = c->nextPing;
    c->nextPing        = (uint16_t)(c->nextPing + 1);
    c->pingOutstanding = true;
    c->stats.pingsSent++;
    snprintf(out, cap, "PING:%u\n", (unsigned)c->outstandingN);
    return true;
}

uint8_t lcPingsUnanswered(const LinkCore* c, uint32_t nowMs) {
    uint16_t n = c->missed;
    if (c->pingOutstanding && (uint32_t)(nowMs - c->lastPingMs) >= LINK_PONG_WINDOW_MS) n++;
    return n > 255 ? 255 : (uint8_t)n;
}

// ─── state ───────────────────────────────────────────────────────────────────
HealthState lcState(LinkCore* c, uint32_t nowMs) {
    rwTick(&c->rate, nowMs);
    HealthState base = linkState(&c->watch, nowMs, LINK_LINE_LOW_MS,
                                 LINK_LINE_LOW_MIN_SAMPLES, LINK_SILENT_MS);
    if (base == HS_LINE_LOW) {
        c->hasReading = false;
        return HS_LINE_LOW;
    }

    // forget failures older than the window, so a stale entry is never compared again
    while (c->failCount > 0 &&
           (uint32_t)(nowMs - c->failTimes[(c->failIdx + 3 - c->failCount) % 3]) > LINK_SILENT_MS) {
        c->failCount--;
    }

    HealthState result = HS_OK;
    if (base == HS_SILENT) {
        // three lines failed within the window and bytes are still arriving
        bool failing = c->failCount >= 3 &&
                       (uint32_t)(nowMs - c->failTimes[c->failIdx]) <= LINK_SILENT_MS;
        bool bytes   = (uint32_t)(nowMs - c->watch.lastByteMs) < LINK_SILENT_MS;
        result = (failing && bytes) ? HS_GARBAGE : HS_SILENT;
        c->latched = result;
    } else if (c->latched != HS_OK) {
        // the link was declared dead and no valid line has come since.
        result = c->latched;
    }
    if (result != HS_OK) {
        c->hasReading = false;
        // the satellite may well answer pings. the ones missed while the link was dead do not
        // count against it when it comes back
        c->missed = 0;
        return result;
    }

    // data arrives but the satellite never answers a ping. only a satellite that has sent a
    // checksummed line can answer, so an old-format one is never called one_way.
    if (c->sawChecksum && lcPingsUnanswered(c, nowMs) >= LINK_ONE_WAY_PINGS) return HS_ONE_WAY;
    // lines arrive but a fifth or more of them are lost or failed
    if (rwLossy(&c->rate, nowMs, LINK_RATE_MIN_LINES)) return HS_INTERMITTENT;
    return HS_OK;
}

LinkHealth lcHealth(LinkCore* c, uint32_t nowMs) {
    LinkHealth h;
    h.link  = lcState(c, nowMs);
    h.partA = HS_OK;
    h.partB = HS_OK;
    bool usable = (h.link == HS_OK || h.link == HS_ONE_WAY || h.link == HS_INTERMITTENT) &&
                  c->hasReading;
    if (!usable) return h;
    if (c->kind == LINK_NANO) {
        h.partA = nanoBmeState(c->stStable);
        h.partB = nanoSupplyState(c->stStable);
    } else {
        h.partA = stm32MpuState(c->stStable);
    }
    // a bit that comes and goes never makes two in a row, so the debounce above never sees it.
    // the values vanish from posts, so it needs a reason too
    if (h.partA == HS_OK && lcHistIntermittent(c->partHist[0])) h.partA = HS_INTERMITTENT;
    if (h.partB == HS_OK && lcHistIntermittent(c->partHist[1])) h.partB = HS_INTERMITTENT;
    return h;
}

bool lcHistIntermittent(uint16_t hist) {
    hist &= 0x3FF;
    int n = 0;
    for (uint16_t h = hist; h; h >>= 1) n += h & 1;
    return n >= 3;
}
