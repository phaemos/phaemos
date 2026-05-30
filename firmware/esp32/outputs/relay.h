// I use #pragma once to keep this header self-contained without boilerplate
// include guards.
#pragma once

// I use a named enum for relay channels so call sites cannot accidentally pass
// a raw GPIO number to triggerRelay - the type system catches the mistake.
enum RelayChannel {
    RELAY_CH1 = 0,
    RELAY_CH2 = 1,
    RELAY_CH3 = 2,
    RELAY_CH4 = 3
};

// initRelay - configures all four relay pins as outputs and sets them to the
// off state. Call once in setup().
void initRelay();

// triggerRelay - sets a single relay channel on or off.
// on=true energises the relay coil (closes the load circuit).
// on=false de-energises it (opens the load circuit).
void triggerRelay(RelayChannel ch, bool on);
