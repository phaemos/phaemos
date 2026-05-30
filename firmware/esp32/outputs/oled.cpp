// I include Wire.h first because Adafruit_SSD1306 needs it initialised before
// any I2C transaction can happen, and include order matters on Arduino.
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "../config.h"
#include "oled.h"

// I allocate the display object at file scope so it persists across calls and
// does not eat stack space inside each function.
static Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
// -1 means no reset pin is wired, which is the standard for most breakout boards.

void initOLED() {
    // I pass OLED_ADDR from config.h so the address is defined in exactly one
    // place and changing hardware only requires editing config.h.
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        // I print to Serial here because the OLED is not yet usable - this
        // gives the developer something to see on the monitor during debugging.
        Serial.println(F("OLED init failed"));
        // I do not halt the program on OLED failure because the rest of the
        // firmware (sensors, telemetry) can still operate without a display.
        return;
    }
    display.clearDisplay();
    display.display();
}

void displaySplash(const char* title, const char* subtitle) {
    display.clearDisplay();

    // I use text size 2 for the title so it is readable across the room
    // during installation and bench-testing.
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);

    // I centre the title by measuring its pixel width at size 2 (6 px per
    // character * 2 = 12 px per char) and halving the remaining space.
    int16_t titleLen = strlen(title);
    int16_t titleX   = (OLED_WIDTH - titleLen * 12) / 2;
    if (titleX < 0) titleX = 0; // clamp in case the string is too long
    display.setCursor(titleX, 10);
    display.print(title);

    // I use text size 1 for the subtitle to keep both lines on screen at once.
    display.setTextSize(1);
    int16_t subLen = strlen(subtitle);
    int16_t subX   = (OLED_WIDTH - subLen * 6) / 2;
    if (subX < 0) subX = 0;
    display.setCursor(subX, 40);
    display.print(subtitle);

    display.display();

    // I hold the splash for 2 s so the user can confirm the device has booted
    // before telemetry overwrites the screen.
    delay(2000);
}

void displayTelemetry(BME280Reading bme, MPU6050Reading mpu, INA219Reading ina,
                      uint16_t dist, bool gas, bool water) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);

    // Line 1 - environmental data from BME280.
    // I keep it short (T/H/P) because all three values must fit on 128 px.
    display.setCursor(0, 0);
    display.print(F("T:"));
    display.print(bme.temperature, 1);
    display.print(F(" H:"));
    display.print(bme.humidity, 0);
    display.print(F(" P:"));
    display.print(bme.pressure, 0);

    // Line 2 - vibration axes from MPU6050.
    // I show Vx/Vy/Vz using one decimal place to fit within the line width.
    display.setCursor(0, 16);
    display.print(F("Vx:"));
    display.print(mpu.accel_x, 1);
    display.print(F(" Vy:"));
    display.print(mpu.accel_y, 1);
    display.print(F(" Vz:"));
    display.print(mpu.accel_z, 1);

    // Line 3 - power rail health from INA219.
    // I show voltage and current together because they are always read as a pair.
    display.setCursor(0, 32);
    display.print(F("V:"));
    display.print(ina.bus_voltage, 2);
    display.print(F("V I:"));
    display.print(ina.current_ma, 0);
    display.print(F("mA"));

    // Line 4 - alert flags on the bottom row where the operator can see them
    // at a glance. I use abbreviated labels to fit within 128 px.
    display.setCursor(0, 48);
    display.print(F("D:"));
    display.print(dist);
    display.print(F("mm"));
    if (gas)   display.print(F(" GAS!"));
    if (water) display.print(F(" H2O!"));

    display.display();
}
