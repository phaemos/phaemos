// test_body.cpp - host test for the telemetry body builder in comms/telemetry_body.cpp. it is
// the same function the firmware calls, so these cases check what the hub really posts: which
// fields are left out for which fault, the water flag, the sentinel rule, clipping, the links
// object and the faults map.
//
// build and run from this folder (ArduinoJson is the copy PlatformIO already downloaded):
//   c++ -std=c++17 -Wall -Wextra -I.. -I../.pio/libdeps/esp32dev/ArduinoJson/src test_body.cpp ../comms/telemetry_body.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_body" && "${TMPDIR:-/tmp}/test_body"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. -I../.pio/libdeps/esp32dev/ArduinoJson/src test_body.cpp ../comms/telemetry_body.cpp ../comms/link_protocol.cpp ../sensors/health.cpp -o "${TMPDIR:-/tmp}/test_body_san" && "${TMPDIR:-/tmp}/test_body_san"
// the HAS_ switches default to the present board. pass -DHAS_FC28=1 -DHAS_NANO=1 -DHAS_STM32=1 (the
// defaults) for this test. it also builds with -DHAS_INPUT_PULLDOWNS=1.

#include <ArduinoJson.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>

#include "../comms/link_protocol.h"
#include "../comms/telemetry_body.h"
#include "../config.h"
#include "../sensors/fitted.h"
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

// floats go through text, so they are compared with a small tolerance
static bool near(JsonVariantConst v, float f) { return v.is<float>() && std::fabs(v.as<float>() - f) < 1e-3f; }

static std::string withCrc(const std::string& body) {
    char tail[16];
    std::snprintf(tail, sizeof tail, "*%04X\r\n",
                  (unsigned)crc16ccitt((const uint8_t*)body.data(), body.size()));
    return body + tail;
}

static Outcome feed(LinkCore& c, const std::string& s, uint32_t now) {
    Outcome last = OUT_NONE;
    for (char ch : s) {
        Outcome o = lcFeedByte(&c, (uint8_t)ch, now);
        if (o != OUT_NONE) last = o;
    }
    return last;
}

static std::string nanoLine(const char* temp, const char* hum, unsigned st, unsigned seq, unsigned up) {
    char b[200];
    std::snprintf(b, sizeof b,
                  "TEMP:%s,HUM:%s,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:%u,SEQ:%u,UP:%u,VCC:4980",
                  temp, hum, st, seq, up);
    return withCrc(b);
}

static std::string bpLine(unsigned st, unsigned seq, unsigned up) {
    char b[220];
    std::snprintf(b, sizeof b,
                  "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,"
                  "ST:%u,SEQ:%u,UP:%u,MT:0,RF:0,BR:0", st, seq, up);
    return withCrc(b);
}

static void applyLinkHealth(LinkCore* nano, LinkCore* stm, uint32_t now) {
    if (nano) {
        LinkHealth h = lcHealth(nano, now);
        healthSet(SK_NANO_LINK, h.link, now);
        healthSet(SK_NANO_BME280, h.partA, now);
        healthSet(SK_NANO_SUPPLY, h.partB, now);
    }
    if (stm) {
        LinkHealth h = lcHealth(stm, now);
        healthSet(SK_STM32_LINK, h.link, now);
        healthSet(SK_STM32_MPU6050, h.partA, now);
    }
}

static TelemetryInput base(const LinkCore* nano, const LinkCore* stm) {
    TelemetryInput in;
    std::memset(&in, 0, sizeof in);
    in.deviceId = "123e4567-e89b-12d3-a456-426614174000";
    in.fw = "1.0.0";
    in.resetReason = "poweron";
    in.seq = 7; in.boot = 3; in.upSeconds = 120;
    in.haveRssi = true; in.rssi = -61; in.heapFree = 184320;
    in.bmeValid = true; in.temperature = 26.4f; in.humidity = 48.2f; in.pressure = 1012.6f;
    in.mpuValid = true; in.ax = 0.01f; in.ay = -0.02f; in.az = 0.99f; in.gx = 0.1f; in.gy = 0; in.gz = -0.1f;
    in.inaValid = true; in.busVoltage = 11.9f; in.currentMa = 240.5f; in.powerMw = 2862.0f;
    in.vlValid = true; in.distMm = 312;
    in.dsValid = true; in.contactTemp = 31.2f;
    in.mlxValid = true; in.irTemp = 30.8f;
    in.asValid = true; in.shaftAngle = 184.2f; in.shaftRpm = 1480.0f;
    in.gasValid = true; in.gasLevel = 212; in.gasAlert = false;
    in.moistureLevel = 3650; in.waterAlert = false;
    in.ldrLevel = 1800; in.micLevel = 42;
    in.nano = nano; in.stm32 = stm;
    return in;
}

