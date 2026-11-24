// the Wire binding for the port expander driver. see mcp23017_logic.h for what it does and why.
#include "mcp23017.h"

#if HAS_EXPANDER

#include <Arduino.h>
#include <Wire.h>

#include "health.h"

namespace {

class WireBus : public mcp::ExpanderBus {
public:
    mcp::BusResult writeReg(uint8_t reg, uint8_t value) override {
        Wire.beginTransmission((uint8_t)MCP23017_ADDR);
        Wire.write(reg);
        Wire.write(value);
        return mcp::busFromWire(Wire.endTransmission());
    }
    mcp::BusResult readRegs(uint8_t reg, uint8_t* out, uint8_t n) override {
        Wire.beginTransmission((uint8_t)MCP23017_ADDR);
        Wire.write(reg);
        uint8_t code = Wire.endTransmission(false);
        if (code != 0) return mcp::busFromWire(code);
        // in the pinned core requestFrom returns 0 for a refused address and for a time-out alike,
        // so a short read is only a failure. the driver follows it with probe() to tell which.
        if (Wire.requestFrom((uint8_t)MCP23017_ADDR, n) != n) return mcp::BUS_FAIL;
        for (uint8_t i = 0; i < n; i++) out[i] = (uint8_t)Wire.read();
        return mcp::BUS_OK;
    }
    mcp::BusResult probe() override {
        Wire.beginTransmission((uint8_t)MCP23017_ADDR);
        return mcp::busFromWire(Wire.endTransmission());
    }
};

class SerialSink : public mcp::ExpanderSink {
public:
    void say(const char* text) override { Serial.println(text); }
};

WireBus     s_bus;
SerialSink  s_sink;
mcp::Expander s_ex(s_bus, s_sink);
bool s_started = false;

}  // namespace

void expanderStart(uint32_t nowMs) {
    s_started = true;
    s_ex.start(nowMs);
}

void expanderTick(uint32_t nowMs) {
    if (s_started) s_ex.service(nowMs);
}

void expanderSyncHealth() {
    // an expander that was never started is stale and not ok: silence never means up
    healthSet(SK_EXPANDER, s_ex.expanderHealth(), s_ex.expanderSince());
    for (uint8_t i = 0; i < mcp::RAIL_COUNT; i++) {
        mcp::Rail r = (mcp::Rail)i;
        // a rail that is not watched stays ok. while the chip is down the last state is kept.
        healthSet(mcp::railKey(r), s_ex.railHealth(r), s_ex.railSince(r));
    }
}

bool expanderStarted() { return s_started; }
bool expanderRunning() { return s_started && s_ex.running(); }
bool expanderTakePress() { return s_started && s_ex.takePress(); }
bool expanderTakeLongPress() { return s_started && s_ex.takeLongPress(); }
void expanderNoteSensorAnswered(uint32_t nowMs) { if (s_started) s_ex.noteSensorAnswered(nowMs); }
void expanderArmSensRailReturn(uint32_t nowMs, uint32_t limitMs) { if (s_started) s_ex.armSensRailReturn(nowMs, limitMs); }
uint32_t expanderRailsUnknownForMs(uint32_t nowMs) { return s_ex.railsUnknownForMs(nowMs); }
const mcp::ExCounters& expanderCounters() { return s_ex.counters(); }

#endif
