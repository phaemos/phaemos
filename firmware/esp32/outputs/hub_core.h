// hub_core.h - the hub's decisions behind a seam the host can drive. no Arduino types. esp32.ino
// is the wiring: it implements HubPlatform with the real pins, tasks and sensors and calls
// HubCore::boot() once and HubCore::step() on every reading. the order of setup(), the restore
// after a warm reset, the board check, the judgement of the three alarms and the panel are all
// here, so test_host/test_core.cpp can replay whole scenarios through them against a recording
// platform and check the outputs at every step.
//
// what stays in esp32.ino and is covered by reading alone: the sensor probing and the library
// set-up calls, the serial parsing, the post task and the pin writes themselves.
#pragma once

#include <stdint.h>

#include "../config.h"
#include "../comms/post_queue.h"
#include "../sensors/analog_checks.h"
#include "../sensors/board_check.h"
#include "../sensors/fitted.h"
#include "saved_state.h"
#include "status_logic.h"
#include "temp_judge.h"

// what the sensors gave on one pass, reduced to what the judgement needs
struct HubStepIn {
    uint32_t   nowMs;
    TempInputs temp;
    bool       bmeFault;           // the BME280 is fitted and not trusted
    // the MQ-2
    bool       gasWarming;
    int        gasRaw;
    bool       gasDigitalLow;
    // the moisture probe
    float      moistureCounts;
    bool       otherFault;         // any other sensor or link (not the BME280, MQ-2 or probe) is in a fault state
    uint32_t   postOkCount;        // the post task's success counter
    bool       postRejected;       // the backend answered 401 or 403: the key is wrong
    bool       plainHttp;          // posting over plain HTTP (a bench build)
    bool       counterRejected;    // the backend answered 409: it holds a newer (boot, seq) for this machine
};

struct HubStepOut {
    bool        relayCh1;          // the cooling relay's command
    StatusResult status;           // what the light, the strip and the display show on this pass
    bool        shownChanged;      // the shown level differs from the last pass
    StatusKind  soundBase;         // the highest level, which the sound follows
    bool        soundChanged;
    TempVerdict temp;
    bool        gasAlert;
    bool        gasFault;
    bool        gasDisagree;
    bool        waterAlarm;
    HealthState fc28State;
    HealthState mq2State;
    bool        resetLoop;
    bool        postStale;
    bool        restoreDropped;
    BoardVerdict board;
};

struct BootInfo {
    SetupVerdict   setup;
    RestoreVerdict verdict;
    uint8_t        linksSeen;
    bool           gasSkipWarmup;
    BoardVerdict   board;
};

// everything the core asks of the hardware. esp32.ino implements it. the host test records the calls.
class HubPlatform {
public:
    virtual ~HubPlatform() {}
    virtual void     relayInitPins() = 0;                      // relays other than GPIO14 go low
    virtual void     armWatchdog() = 0;
    virtual void     relaySet(uint8_t ch, bool on) = 0;        // ch 0 to 3 for relays 1 to 4
    virtual void     gpio14Release() = 0;                      // a plain input on both images
    virtual void     gpio14DriveRelayLow() = 0;                // relay 3 of the present board
    virtual void     delayMs(uint32_t ms) = 0;
    virtual void     i2cBegin() = 0;
    virtual bool     i2cLinesIdle() = 0;
    virtual bool     i2cProbe(uint8_t addr) = 0;
    virtual void     outputsInit() = 0;                        // panel, buzzer, strip, display and its STARTING line
    virtual void     startPostTask() = 0;
    virtual void     initSensors(const BootInfo& info) = 0;
    virtual HubStepIn readAll() = 0;
    virtual void     applyOutputs(const HubStepOut& out) = 0;
    virtual void     splashAndBeeps(bool waterUnproven, bool gasUnproven) = 0;
    virtual void     dropWatchdog() = 0;
    virtual uint32_t nowMs() = 0;
};

class HubCore {
public:
    // rtc is the record in RTC memory. the core reads and writes it in place.
    void init(SavedState* rtc);

    // the whole boot, in order: relays low, watchdog, saved state, restore of relays 1, 2 and 4,
    // GPIO14 released, the rail wait, the board check, outputs, the post task, sensor set-up, the
    // first judgement, the splash and the run watchdog.
    void boot(HubPlatform& p, int resetReason);

    // one judgement. the wiring then applies the outputs.
    HubStepOut step(const HubStepIn& in);

    // retries the board check while it is unknown
    void recheckBoard(HubPlatform& p);

    void setLinksSeen(uint8_t mask) { linksSeen_ = mask; }
    const BootInfo& info() const { return info_; }
    BoardVerdict board() const { return board_; }
    bool resetLoop() const { return resetLoopHold_; }
    const TempJudge& judge() const { return tj_; }

private:
    void probeBoard(HubPlatform& p, bool withDelays);
    void saveState();

    SavedState*   rtc_ = nullptr;
    BootInfo      info_;
    TempJudge     tj_;
    PostFreshness fresh_;
    BoardVerdict  board_ = BOARD_UNKNOWN;
    uint8_t       relayMask_ = 0;
    uint8_t       deferredRelay3_ = 0;
    bool          restorePending_ = false;
    uint32_t      restoreDeadline_ = 0;
    bool          resetLoopHold_ = false;
    bool          loopRelease_ = false;
    StatusKind    soundBase_ = STK_NORMAL;
    StatusKind    shown_ = STK_FAULT;      // the panel starts on a fault until the first judgement
    bool          altPhase_ = false;
    uint8_t       moistLowPasses_ = 0;
    uint8_t       linksSeen_ = 0;
    bool          freshInit_ = false;
};