static StaticJsonDocument<TELEMETRY_DOC_BYTES> g_doc;

static bool build(const TelemetryInput& in, StaticJsonDocument<4096>* parsed) {
    g_doc.clear();
    bool ok = buildTelemetry(g_doc, in);
    std::string body;
    serializeJson(g_doc, body);
    parsed->clear();
    CHECK(!deserializeJson(*parsed, body));
    return ok;
}

static void testAllWell() {
    healthInit();
    LinkCore nano, stm;
    lcInit(&nano, LINK_NANO, 0);
    lcInit(&stm, LINK_STM32, 0);
    feed(nano, nanoLine("25.1", "50.7", 0, 12, 26), 1000);
    feed(stm, bpLine(0, 7, 9), 1000);
    applyLinkHealth(&nano, &stm, 1000);
    StaticJsonDocument<4096> d;
    CHECK(build(base(&nano, &stm), &d));
    CHECK(d["device_id"] == "123e4567-e89b-12d3-a456-426614174000");
    CHECK(d["node_type"] == "esp32");
    CHECK(near(d["temperature"], 26.4f) && d["distance_mm"] == 312 && near(d["shaft_rpm"], 1480.0f));
    CHECK(d["seq"] == 7 && d["boot"] == 3 && d["up"] == 120);
    CHECK(d["reset_reason"] == "poweron" && d["rssi"] == -61 && d["heap_free"] == 184320 && d["fw"] == "1.0.0");
    CHECK(!d.containsKey("ts"));
    CHECK(d["faults"].is<JsonObject>() && d["faults"].size() == 0);
    CHECK(near(d["nano_temp"], 25.1f) && near(d["nano_hum"], 50.7f) && d["nano_light"] == 300);
    CHECK(near(d["fft_peak_hz"], 12.5f) && near(d["vib_rms_z"], 0.031f) && near(d["vib_peak"], 0.094f));
    CHECK(near(d["stm32_vib_x"], 0.02f) && near(d["stm32_vib_y"], -0.01f) && near(d["stm32_vib_z"], 1.01f));
    CHECK(d["vib_clipping"] == false);
    CHECK(d["links"]["nano"]["ok"] == 1 && d["links"]["nano"]["crc"] == 0 && d["links"]["nano"]["fmt"] == 0);
    CHECK(d["links"]["nano"]["st"] == 0 && d["links"]["nano"]["up"] == 26 && d["links"]["nano"]["vcc"] == 4980);
    CHECK(d["links"]["stm32"]["ok"] == 1 && d["links"]["stm32"]["up"] == 9);
    CHECK(!d["links"]["stm32"].containsKey("vcc"));
    // the boot count and the signal are left out when they are not available
    TelemetryInput in = base(&nano, &stm);
    in.boot = 0; in.haveRssi = false;
    CHECK(build(in, &d));
    CHECK(!d.containsKey("boot") && !d.containsKey("rssi"));
}

#if HAS_FC28
static void testWater() {
    healthInit();
    StaticJsonDocument<4096> d;
    TelemetryInput in = base(nullptr, nullptr);
    // an unplugged input withholds the level only. the water flag is still posted
    healthSet(SK_FC28, HS_UNPLUGGED, 1);
    in.moistureLevel = 0; in.waterAlert = true;
    CHECK(build(in, &d));
    CHECK(!d.containsKey("moisture_level"));
    CHECK(d["water_detected"] == true);
    CHECK(d["faults"]["fc28"] == "unplugged");
    // posted false too, so the backend always has the flag
    in.waterAlert = false;
    CHECK(build(in, &d));
    CHECK(d["water_detected"] == false && !d.containsKey("moisture_level"));
    // plugged in: both go out
    healthSet(SK_FC28, HS_OK, 2);
    in.moistureLevel = 3650;
    CHECK(build(in, &d));
    CHECK(d["moisture_level"] == 3650 && d["water_detected"] == false);
}
#endif

