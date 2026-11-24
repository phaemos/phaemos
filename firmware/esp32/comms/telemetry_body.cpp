#include "telemetry_body.h"

#include <string.h>

#include "../sensors/fitted.h"

#include <math.h>

#include "../config.h"
#include "../sensors/health.h"

namespace {

const double RAD_TO_DEG_D = 57.295779513082320876798154814105;

// round to a sensible number of decimals. a float posted as it is prints nine digits
// (25.10000038), which costs body size and means nothing. a double that has been rounded prints
// the short form.
double R(double v, int decimals) {
    double scale = 1.0;
    for (int i = 0; i < decimals; i++) scale *= 10.0;
    double scaled = v * scale + (v < 0 ? -0.5 : 0.5);
    // a float to integer cast outside the integer's range is undefined behaviour. one UART line
    // with a valid checksum can carry TEMP:1e30, so every value is bounded before the cast. a
    // value too large to round was never a reading with decimals anyway and a NaN or an
    // infinity fails the comparison and is passed through for the JSON writer to handle
    if (!(scaled > -1e15 && scaled < 1e15)) return v;
    return (double)(long long)scaled / scale;
}

// a link whose lines can be used. one_way and intermittent still deliver data.
bool linkUsable(SensorKey key) {
    HealthState st = healthState(key);
    return st == HS_OK || st == HS_ONE_WAY || st == HS_INTERMITTENT;
}

void addLinkCounters(JsonObject links, const char* name, const LinkCore& c, bool withReading,
                     uint16_t st, uint32_t up, uint16_t vccMv, bool hasVcc) {
    JsonObject o = links.createNestedObject(name);
    o["ok"]       = c.stats.good;
    o["crc"]      = c.stats.crc;
    // lines that passed their checksum but did not parse (or ran too long). the garbage rule is
    // fed by these as well as by crc, so both are posted.
    o["fmt"]      = lcParseFailures(&c);
    o["gaps"]     = c.stats.gaps;
    o["restarts"] = c.stats.restarts;
    // the last status, uptime and supply are left out until a line has arrived and again when
    // the link is dead, so they are never stale.
    if (withReading) {
        o["st"] = st;
        o["up"] = up;
        if (hasVcc) o["vcc"] = vccMv;
    }
}

}  // namespace

