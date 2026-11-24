// worst_json.cpp - host-side check of the largest telemetry body the hub can build, against
// TELEMETRY_BODY_MAX_BYTES and TELEMETRY_DOC_BYTES in config.h. it calls the same function the
// firmware calls (buildTelemetry in comms/telemetry_body.cpp), so the two cannot drift. values
// are the longest a float can print and every counter is at its largest.
//
// build and run from this folder (ArduinoJson is the copy PlatformIO already downloaded):
//   c++ -std=c++17 -Wall -Wextra -I.. -I../.pio/libdeps/esp32dev/ArduinoJson/src worst_json.cpp ../comms/telemetry_body.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/worst_json" && "${TMPDIR:-/tmp}/worst_json"
//   c++ -std=c++17 -Wall -Wextra -DHAS_EXPANDER=1 -DHAS_INPUT_MONITOR=1 -I.. -I../.pio/libdeps/esp32dev/ArduinoJson/src worst_json.cpp ../comms/telemetry_body.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/worst_json_revb" && "${TMPDIR:-/tmp}/worst_json_revb"
// the HAS_ switches default to the present board. build with -DHAS_INPUT_MONITOR=1 and the
// other revised-board switches to measure the revised board (it only adds the supply key).

#include <ArduinoJson.h>

#include <cstdint>
#include <cstdio>
#include <cstring>

#include "../comms/link_protocol.h"
#include "../comms/telemetry_body.h"
#include "../config.h"
#include "../sensors/health.h"

struct Case {
    const char* name;
    bool longValues;
    int  faults;        // how many of the SK_COUNT keys carry a fault
};

static void fillLink(LinkCore* c, LinkKind kind, bool longValues) {
    lcInit(c, kind, 0);
    c->stats.good = c->stats.crc = c->stats.format = c->stats.overlong = 4294967295u;
    c->stats.gaps = c->stats.restarts = 4294967295u;
    c->hasReading = true;
    float v = longValues ? -15.987654f : 1.0f;
    if (kind == LINK_NANO) {
        NanoReading& n = c->nano;
        n.temp = longValues ? -39.123456f : 20.0f;
        n.hum  = longValues ? 99.876543f : 20.0f;
        n.pres = longValues ? 1013.2379f : 1000.0f;
        n.light = longValues ? 1023.1234f : 1.0f;
        n.moist = longValues ? 1023.1234f : 1.0f;
        n.water = true;
        n.st = 65535; n.vccMv = 65535; n.up = 4294967295u;
        n.checksummed = true;
    } else {
        Stm32Reading& s = c->stm;
        s.fft = longValues ? 49.609375f : 1.0f;
        s.mag = v;
        s.vib[0] = s.vib[1] = s.vib[2] = v;
        s.rms[0] = s.rms[1] = s.rms[2] = v;
        s.pk = v;
        s.st = 0; s.up = 4294967295u;
        s.hasVib = true; s.extended = true;
    }
}

static size_t build(const Case& k, size_t* pool, bool* over) {
    static StaticJsonDocument<TELEMETRY_DOC_BYTES> doc;
    static LinkCore nano, stm;
    healthInit();
    // the expander and rail keys can only be set on a board that has the expander
    int faulted = 0;
    for (int i = 0; i < SK_COUNT && faulted < k.faults; i++) {
        if (i >= SK_EXPANDER && !HAS_EXPANDER) continue;
        healthSet((SensorKey)i, HS_OUT_OF_RANGE, 1);
        faulted++;
    }
    // the sensors a fault would hide are posted anyway, so this is an upper bound
    fillLink(&nano, LINK_NANO, k.longValues);
    fillLink(&stm, LINK_STM32, k.longValues);

    TelemetryInput in;
    std::memset(&in, 0, sizeof in);
    bool L = k.longValues;
    in.deviceId = "123e4567-e89b-12d3-a456-426614174000";
    in.fw = "1.0.0";
    in.resetReason = "deepsleep";                  // the longest reason
    in.seq = 4294967295u; in.boot = 4294967295u; in.upSeconds = 4294967295u;
    in.haveRssi = true; in.rssi = -127; in.heapFree = 4294967295u;
    in.bmeValid = true;
    in.temperature = L ? -39.123456f : 21.5f;
    in.humidity    = L ? 99.876543f : 40.0f;
    in.pressure    = L ? 1013.2379f : 1013.0f;
    in.mpuValid = true;
    in.ax = in.ay = in.az = L ? -7.9876543f : 0.01f;
    in.gx = in.gy = in.gz = L ? -8.7266463f : 0.0f;
    in.inaValid = true;
    in.busVoltage = L ? 31.987654f : 12.0f;
    in.currentMa  = L ? -3199.8765f : 100.0f;
    in.powerMw    = L ? -102357.12f : 1200.0f;
    in.vlValid = true;  in.distMm = L ? 8190 : 100;
    in.dsValid = true;  in.contactTemp = L ? -54.9375f : 20.0f;
    in.mlxValid = true; in.irTemp = L ? -69.98999f : 20.0f;
    in.asValid = true;  in.shaftAngle = L ? 359.91211f : 10.0f; in.shaftRpm = L ? -1499.8765f : 0.0f;
    in.gasValid = true; in.gasLevel = L ? 1023.0f : 10.0f; in.gasAlert = false;
    in.moistureLevel = L ? 4095.0f : 10.0f; in.waterAlert = false;
    in.ldrLevel = L ? 4095.0f : 10.0f;
    in.micLevel = L ? 4095.0f : 10.0f;
    in.nano = &nano;
    in.stm32 = &stm;
    in.boardMismatch = true;
    in.postOk = in.postFailed = in.bodiesReplaced = in.bodiesTooBig = 4294967295u;
    in.stackPostFree = in.stackLoopFree = in.heapMinFree = in.heapLargestBlock = 4294967295u;

    // with faults set the builder leaves the faulted sensors out. clear the health states used
    // above for the readings so every field is posted, then put the faults back for the map.
    HealthState saved[SK_COUNT];
    for (int i = 0; i < SK_COUNT; i++) saved[i] = healthState((SensorKey)i);
    healthInit();
    doc.clear();
    buildTelemetry(doc, in);
    // add the faults map the way the builder would for the faulted keys, on top of the full set of fields
    JsonObject faults = doc["faults"];
    for (int i = 0; i < SK_COUNT; i++) {
        if (saved[i] != HS_OK) faults[healthKeyName((SensorKey)i)] = healthStateName(saved[i]);
    }
    *pool = doc.memoryUsage();
    *over = doc.overflowed();
    return measureJson(doc);
}

int main() {
    int bad = 0;
    Case rows[] = {
        {"realistic: every field, short values, no fault",         false, 0},
        {"every field, long values, one fault",                    true,  1},
        {"every field, long values, all faults (impossible)",      true,  SK_COUNT},
    };
    for (const Case& r : rows) {
        size_t pool; bool over;
        size_t n = build(r, &pool, &over);
        bool fits = !over && n < TELEMETRY_BODY_MAX_BYTES;
        std::printf("%-54s body %4zu bytes (limit %d), pool %4zu of %d, overflow %d, %s\n",
                    r.name, n, TELEMETRY_BODY_MAX_BYTES - 1, pool, TELEMETRY_DOC_BYTES, over,
                    fits ? "fits" : "DOES NOT FIT");
        if (!fits) bad++;
    }
    std::printf("%d cases over the limit\n", bad);
    return bad ? 1 : 0;
}