static void testHubSensorFaults() {
    healthInit();
    StaticJsonDocument<4096> d;
    TelemetryInput in = base(nullptr, nullptr);
    // a faulted sensor has its readings left out and is named in the faults map
    in.bmeValid = false;
    healthSet(SK_BME280, HS_INTERMITTENT, 1);
    healthSet(SK_MQ2, HS_WARMING_UP, 1);
    in.gasValid = false;
    CHECK(build(in, &d));
    CHECK(!d.containsKey("temperature") && !d.containsKey("humidity") && !d.containsKey("pressure"));
    CHECK(!d.containsKey("gas_level") && !d.containsKey("gas_alert"));
    CHECK(d["faults"]["bme280"] == "intermittent" && d["faults"]["mq2"] == "warming_up");
    CHECK(d.containsKey("vibration_z") && d.containsKey("distance_mm"));
    // a BMP280 has no humidity
    healthInit();
    in = base(nullptr, nullptr);
    in.humidity = NAN;
    CHECK(build(in, &d));
    CHECK(d.containsKey("temperature") && !d.containsKey("humidity"));
    // an unplugged microphone is left out and the LDR never is
    healthSet(SK_MAX4466, HS_UNPLUGGED, 1);
    CHECK(build(in, &d));
    CHECK(!d.containsKey("sound_level") && d.containsKey("light_level"));
    CHECK(d["faults"]["max4466"] == "unplugged");
}

static void testNanoSentinel() {
    healthInit();
    StaticJsonDocument<4096> d;
    LinkCore nano;
    lcInit(&nano, LINK_NANO, 0);
    // a real -1.0 degC on a checksummed line is a reading
    feed(nano, nanoLine("-1.0", "60.0", 0, 0, 2), 1000);
    applyLinkHealth(&nano, nullptr, 1000);
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(near(d["nano_temp"], -1.0f) && near(d["nano_hum"], 60.0f) && near(d["nano_pres"], 1006.6f));
    // humidity under zero means no humidity element: only humidity is left out
    feed(nano, nanoLine("21.0", "-1", 0, 1, 4), 3000);
    applyLinkHealth(&nano, nullptr, 3000);
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(near(d["nano_temp"], 21.0f) && !d.containsKey("nano_hum") && d.containsKey("nano_pres"));
    // the status bits decide. BME_MISSING on the line itself leaves the three values out at
    // once, even before the two-line debounce has made it a fault
    feed(nano, nanoLine("-1", "-1", NANO_BME_MISSING, 2, 6), 5000);
    applyLinkHealth(&nano, nullptr, 5000);
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(!d.containsKey("nano_temp") && !d.containsKey("nano_hum") && !d.containsKey("nano_pres"));
    CHECK(d.containsKey("nano_light") && d.containsKey("nano_moist"));
    CHECK(d["faults"].size() == 0);                       // one line is a glitch
    // the second line makes it a fault
    feed(nano, nanoLine("-1", "-1", NANO_BME_MISSING, 3, 8), 7000);
    applyLinkHealth(&nano, nullptr, 7000);
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(d["faults"]["nano_bme280"] == "missing");
    // a single transient ASLEEP line is not posted as a fault
    healthInit();
    LinkCore n2;
    lcInit(&n2, LINK_NANO, 0);
    feed(n2, nanoLine("20.0", "40.0", 0, 0, 2), 1000);
    feed(n2, nanoLine("-1", "-1", NANO_BME_ASLEEP, 1, 4), 3000);
    applyLinkHealth(&n2, nullptr, 3000);
    CHECK(build(base(&n2, nullptr), &d));
    CHECK(d["faults"].size() == 0);
    feed(n2, nanoLine("20.0", "40.0", 0, 2, 6), 5000);
    applyLinkHealth(&n2, nullptr, 5000);
    CHECK(build(base(&n2, nullptr), &d));
    CHECK(d["faults"].size() == 0 && near(d["nano_temp"], 20.0f));
    // an old-format line still uses -1 as no value
    healthInit();
    LinkCore old;
    lcInit(&old, LINK_NANO, 0);
    feed(old, "TEMP:-1,HUM:-1,PRES:-1,LIGHT:5,MOIST:6,WATER:1\r\n", 1000);
    applyLinkHealth(&old, nullptr, 1000);
    CHECK(build(base(&old, nullptr), &d));
    CHECK(!d.containsKey("nano_temp") && !d.containsKey("nano_hum") && !d.containsKey("nano_pres"));
    CHECK(d["nano_light"] == 5 && d["nano_water"] == true);
    // and an old-format line carries no st, up or vcc in links
    CHECK(!d["links"]["nano"].containsKey("st") && !d["links"]["nano"].containsKey("vcc"));
    CHECK(d["links"]["nano"]["ok"] == 1);
}

