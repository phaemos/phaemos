#include "hub_core.h"

#include <string.h>

void HubCore::init(SavedState* rtc) {
    rtc_ = rtc;
    memset(&info_, 0, sizeof info_);
    info_.board = BOARD_UNKNOWN;
    tjInit(&tj_);
    board_ = BOARD_UNKNOWN;
    relayMask_ = 0;
    deferredRelay3_ = 0;
    restorePending_ = false;
    resetLoopHold_ = false;
    loopRelease_ = false;
    soundBase_ = STK_NORMAL;
    shown_ = STK_FAULT;
    altPhase_ = false;
    moistLowPasses_ = 0;
    linksSeen_ = 0;
    freshInit_ = false;
}

void HubCore::saveState() {
    ssStoreJudge(rtc_, &tj_);
    rtc_->relayMask = relayMask_;
    rtc_->linksSeen = linksSeen_;
    ssSeal(rtc_);
}

// probes the expander several times and a few other known devices to show the bus works and decides
// the board. GPIO14 is driven only when the verdict says the present-board image is on the present board.
void HubCore::probeBoard(HubPlatform& p, bool withDelays) {
    p.i2cBegin();
    bool idle = p.i2cLinesIdle();
    bool mcp = false;
    for (uint8_t i = 0; i < BOARD_PROBE_TRIES && !mcp; i++) {
        mcp = p.i2cProbe(MCP23017_ADDR);
        if (!mcp && withDelays) p.delayMs(BOARD_PROBE_GAP_MS);
    }
    bool other = false;
    if (!mcp) {
        const uint8_t known[] = { OLED_ADDR, BME280_ADDR, 0x77, MPU6050_ADDR, INA219_ADDR,
                                  MLX90614_ADDR, VL53L0X_ADDR, AS5600_ADDR };
        for (uint8_t a : known) {
            if (p.i2cProbe(a)) { other = true; break; }
        }
    }
    board_ = boardVerdict(HAS_SENSOR_RAIL_SWITCH != 0, idle, mcp, other);
    info_.board = board_;
    if (mayDriveGpio14AsRelay(HAS_SENSOR_RAIL_SWITCH != 0, board_)) {
        p.gpio14DriveRelayLow();
        if (deferredRelay3_) {
            p.relaySet(2, true);
            deferredRelay3_ = 0;
        }
    }
}

void HubCore::recheckBoard(HubPlatform& p) {
    if (board_ != BOARD_UNKNOWN) return;
    probeBoard(p, false);
}

void HubCore::boot(HubPlatform& p, int resetReason) {
    // 1. the relays other than GPIO14 go low and the watchdog is armed, before anything that can wait
    p.relayInitPins();
    p.armWatchdog();

    // 2. the saved state. it is trusted only after a warm reset and only when it is intact
    bool warm = ssWarmResetReason(resetReason);
    bool intact = warm && ssValid(rtc_);
    if (!intact) ssReset(rtc_);
    info_.setup = ssSetupBootCheck(rtc_, resetReason);
    // a damaged record on a warm reset is the same as a cold start: nothing to restore and nothing counted
    info_.verdict = intact ? ssRestoreVerdict(resetReason, rtc_) : RV_NONE;
    info_.gasSkipWarmup = intact && rtc_->gasWarmedUp != 0;
    info_.linksSeen = intact ? rtc_->linksSeen : 0;

    // 3. restore relays 1, 2 and 4 at once. they need no board check. relay 3 waits for it on the
    // present board, where it is GPIO14
    if (info_.verdict != RV_NONE) {
        ssLoadJudge(rtc_, &tj_);
        relayMask_ = rtc_->relayMask;
        if (info_.verdict == RV_RESTORE) {
            for (uint8_t ch = 0; ch < 4; ch++) {
                if (!(relayMask_ & (1u << ch))) continue;
                if (ch == 2 && HAS_SENSOR_RAIL_SWITCH == 0) {
                    deferredRelay3_ = 1;
                    continue;
                }
                p.relaySet(ch, true);
            }
            restorePending_ = tjPending(&tj_) || relayMask_ != 0;
            restoreDeadline_ = p.nowMs() + RELAY_RESTORE_CONFIRM_MS;
        } else {
            // a reset loop: no restore and the relay takes its state for no information. that
            // is the same whatever the relay was doing before the loop began
            tjClear(&tj_);
            relayMask_ = 0;
            resetLoopHold_ = true;
            if (COOLING_RELAY_NO_INFO_ON) {
                p.relaySet(0, true);
                relayMask_ |= 1;
            }
        }
        // every warm reset is one more without a trusted reading until one arrives
        ssNoteBoot(rtc_);
    }

    // 4. GPIO14 is released as a plain input on both images, the sensor rail gets its start-up
    // time and only then is the bus used to recognise the board. the bus is probed several times
    // and any doubt means GPIO14 is not driven
    p.gpio14Release();
    p.delayMs(SENSOR_RAIL_STARTUP_MS);
    probeBoard(p, true);

    // 5. the outputs and the post task start before any sensor set-up, so a sensor that stalls can
    // never keep the panel dark or the hub silent
    p.outputsInit();
    p.startPostTask();

    // 6. sensor set-up, then the first judgement before the splash and the beeps
    p.initSensors(info_);
    fresh_.okCount = 0;
    pfInit(&fresh_, p.nowMs());
    HubStepIn in = p.readAll();
    HubStepOut out = step(in);
    p.applyOutputs(out);

    // 7. the splash and the run watchdog
    p.splashAndBeeps(HAS_FC28 && !WATER_ALARM_PROVEN, HAS_MQ2 && !GAS_ALARM_PROVEN);
    p.dropWatchdog();
}

