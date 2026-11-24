// corpus_replay.cpp - replays every file in a corpus folder through the hub's satellite line
// parser, the health table and the telemetry body builder, with the address and undefined
// behaviour sanitizers on and no fuzzing engine needed. it is the regression part of the fuzz kept
// for the hub: each file is an input that once broke something or a seed worth keeping.
//
// the first file in the corpus is the input the security audit's fuzzer found: a satellite line with
// a valid checksum and a value such as 9.4e37 made the body builder cast a double to long long out of
// range, which is undefined behaviour (comms/telemetry_body.cpp, now bounded).
//
// file format, the same as the audit's libFuzzer harness: the first byte is a mode (bit 0 picks
// the Black Pill and not the Nano, bit 1 seals each LF-ended line with a valid CRC, bit 2 starts the
// link as one that has already seen a checksummed line) and the rest is what arrives on the wire.
//
// build and run from this folder:
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. -I../.pio/libdeps/esp32dev/ArduinoJson/src corpus_replay.cpp ../comms/telemetry_body.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/corpus_replay" && "${TMPDIR:-/tmp}/corpus_replay" corpus
#include <ArduinoJson.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <string>
#include <vector>

#include "../comms/link_protocol.h"
#include "../comms/telemetry_body.h"
#include "../config.h"
#include "../sensors/health.h"

static void feed(LinkCore* c, const uint8_t* d, size_t n, uint32_t* now) {
    for (size_t i = 0; i < n; i++) {
        lcFeedByte(c, d[i], *now);
        if (c->buf.len > LINK_LINE_MAX - 1) { std::fprintf(stderr, "INVARIANT: line buffer length %u\n", c->buf.len); std::abort(); }
        *now += 1;
    }
}

static int runOne(const uint8_t* data, size_t size) {
    if (size < 1) return 0;
    uint8_t mode = data[0];
    data++; size--;
    LinkKind kind = (mode & 1) ? LINK_STM32 : LINK_NANO;
    static LinkCore c;
    uint32_t now = 1000;
    lcInit(&c, kind, now, (mode & 4) != 0);
    if (mode & 2) {
        size_t start = 0;
        for (size_t i = 0; i <= size; i++) {
            if (i == size || data[i] == '\n') {
                std::string clean;
                for (size_t k = start; k < i; k++) {
                    char ch = (char)data[k];
                    if (ch != '*' && ch != 0 && ch != '\r') clean.push_back(ch);
                }
                char tail[8];
                std::snprintf(tail, sizeof tail, "*%04X\n", crc16ccitt((const uint8_t*)clean.data(), clean.size()));
                clean += tail;
                feed(&c, (const uint8_t*)clean.data(), clean.size(), &now);
                start = i + 1;
            }
        }
    } else {
        feed(&c, data, size, &now);
    }
    healthInit();
    LinkHealth h = lcHealth(&c, now);
    if (kind == LINK_NANO) {
        healthSet(SK_NANO_LINK, h.link, now); healthSet(SK_NANO_BME280, h.partA, now); healthSet(SK_NANO_SUPPLY, h.partB, now);
    } else {
        healthSet(SK_STM32_LINK, h.link, now); healthSet(SK_STM32_MPU6050, h.partA, now);
    }
    TelemetryInput in;
    std::memset(&in, 0, sizeof in);
    in.deviceId = "123e4567-e89b-12d3-a456-426614174000";
    in.fw = "1.0.0"; in.resetReason = "poweron"; in.boardCheck = "ok";
    in.nano  = kind == LINK_NANO ? &c : nullptr;
    in.stm32 = kind == LINK_STM32 ? &c : nullptr;
    static StaticJsonDocument<TELEMETRY_DOC_BYTES> doc;
    static char body[TELEMETRY_BODY_MAX_BYTES];
    doc.clear();
    bool fits = buildTelemetry(doc, in);
    size_t need = measureJson(doc);
    if (fits && need < sizeof body) {
        size_t len = serializeJson(doc, body, sizeof body);
        if (len != need || len >= sizeof body || body[len] != 0) { std::fprintf(stderr, "INVARIANT: body length\n"); std::abort(); }
    }
    return 0;
}

int main(int argc, char** argv) {
    const char* dir = argc > 1 ? argv[1] : "corpus";
    DIR* d = opendir(dir);
    if (!d) { std::fprintf(stderr, "cannot open %s\n", dir); return 2; }
    int files = 0;
    while (dirent* e = readdir(d)) {
        if (e->d_name[0] == '.') continue;
        std::string path = std::string(dir) + "/" + e->d_name;
        FILE* f = std::fopen(path.c_str(), "rb");
        if (!f) continue;
        std::vector<uint8_t> buf;
        uint8_t tmp[4096];
        size_t n;
        while ((n = std::fread(tmp, 1, sizeof tmp, f)) > 0) buf.insert(buf.end(), tmp, tmp + n);
        std::fclose(f);
        runOne(buf.data(), buf.size());
        files++;
    }
    closedir(d);
    std::printf("replayed %d corpus files, no undefined behaviour\n", files);
    return files > 0 ? 0 : 1;
}
