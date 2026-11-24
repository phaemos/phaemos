// mcp23017.h - the port expander on the revised board: seven rail inputs, the push button and
// the spare header. built only when HAS_EXPANDER is 1, so the present board's image carries none of
// it. the decisions are in mcp23017_logic.h, which the host test drives. nothing here has run on a
// board and no revised board has been made.
#pragma once

#include <stdint.h>

#include "../config.h"
#include "mcp23017_logic.h"

#if HAS_EXPANDER

// one start attempt. call it once at boot when the board check says the expander answers.
void expanderStart(uint32_t nowMs);
// call it on every pass of the main loop. it talks to the chip only when a poll or a check is due
// and ends at the first failed transfer, so it holds the loop for about one bus time-out at worst.
void expanderTick(uint32_t nowMs);
// copies the expander and rail states into the health table, with the time each began. it is
// called whether or not the driver started: an expander that is not running is stale and never ok.
void expanderSyncHealth();

bool expanderStarted();
bool expanderRunning();
// button events. each returns true once per event.
bool expanderTakePress();
bool expanderTakeLongPress();
// a cable sensor answered on this pass. the sensor rail is called present only while one has.
void expanderNoteSensorAnswered(uint32_t nowMs);
// the sensor rail was just switched back on and the bus is up. SENS_OK has to read high on two polls in
// a row within the limit. nothing waits: the check is judged on the polls the loop makes anyway.
void expanderArmSensRailReturn(uint32_t nowMs, uint32_t limitMs);
// how long the watched rails have not been known, 0 while the last good reading is fresh
uint32_t expanderRailsUnknownForMs(uint32_t nowMs);
const mcp::ExCounters& expanderCounters();

#endif
