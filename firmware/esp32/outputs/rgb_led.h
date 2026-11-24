// use #pragma once for the same reason as the other headers in this folder.
#pragma once

#include <stdint.h>

// define LEDStatus as a named enum so the call site reads
// setLEDStatus(STATUS_CRITICAL) rather than setLEDStatus(2), making intent
// obvious without a comment at every call.
enum LEDStatus {
    STATUS_NORMAL   = 0, // green  - all thresholds within limits
    STATUS_WARNING  = 1, // amber  - at least one threshold crossed
    STATUS_CRITICAL = 2, // red    - immediate hazard detected
    STATUS_FAULT    = 3  // amber  - a sensor or supply fault, readings cannot be trusted
};

// initRGBLed - call once in setup() to start the NeoPixel strip and clear it.
void initRGBLed();

// setLEDStatus - sets every pixel on the strip to the colour that represents s.
// update all pixels together because the strip forms a single status bar,
// not individual independently controlled lights.
void setLEDStatus(LEDStatus s);

// setStripColour - fills the strip with one colour. the colour is scaled down
// when the estimated draw would pass STRIP_CURRENT_LIMIT_MA, whatever is asked for.
void setStripColour(uint8_t r, uint8_t g, uint8_t b);