static void testClipping() {
    healthInit();
    StaticJsonDocument<4096> d;
    LinkCore stm;
    lcInit(&stm, LINK_STM32, 0);
    // clipping on two lines in a row: the values are forwarded, vib_clipping is true and there
    // is no fault key for it
    feed(stm, bpLine(STM_CLIPPING, 0, 1), 1000);
    feed(stm, bpLine(STM_CLIPPING, 1, 2), 2000);
    applyLinkHealth(nullptr, &stm, 2000);
    CHECK(build(base(nullptr, &stm), &d));
    CHECK(d["vib_clipping"] == true);
    CHECK(d.containsKey("fft_peak_hz") && d.containsKey("vib_magnitude") && d.containsKey("vib_rms_x"));
    CHECK(d.containsKey("vib_peak") && d.containsKey("stm32_vib_z"));
    CHECK(!d["faults"].containsKey("stm32_mpu6050") && d["faults"].size() == 0);
    // clearing: false again
    feed(stm, bpLine(0, 2, 3), 3000);
    applyLinkHealth(nullptr, &stm, 3000);
    CHECK(build(base(nullptr, &stm), &d));
    CHECK(d["vib_clipping"] == false);

    // a missing sensor leaves the vibration values out. the line carries the bit at once
    feed(stm, bpLine(STM_SENSOR_MISSING, 3, 4), 4000);
    feed(stm, bpLine(STM_SENSOR_MISSING, 4, 5), 5000);
    applyLinkHealth(nullptr, &stm, 5000);
    CHECK(build(base(nullptr, &stm), &d));
    CHECK(!d.containsKey("fft_peak_hz") && !d.containsKey("vib_rms_x") && !d.containsKey("stm32_vib_x"));
    CHECK(d["faults"]["stm32_mpu6050"] == "missing");
    // no complete window: intermittent and the values are not used
    feed(stm, bpLine(STM_NO_DATA, 5, 6), 6000);
    feed(stm, bpLine(STM_NO_DATA, 6, 7), 7000);
    applyLinkHealth(nullptr, &stm, 7000);
    CHECK(build(base(nullptr, &stm), &d));
    CHECK(!d.containsKey("vib_peak"));
    CHECK(d["faults"]["stm32_mpu6050"] == "intermittent");
    // a dead link: nothing forwarded and no vib_clipping at all
    healthInit();
    LinkCore dead;
    lcInit(&dead, LINK_STM32, 0);
    feed(dead, bpLine(0, 0, 1), 1000);
    applyLinkHealth(nullptr, &dead, 1000);
    CHECK(lcState(&dead, 20000) == HS_SILENT);
    applyLinkHealth(nullptr, &dead, 20000);
    CHECK(build(base(nullptr, &dead), &d));
    CHECK(!d.containsKey("vib_clipping") && !d.containsKey("fft_peak_hz"));
    CHECK(d["faults"]["stm32_link"] == "silent");
    // and the links counters stay while the last status, uptime and supply are left out
    CHECK(d["links"]["stm32"]["ok"] == 1);
    CHECK(!d["links"]["stm32"].containsKey("st") && !d["links"]["stm32"].containsKey("up"));
}

static void testLinksObject() {
    healthInit();
    StaticJsonDocument<4096> d;
    LinkCore nano;
    lcInit(&nano, LINK_NANO, 0);
    // before any line the counters are there and nothing stale is
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(d["links"]["nano"]["ok"] == 0 && d["links"]["nano"]["crc"] == 0);
    CHECK(!d["links"]["nano"].containsKey("st") && !d["links"]["nano"].containsKey("up"));
    // parse failures are posted beside crc, because garbage is fed by both
    feed(nano, withCrc("TEMP:1"), 1000);
    feed(nano, "TEMP:1*0000\r\n", 1100);
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(d["links"]["nano"]["crc"] == 1 && d["links"]["nano"]["fmt"] == 1);
}

static void testFaultsMapIsComplete() {
    healthInit();
    StaticJsonDocument<4096> d;
    for (int k = 0; k < SK_COUNT; k++) healthSet((SensorKey)k, HS_OUT_OF_RANGE, 1);
    CHECK(build(base(nullptr, nullptr), &d));
    CHECK(d["faults"].size() == (size_t)SK_COUNT);
    CHECK(d["faults"].containsKey("nano_bme280") && d["faults"].containsKey("stm32_mpu6050"));
    CHECK(d["faults"].containsKey("nano_supply") && d["faults"].containsKey("supply"));
    CHECK(d["faults"].containsKey("expander") && d["faults"].containsKey("aux_rail") &&
          d["faults"].containsKey("sens_rail") && d["faults"].containsKey("enable_rail"));
    CHECK(SK_COUNT == 25);
}

