// I use #pragma once for the same reason as the other headers in this folder.
#pragma once

// I define LEDStatus as a named enum so the call site reads
// setLEDStatus(STATUS_CRITICAL) rather than setLEDStatus(2), making intent
// obvious without a comment at every call.
enum LEDStatus {
    STATUS_NORMAL   = 0, // green  - all thresholds within limits
    STATUS_WARNING  = 1, // amber  - at least one threshold crossed
    STATUS_CRITICAL = 2  // red    - immediate hazard detected
};

// initRGBLed - call once in setup() to start the NeoPixel strip and clear it.
void initRGBLed();

// setLEDStatus - sets every pixel on the strip to the colour that represents s.
// I update all pixels together because the strip forms a single status bar,
// not individual independently controlled lights.
void setLEDStatus(LEDStatus s);
