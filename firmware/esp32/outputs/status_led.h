// use #pragma once for the same reason as the other headers in this folder.
#pragma once

#include "rgb_led.h"

// initStatusLeds - sets the three panel LEDs (red, amber, green) to off.
// call once in setup().
void initStatusLeds();

// setPanelStatus - lights exactly one panel LED for the status: green for
// normal, amber for warning or fault and red for critical.
void setPanelStatus(LEDStatus s);

// statusWord - the status as text, so the display and serial log never rely on
// colour alone.
const char* statusWord(LEDStatus s);