// the present board never sets the expander or rail keys, so its body has none of them: not in the
// faults map and not in the not_fitted list. the keys are not part of what that body says.
static void testPresentBoardBodyHasNoExpanderKeys() {
    healthInit();
    TelemetryInput in = base(nullptr, nullptr);
    in.sendNotFitted = true;
    StaticJsonDocument<4096> d;
    CHECK(build(in, &d));
    CHECK(d["faults"].size() == 0);
    for (JsonVariant v : d["not_fitted"].as<JsonArray>()) {
        const char* n = v.as<const char*>();
        CHECK(std::strcmp(n, "expander") != 0 && std::strstr(n, "_rail") == nullptr);
    }
    // only the keys that were fitted-off before are listed. the 12 V monitor is the one on the present board
    CHECK(d["not_fitted"].size() == 1 && d["not_fitted"][0] == "supply");
}

static void testOverflowIsReported() {
    healthInit();
    StaticJsonDocument<64> tiny;
    bool ok = buildTelemetry(tiny, base(nullptr, nullptr));
    CHECK(!ok && tiny.overflowed());
}


static void testDiagAndBoard() {
    healthInit();
    StaticJsonDocument<4096> d;
    TelemetryInput in = base(nullptr, nullptr);
    in.postOk = 120; in.postFailed = 3; in.bodiesReplaced = 7; in.bodiesTooBig = 1;
    in.stackPostFree = 4100; in.stackLoopFree = 2900; in.heapMinFree = 150000; in.heapLargestBlock = 110592;
    CHECK(build(in, &d));
    CHECK(d["diag"]["post_ok"] == 120 && d["diag"]["post_failed"] == 3 && d["diag"]["replaced"] == 7);
    CHECK(d["diag"]["too_big"] == 1 && d["diag"]["stack_post"] == 4100 && d["diag"]["stack_loop"] == 2900);
    CHECK(d["diag"]["heap_min"] == 150000 && d["diag"]["heap_block"] == 110592);
    // the board mismatch is posted only when there is one
    CHECK(!d.containsKey("board_mismatch"));
    in.boardMismatch = true;
    CHECK(build(in, &d));
    CHECK(d["board_mismatch"] == true);
    // the new fields appear only when there is something to say
    in = base(nullptr, nullptr);
    CHECK(build(in, &d));
    CHECK(!d.containsKey("board_check") && !d.containsKey("reset_loop") &&
          !d.containsKey("setup_excluded") && !d.containsKey("not_fitted"));
    in.boardCheck = "ok";
    CHECK(build(in, &d) && !d.containsKey("board_check"));
    in.boardCheck = "unknown";
    in.resetLoop = true;
    in.setupExcludedMask = (1u << 0) | (1u << 6);
    CHECK(build(in, &d));
    CHECK(d["board_check"] == "unknown" && d["reset_loop"] == true);
    CHECK(d["setup_excluded"].size() == 2 && d["setup_excluded"][0] == "bme280" && d["setup_excluded"][1] == "ds18b20");
    // not_fitted names the sensors this image is built without, once. on the present board that
    // includes the 12 V monitor, which only the revised board has
    in.sendNotFitted = true;
    CHECK(build(in, &d));
    size_t expect = 0;
    for (uint8_t k = 0; k < SK_COUNT; k++) if (!sensorFitted((SensorKey)k)) expect++;
    CHECK(d.containsKey("not_fitted") && d["not_fitted"].size() == expect);
}

