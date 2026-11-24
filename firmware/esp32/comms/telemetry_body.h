// telemetry_body.h - builds the JSON the hub posts. it takes plain values in a struct and uses
// no Arduino types, so the same function runs in the firmware and in the host tests
// (test_host/test_body.cpp and worst_json.cpp). the firmware fills the struct from its sensors
// and the tests fill it with whatever they want to check.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include "link_protocol.h"

struct TelemetryInput {
    const char* deviceId;
    const char* fw;
    const char* resetReason;
    uint32_t    seq;
    uint32_t    boot;          // 0 when the boot counter is not available
    uint32_t    upSeconds;
    bool        haveRssi;
    int         rssi;
    uint32_t    heapFree;

    // the hub's own sensors. a valid flag says the reading may be posted.
    bool  bmeValid;  float temperature, humidity, pressure;   // humidity is NAN on a BMP280
    bool  mpuValid;  float ax, ay, az, gx, gy, gz;            // gyro in rad/s
    bool  inaValid;  float busVoltage, currentMa, powerMw;
    bool  vlValid;   uint16_t distMm;
    bool  dsValid;   float contactTemp;
    bool  mlxValid;  float irTemp;
    bool  asValid;   float shaftAngle, shaftRpm;
    bool  gasValid;  float gasLevel;  bool gasAlert;
    float moistureLevel;  bool waterAlert;
    float ldrLevel;
    float micLevel;

    // the image and the board disagree about GPIO14 (see sensors/board_check.h)
    bool boardMismatch;
    // "ok", "mismatch" or "unknown". posted only when it is not ok
    const char* boardCheck;
    // warm resets without a trusted temperature reading have reached the limit
    bool resetLoop;
    // bit n set means the set-up with SetupId n is left out until power-up
    uint8_t setupExcludedMask;
    // the hub is posting over plain HTTP (a bench build only)
    bool plainHttp;
    // true on the first body of a boot only: the sensors this image is built without
    bool sendNotFitted;

    // counters for the first bench session. the post task and the main loop fill them in
    uint32_t postOk, postFailed, bodiesReplaced, bodiesTooBig;
    uint32_t stackPostFree, stackLoopFree;     // lowest free stack seen, in bytes
    uint32_t heapMinFree, heapLargestBlock;

    // the two serial links. null when the board has none.
    const LinkCore* nano;
    const LinkCore* stm32;
};

// buildTelemetry fills the document. it returns false when the document overflowed. a sensor
// whose health state is a fault has its readings left out. the water flag is the exception:
// water_detected is always posted because an unplugged probe and a flooded one read the same.
bool buildTelemetry(JsonDocument& doc, const TelemetryInput& in);