bool buildTelemetry(JsonDocument& doc, const TelemetryInput& in) {
    doc["device_id"] = in.deviceId;
    doc["node_type"] = "esp32";

    // BME280 (humidity is NAN on a BMP280)
    if (in.bmeValid) {
        doc["temperature"] = R(in.temperature, 2);
        if (!isnan(in.humidity)) doc["humidity"] = R(in.humidity, 1);
        doc["pressure"]    = R(in.pressure, 2);
    }

    // MPU6050 - the backend names the acceleration axes vibration_x/y/z in g
    // and wants gyro in degrees per second, but the driver gives rad/s.
    if (in.mpuValid) {
        doc["vibration_x"] = R(in.ax, 3);
        doc["vibration_y"] = R(in.ay, 3);
        doc["vibration_z"] = R(in.az, 3);
        doc["gyro_x"]      = R(in.gx * RAD_TO_DEG_D, 2);
        doc["gyro_y"]      = R(in.gy * RAD_TO_DEG_D, 2);
        doc["gyro_z"]      = R(in.gz * RAD_TO_DEG_D, 2);
    }

    if (in.inaValid) {
        doc["bus_voltage"] = R(in.busVoltage, 3);
        doc["current_ma"]  = R(in.currentMa, 1);
        doc["power_mw"]    = R(in.powerMw, 1);
    }

    if (in.vlValid)  doc["distance_mm"]    = in.distMm;
    if (in.dsValid)  doc["contact_temp"]   = R(in.contactTemp, 2);
    if (in.mlxValid) doc["ir_temperature"] = R(in.irTemp, 2);

    if (in.asValid) {
        doc["shaft_angle"] = R(in.shaftAngle, 1);
        doc["shaft_rpm"]   = R(in.shaftRpm, 1);
    }

    // MQ2 - both fields are left out while the heater warms up and while the sensor is in
    // fault, because neither reading means anything then.
    if (in.gasValid) {
        doc["gas_level"] = R(in.gasLevel, 0);
        doc["gas_alert"] = in.gasAlert;
    }

#if HAS_FC28
    // FC28 - an unplugged input withholds the level only. the water flag is always sent: an
    // unplugged input and a probe flooded with a conductive liquid read the same on this
    // circuit, so the leak alarm wins and the backend alarms on the flag.
    if (healthState(SK_FC28) == HS_OK) doc["moisture_level"] = R(in.moistureLevel, 0);
    doc["water_detected"] = in.waterAlert;
#endif

    // LDR and microphone
    doc["light_level"] = R(in.ldrLevel, 0);
    if (healthState(SK_MAX4466) == HS_OK) doc["sound_level"] = R(in.micLevel, 0);

    // Nano data. a value is usable when the line's own status bits say so (the current line,
    // before any debounce) and the sensor is not already marked bad. on a checksummed line
    // the status bits decide and never the value, so a real -1.0 degC is a reading. the -1
    // form is believed only on an old-format line. humidity under zero means no humidity
    // element (a BMP280).
#if HAS_NANO
    if (in.nano && in.nano->hasReading && linkUsable(SK_NANO_LINK)) {
        const NanoReading& n = in.nano->nano;
        if (nanoBmeState(n.st) == HS_OK && healthState(SK_NANO_BME280) == HS_OK) {
            if (n.checksummed) {
                doc["nano_temp"] = R(n.temp, 2);
                doc["nano_pres"] = R(n.pres, 2);
                if (n.hum >= 0.0f) doc["nano_hum"] = R(n.hum, 1);
            } else {
                if (n.temp != -1.0f) doc["nano_temp"] = R(n.temp, 2);
                if (n.hum  != -1.0f) doc["nano_hum"]  = R(n.hum, 1);
                if (n.pres != -1.0f) doc["nano_pres"] = R(n.pres, 2);
            }
        }
        doc["nano_light"] = R(n.light, 0);
        doc["nano_moist"] = R(n.moist, 0);
        doc["nano_water"] = n.water;
    }
#endif

    // Black Pill data. clipping is a reading and not a fault, so the values go out with it
    // and vib_clipping says so. the fields are left out only when the sensor is missing or
    // stuck or the node has no complete window.
#if HAS_STM32
    if (in.stm32 && in.stm32->hasReading && linkUsable(SK_STM32_LINK)) {
        const Stm32Reading& s = in.stm32->stm;
        if (stm32MpuState(s.st) == HS_OK && healthState(SK_STM32_MPU6050) == HS_OK) {
            doc["fft_peak_hz"]   = R(s.fft, 2);
            doc["vib_magnitude"] = R(s.mag, 3);
            if (s.extended) {
                doc["vib_rms_x"] = R(s.rms[0], 3);
                doc["vib_rms_y"] = R(s.rms[1], 3);
                doc["vib_rms_z"] = R(s.rms[2], 3);
                doc["vib_peak"]  = R(s.pk, 3);
            }
            if (s.hasVib) {
                doc["stm32_vib_x"] = R(s.vib[0], 3);
                doc["stm32_vib_y"] = R(s.vib[1], 3);
                doc["stm32_vib_z"] = R(s.vib[2], 3);
            }
        }
        // absent when the link is down. an old-format line has no status bits to read.
        if (s.extended) doc["vib_clipping"] = stm32Clipping(s.st);
    }
#endif

    // node information and faults. the hub has no synchronised clock, so there is no ts.
    doc["seq"] = in.seq;
    if (in.boot > 0) doc["boot"] = in.boot;
    doc["up"]           = in.upSeconds;
    doc["reset_reason"] = in.resetReason;
    if (in.haveRssi) doc["rssi"] = in.rssi;
    doc["heap_free"]    = in.heapFree;
    doc["fw"]           = in.fw;

    // set only when the image and the board disagree about GPIO14. the hub carries on with
    // everything else.
    if (in.boardMismatch) doc["board_mismatch"] = true;
    if (in.boardCheck && strcmp(in.boardCheck, "ok") != 0) doc["board_check"] = in.boardCheck;
    if (in.resetLoop) doc["reset_loop"] = true;
    if (in.plainHttp) doc["plain_http"] = true;
    if (in.setupExcludedMask) {
        static const char* const names[] = { "bme280", "mpu6050", "ina219", "vl53l0x", "mlx90614",
                                             "as5600", "ds18b20" };
        JsonArray ex = doc.createNestedArray("setup_excluded");
        for (uint8_t i = 0; i < 7; i++) {
            if (in.setupExcludedMask & (1u << i)) ex.add(names[i]);
        }
    }
    // the sensors this image is built without. sent once per boot, so the backend never reads
    // their absence as a fault and the post stays small
    if (in.sendNotFitted) {
        JsonArray nf = doc.createNestedArray("not_fitted");
        for (uint8_t k = 0; k < SK_COUNT; k++) {
            if (!sensorFitted((SensorKey)k)) nf.add(healthKeyName((SensorKey)k));
        }
    }

    // counters for the first bench session. the stack figures are the lowest free stack seen.
    JsonObject diag = doc.createNestedObject("diag");
    diag["post_ok"]     = in.postOk;
    diag["post_failed"] = in.postFailed;
    diag["replaced"]    = in.bodiesReplaced;
    diag["too_big"]     = in.bodiesTooBig;
    diag["stack_post"]  = in.stackPostFree;
    diag["stack_loop"]  = in.stackLoopFree;
    diag["heap_min"]    = in.heapMinFree;
    diag["heap_block"]  = in.heapLargestBlock;

    // an empty object means every sensor is well. the key is always present so the backend
    // can tell that from firmware that does not report faults.
    JsonObject faults = doc.createNestedObject("faults");
    for (uint8_t k = 0; k < SK_COUNT; k++) {
        HealthState st = healthState((SensorKey)k);
        if (st != HS_OK) faults[healthKeyName((SensorKey)k)] = healthStateName(st);
    }

    // per link counters, for the links that are fitted.
#if HAS_NANO || HAS_STM32
    JsonObject links = doc.createNestedObject("links");
#if HAS_NANO
    if (in.nano) {
        addLinkCounters(links, "nano", *in.nano, in.nano->hasReading && in.nano->nano.checksummed,
                        in.nano->nano.st, in.nano->nano.up, in.nano->nano.vccMv, true);
    }
#endif
#if HAS_STM32
    if (in.stm32) {
        addLinkCounters(links, "stm32", *in.stm32, in.stm32->hasReading && in.stm32->stm.extended,
                        in.stm32->stm.st, in.stm32->stm.up, 0, false);
    }
#endif
#endif

    return !doc.overflowed();
}