static void testRounding() {
    healthInit();
    TelemetryInput in = base(nullptr, nullptr);
    in.temperature = 26.4f;           // a float prints as 26.399999618530273 or 26.39999962
    in.humidity = 48.2f;
    in.pressure = 1012.6f;
    in.ax = 0.012345678f;
    in.currentMa = 240.5123f;
    g_doc.clear();
    buildTelemetry(g_doc, in);
    std::string body;
    serializeJson(g_doc, body);
    CHECK(body.find("\"temperature\":26.4,") != std::string::npos);
    CHECK(body.find("\"humidity\":48.2,") != std::string::npos);
    CHECK(body.find("\"pressure\":1012.6,") != std::string::npos);
    CHECK(body.find("\"vibration_x\":0.012,") != std::string::npos);
    CHECK(body.find("\"current_ma\":240.5,") != std::string::npos);
    // nothing in the body carries a run of nine digits
    CHECK(body.find("0000") == std::string::npos && body.find("9999") == std::string::npos);
    // negatives round the same way
    in.temperature = -1.005f;
    g_doc.clear();
    buildTelemetry(g_doc, in);
    body.clear();
    serializeJson(g_doc, body);
    CHECK(body.find("\"temperature\":-1") != std::string::npos);
}

static void testIntermittentPartWithholds() {
    healthInit();
    StaticJsonDocument<4096> d;
    LinkCore nano;
    lcInit(&nano, LINK_NANO, 0);
    unsigned seq = 0;
    uint32_t t = 1000;
    for (int i = 0; i < 12; i++, t += 2000) {
        feed(nano, nanoLine("21.0", "40.0", (i % 2) ? NANO_BME_MISSING : 0, seq++, t / 1000), t);
        applyLinkHealth(&nano, nullptr, t);
    }
    CHECK(healthState(SK_NANO_BME280) == HS_INTERMITTENT);
    CHECK(build(base(&nano, nullptr), &d));
    CHECK(d["faults"]["nano_bme280"] == "intermittent");
    CHECK(!d.containsKey("nano_temp") && !d.containsKey("nano_hum") && !d.containsKey("nano_pres"));
    CHECK(d.containsKey("nano_light") && d.containsKey("nano_moist"));
}

// L22: a float cast to an integer outside its range is undefined behaviour. one UART line with a
// valid checksum can carry TEMP:1e30, so every value is bounded before the cast. these run under the
// undefined behaviour sanitizer, which stops on the first bad cast.
static void testAbsurdValues() {
    healthInit();
    StaticJsonDocument<4096> d;
    const float absurd[] = { 1e30f, -1e30f, 3.4e38f, -3.4e38f, 9.3e18f, -9.3e18f, 9.3e15f, 1e15f, 1e14f,
                             std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(),
                             std::numeric_limits<float>::quiet_NaN(), 0.0f, -0.0f, 1e-30f };
    for (float v : absurd) {
        TelemetryInput in = base(nullptr, nullptr);
        in.temperature = in.humidity = in.pressure = v;
        in.ax = in.ay = in.az = v; in.gx = in.gy = in.gz = v;
        in.busVoltage = in.currentMa = in.powerMw = v;
        in.contactTemp = in.irTemp = in.shaftAngle = in.shaftRpm = v;
        in.gasLevel = in.moistureLevel = in.ldrLevel = in.micLevel = v;
        build(in, &d);
    }
    // the same through the link: a satellite line with a valid checksum and absurd numbers
    LinkCore nano, stm;
    lcInit(&nano, LINK_NANO, 0);
    lcInit(&stm, LINK_STM32, 0);
    feed(nano, nanoLine("1e30", "50.7", 0, 12, 26), 1000);
    feed(nano, nanoLine("-3.4e38", "1e30", 0, 13, 27), 1100);
    feed(stm, bpLine(0, 7, 9), 1000);
    applyLinkHealth(&nano, &stm, 1100);
    CHECK(build(base(&nano, &stm), &d));
    // a rounded value is still a number of the right size and ordinary values are unchanged
    TelemetryInput in = base(nullptr, nullptr);
    in.temperature = 26.4f;
    CHECK(build(in, &d) && near(d["temperature"], 26.4f));
    in.temperature = 1e30f;
    CHECK(build(in, &d));
}

static void testPlainHttpField() {
    healthInit();
    StaticJsonDocument<4096> d;
    TelemetryInput in = base(nullptr, nullptr);
    CHECK(build(in, &d) && !d.containsKey("plain_http"));
    in.plainHttp = true;
    CHECK(build(in, &d) && d["plain_http"] == true);
}

int main() {
    testAllWell();
#if HAS_FC28
    testWater();
#endif
    testHubSensorFaults();
    testNanoSentinel();
    testClipping();
    testLinksObject();
    testFaultsMapIsComplete();
    testPresentBoardBodyHasNoExpanderKeys();
    testOverflowIsReported();
    testDiagAndBoard();
    testRounding();
    testIntermittentPartWithholds();
    testAbsurdValues();
    testPlainHttpField();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
