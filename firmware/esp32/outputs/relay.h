// use #pragma once to keep this header self-contained without boilerplate
// include guards.
#pragma once

#include <stdint.h>

#include "relay_proof.h"

// use a named enum for relay channels so call sites cannot accidentally pass
// a raw GPIO number to triggerRelay - the type system catches the mistake.
enum RelayChannel {
    RELAY_CH1 = 0,
    RELAY_CH2 = 1,
    RELAY_CH3 = 2,
    RELAY_CH4 = 3
};

// initRelay - configures all four relay pins as outputs and sets them to the
// off state (pins LOW). Call it as the first thing in setup() so no load
// switches while the rest of the boot runs.
void initRelay();

// relayAllowGpio14 says whether GPIO14 may be driven as relay 3. it is a relay pin only in the
// present-board image. only when the board really is the present board. until it is
// called with true, nothing touches GPIO14. calling it with true sets the pin low as an output.
void relayAllowGpio14(bool allow);

// triggerRelay - sets a single relay channel on or off.
// on=true energises the relay coil (closes the load circuit).
// on=false de-energises it (opens the load circuit).
void triggerRelay(RelayChannel ch, bool on);

// relayStateMask returns the commanded state of the four relays, bit n for relay n+1.
uint8_t relayStateMask();

// relayRestore drives the relays to a saved state straight after initRelay() on a warm reset.
void relayRestore(uint8_t mask);

// a command is never taken as proof that a relay switched (see relay_proof.h). relaySetRailReader
// gives the driver the relay rail's current meter. it returns false when it has no reading. with
// none set, which is every board today, each relay switched on is reported unconfirmed.
void relaySetRailReader(bool (*read)(int32_t *ma));

// relayProof says whether relay ch was shown to pull in. relayUnconfirmedMask has bit n set for
// relay n+1 commanded on and not confirmed.
RelayProof relayProof(RelayChannel ch);
uint8_t relayUnconfirmedMask();
