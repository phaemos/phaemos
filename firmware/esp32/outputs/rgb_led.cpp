// include Adafruit_NeoPixel before the local headers because the library
// defines types that the local code may indirectly depend on at parse time.
#include <Adafruit_NeoPixel.h>

#include "../config.h"
#include "rgb_led.h"

// allocate the NeoPixel object at file scope so it lives for the full
// lifetime of the firmware, not just inside init().
// NEO_GRB + NEO_KHZ800 is the correct timing for WS2812B strips.
static Adafruit_NeoPixel strip(RGB_LED_COUNT, RGB_LED_PIN,
                               NEO_GRB + NEO_KHZ800);

void initRGBLed() {
    strip.begin();
    // clear all pixels immediately after begin() so the strip does not show
    // random colours from the last power cycle while the rest of boot runs.
    strip.clear();
    strip.show();
}

void setStripColour(uint8_t r, uint8_t g, uint8_t b) {
    // estimate the draw for the whole strip in milliamps. each channel scales
    // linearly with its level and every pixel has a small idle draw.
    uint32_t pixels = strip.numPixels();
    uint32_t drawMa = pixels * STRIP_IDLE_MA_PER_LED
                    + pixels * ((uint32_t)r + g + b) * STRIP_MA_PER_CHANNEL / 255UL;

    // the supply rail only gives STRIP_CURRENT_LIMIT_MA, so scale the colour
    // down (keeping its hue) whenever the request would pull more than that.
    uint32_t budgetMa = STRIP_CURRENT_LIMIT_MA;
    uint32_t idleMa   = pixels * STRIP_IDLE_MA_PER_LED;
    if (drawMa > budgetMa && drawMa > idleMa) {
        uint32_t allowed = (budgetMa > idleMa) ? (budgetMa - idleMa) : 0;
        uint32_t wanted  = drawMa - idleMa;
        r = (uint8_t)((uint32_t)r * allowed / wanted);
        g = (uint8_t)((uint32_t)g * allowed / wanted);
        b = (uint8_t)((uint32_t)b * allowed / wanted);
    }

    uint32_t colour = strip.Color(r, g, b);
    for (uint16_t i = 0; i < strip.numPixels(); i++) {
        strip.setPixelColor(i, colour);
    }
    strip.show();
}

void setLEDStatus(LEDStatus s) {
    // use a mid-brightness green rather than full to keep the draw low, amber
    // (255, 100, 0) rather than pure yellow because it stands apart from green
    // on a WS2812B panel and full red for the critical state. the strip cap in
    // setStripColour applies to all of them.
    switch (s) {
        case STATUS_NORMAL:   setStripColour(0, 180, 0);   break;
        case STATUS_WARNING:  setStripColour(255, 100, 0); break;
        case STATUS_CRITICAL: setStripColour(255, 0, 0);   break;
        // violet rather than amber so a fault looks different from a warning on the strip.
        case STATUS_FAULT:    setStripColour(160, 0, 160); break;
        default:
            // default to off rather than an arbitrary colour so an unknown
            // status does not mislead the operator about system health.
            setStripColour(0, 0, 0);
            break;
    }
}