HubStepOut HubCore::step(const HubStepIn& in) {
    HubStepOut out;
    memset(&out, 0, sizeof out);
    uint32_t now = in.nowMs;

    bool anyTrusted = in.temp.bme.trusted || in.temp.bmeOverRange || in.temp.ds.trusted ||
                      in.temp.mlx.trusted;

    // a restored cooling state must be confirmed by a trusted reading from any source. no trusted
    // reading within RELAY_RESTORE_CONFIRM_MS drops it
    RestoreStep rs = ssRestoreStep(restorePending_, anyTrusted, now, restoreDeadline_);
    if (rs == RESTORE_CONFIRMED) {
        restorePending_ = false;
    } else if (rs == RESTORE_DROP) {
        restorePending_ = false;
        tjClear(&tj_);
        out.restoreDropped = true;
    }

    // a trusted reading ends a reset loop and clears the count of warm resets without one
    if (anyTrusted) {
        ssNoteConfirmed(rtc_);
        if (resetLoopHold_) {
            resetLoopHold_ = false;
            loopRelease_ = true;
        }
    }

    out.temp = tjStep(&tj_, in.temp);

    // the cooling relay. critical is any latch. in a reset loop, with nothing trusted, the relay
    // takes its state for no information. when the loop ends it stays on while any source is over its
    // threshold or still being confirmed, so it does not drop for the passes a count needs
    bool cooling = out.temp.critActive;
    if (resetLoopHold_) {
        cooling = COOLING_RELAY_NO_INFO_ON != 0;
    } else if (loopRelease_) {
        bool pending = tjPending(&tj_);
        cooling = pending;
        if (!pending) loopRelease_ = false;
    }
    out.relayCh1 = cooling;
    if (cooling) relayMask_ |= 1; else relayMask_ &= (uint8_t)~1u;

    // the gas sensor. the warm-up holds the alarm back. after it both paths are judged together
    out.mq2State = HS_OK;
    if (HAS_MQ2) {
        if (in.gasWarming) {
            out.mq2State = HS_WARMING_UP;
        } else {
            GasJudgement g = gasJudge(in.gasRaw, in.gasDigitalLow);
            out.gasAlert = g.alarm;
            out.gasFault = g.fault;
            out.gasDisagree = g.disagree;
            if (g.fault || g.disagree) out.mq2State = HS_OUT_OF_RANGE;
            ssNoteGasWarmed(rtc_);
        }
    }

    // the water probe
    out.fc28State = HS_OK;
    if (HAS_FC28) {
        out.waterAlarm = waterAlarm(in.moistureCounts);
#if HAS_INPUT_PULLDOWNS || HAS_PROBE_SERIES_R
        out.fc28State = moistureState(in.moistureCounts, &moistLowPasses_);
#endif
    }

    out.postStale = pfUpdate(&fresh_, now, in.postOkCount, POST_STALE_MS);
    out.resetLoop = resetLoopHold_;
    out.board = board_;

    // the panel
    StatusInput si;
    memset(&si, 0, sizeof si);
    si.critActive = out.temp.critActive;
    si.warnActive = out.temp.warnActive;
    si.gasAlert   = out.gasAlert;
    si.waterAlert = out.waterAlarm;
    si.tempFault  = in.bmeFault;
    si.gasFault   = out.gasFault || out.gasDisagree;
    si.gasWarm    = HAS_MQ2 && in.gasWarming;
    si.probeFault = HAS_FC28 && out.fc28State == HS_UNPLUGGED;
    si.noTemp     = TEMP_ANY_FITTED && out.temp.alarmUnavailable;
    si.boardFault = board_ != BOARD_OK;
    si.resetLoop  = resetLoopHold_;
    si.otherFault = in.otherFault;
    // a rejected key shows NET straight away and does not wait for POST_STALE_MS
    si.postFault  = out.postStale || in.postRejected;
    si.plainHttp  = in.plainHttp;
    si.counterRejected = in.counterRejected;
    altPhase_ = !altPhase_;
    out.status = decideStatus(si, altPhase_);
    out.shownChanged = out.status.shown != shown_;
    shown_ = out.status.shown;
    out.soundChanged = out.status.base != soundBase_;
    soundBase_ = out.status.base;
    out.soundBase = soundBase_;

    saveState();
    return out;
}
