// I include Adafruit_NeoPixel before the local headers because the library
// defines types that the local code may indirectly depend on at parse time.
#include <Adafruit_NeoPixel.h>

#include "../config.h"
#include "rgb_led.h"

// I allocate the NeoPixel object at file scope so it lives for the full
// lifetime of the firmware, not just inside init().
// NEO_GRB + NEO_KHZ800 is the correct timing for WS2812B strips.
static Adafruit_NeoPixel strip(RGB_LED_COUNT, RGB_LED_PIN,
                               NEO_GRB + NEO_KHZ800);

void initRGBLed() {
    strip.begin();
    // I clear all pixels immediately after begin() so the strip does not show
    // random colours from the last power cycle while the rest of boot runs.
    strip.clear();
    strip.show();
}

void setLEDStatus(LEDStatus s) {
    uint32_t colour;

    switch (s) {
        case STATUS_NORMAL:
            // I use a mid-brightness green (0, 180, 0) rather than full
            // (0, 255, 0) to reduce power draw on the 5 V rail when the
            // strip has 30 pixels lit.
            colour = strip.Color(0, 180, 0);
            break;

        case STATUS_WARNING:
            // I use amber (255, 100, 0) rather than pure yellow because it is
            // more visually distinct from green on a WS2812B panel.
            colour = strip.Color(255, 100, 0);
            break;

        case STATUS_CRITICAL:
            // I use full red to maximise urgency - power draw is acceptable
            // here because the operator needs to act immediately.
            colour = strip.Color(255, 0, 0);
            break;

        default:
            // I default to off rather than an arbitrary colour so an unknown
            // status does not mislead the operator about system health.
            colour = strip.Color(0, 0, 0);
            break;
    }

    // I fill all pixels with the same colour in a loop so the visual effect
    // is a solid status bar rather than a partial update.
    for (int i = 0; i < strip.numPixels(); i++) {
        strip.setPixelColor(i, colour);
    }
    strip.show();
}
