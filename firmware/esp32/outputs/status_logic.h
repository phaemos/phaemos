// status_logic.h - decides what the panel shows, with no Arduino types so the host test can
// cover it. precedence, highest first:
//   CRITICAL  a confirmed critical temperature. it always wins and never alternates, so a
//             critical machine condition is never hidden by anything.
//   WARNING   a warning temperature, gas or water.
//   FAULT     any fault: a sensor or link in a fault state, the gas alarm not available (warming up
//             or unplugged), the over-temperature alarm not available, a board mismatch, a reset
//             loop or no successful post for POST_STALE_MS.
//   NORMAL
// the light, the strip and the display show the highest. when a warning and a fault both
// exist (and nothing is critical) they alternate on every reading, so a warning never hides a
// fault. the sound follows the highest level only, so the alternation does not beep.
#pragma once

#include <stdint.h>

// the same numbers as LEDStatus in rgb_led.h
enum StatusKind : uint8_t {
    STK_NORMAL   = 0,
    STK_WARNING  = 1,
    STK_CRITICAL = 2,
    STK_FAULT    = 3
};

struct StatusInput {
    bool critActive;
    bool warnActive;
    bool gasAlert;
    bool waterAlert;
    bool tempFault;     // the BME280 is lost or out of range
    bool gasFault;      // the MQ-2 is unplugged or faulted
    bool gasWarm;       // the MQ-2 is warming up, so the gas alarm is not available
    bool probeFault;    // the moisture input reads as unplugged
    bool noTemp;        // no trusted temperature source: the over-temperature alarm is unavailable
    bool boardFault;    // the image and the board disagree
    bool resetLoop;     // a reset loop: restores went unconfirmed and the relay is in its no-information state
    bool otherFault;    // any other sensor or link is in a fault state
    bool postFault;     // no post has succeeded for POST_STALE_MS
    bool counterRejected; // the server answered 409: it has seen a newer boot counter from this machine
    bool plainHttp;     // the hub posts over plain HTTP (a bench build), so nothing it sends is private
};

struct StatusResult {
    StatusKind base;     // the highest level, which drives the sound
    StatusKind shown;    // what the light, the strip and the display show on this reading
    bool       both;     // a warning and a fault both exist and are alternating
    char       text[32];
};

// altPhase flips on every reading. the text is the word and, for a fault, short codes of what
// failed, whole codes only, cut to fit the display row (a trailing + marks a longer list). the
// codes are LOOP (reset loop), NOTMP (no trusted temperature source), MQ-2 (gas sensor fault), WARM
// (gas warm-up), TEMP (BME280 lost), PRB (probe unplugged), BRD (board check), PLN (plain HTTP
// bench mode), CTR (the server refused the boot counter), NET (no post for POST_STALE_MS) and SENS (any other sensor or link). TEMP is dropped when NOTMP is shown.
StatusResult decideStatus(const StatusInput& in, bool altPhase);
