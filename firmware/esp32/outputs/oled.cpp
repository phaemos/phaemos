// include Wire.h first because Adafruit_SSD1306 needs it initialised before
// any I2C transaction can happen and include order matters on Arduino.
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "../config.h"
#include "oled.h"

// allocate the display object at file scope so it persists across calls and
// does not eat stack space inside each function.
// both clock arguments are set to the board's I2C speed because the library
// default raises the bus to 400 kHz around every transfer, which the other
// devices on this bus are not built for.
static Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1,
                                I2C_FREQ_HZ, I2C_FREQ_HZ);
// -1 means no reset pin is wired, which is the standard for most breakout boards.

void initOLED() {
    // pass OLED_ADDR from config.h so the address is defined in exactly one
    // place and changing hardware only requires editing config.h.
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        // print to Serial here because the OLED is not yet usable - this
        // gives the developer something to see on the monitor during debugging.
        Serial.println(F("OLED init failed"));
        // do not halt the program on OLED failure because the rest of the
        // firmware (sensors, telemetry) can still operate without a display.
        return;
    }
    display.clearDisplay();
    display.display();
}

void displaySplash(const char* title, const char* subtitle) {
    display.clearDisplay();

    // use text size 2 for the title so it is readable across the room
    // during installation and bench-testing.
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);

    // centre the title by measuring its pixel width at size 2 (6 px per
    // character * 2 = 12 px per char) and halving the remaining space.
    int16_t titleLen = strlen(title);
    int16_t titleX   = (OLED_WIDTH - titleLen * 12) / 2;
    if (titleX < 0) titleX = 0; // clamp in case the string is too long
    display.setCursor(titleX, 10);
    display.print(title);

    // use text size 1 for the subtitle to keep both lines on screen at once.
    display.setTextSize(1);
    int16_t subLen = strlen(subtitle);
    int16_t subX   = (OLED_WIDTH - subLen * 6) / 2;
    if (subX < 0) subX = 0;
    display.setCursor(subX, 40);
    display.print(subtitle);

    display.display();

    // hold the splash for 2 s so the user can confirm the device has booted
    // before telemetry overwrites the screen.
    delay(2000);
}

// formatValue writes a number with the given decimals or dashes when it is
// absent, so a lost sensor never shows as "nan" or a made-up figure.
static void formatValue(char* out, size_t size, float v, uint8_t decimals) {
    if (isnan(v)) {
        snprintf(out, size, "--");
    } else {
        snprintf(out, size, "%.*f", decimals, v);
    }
}

void displayTelemetry(BME280Reading bme, MPU6050Reading mpu, INA219Reading ina,
                      uint16_t dist, bool gas, bool water, const char* status) {
    // build the five text rows first so the screen is only redrawn when the
    // content changes. a full frame takes about 90 ms at 100 kHz.
    char t[10], h[10], p[10], ax[10], ay[10], az[10], v[10], i[10];
    formatValue(t, sizeof t, bme.temperature, 1);
    formatValue(h, sizeof h, bme.humidity, 0);
    formatValue(p, sizeof p, bme.pressure, 0);
    formatValue(ax, sizeof ax, mpu.accel_x, 1);
    formatValue(ay, sizeof ay, mpu.accel_y, 1);
    formatValue(az, sizeof az, mpu.accel_z, 1);
    formatValue(v, sizeof v, ina.bus_voltage, 2);
    formatValue(i, sizeof i, ina.current_ma, 0);

    char rows[5][26] = {{0}};
    // row 1 - environmental data from BME280, kept short so T/H/P fit on 128 px.
    snprintf(rows[0], sizeof rows[0], "T:%s H:%s P:%s", t, h, p);
    // row 2 - vibration axes from MPU6050, one decimal place to fit the width.
    snprintf(rows[1], sizeof rows[1], "Vx:%s Vy:%s Vz:%s", ax, ay, az);
    // row 3 - power rail health from INA219, voltage and current as a pair.
    snprintf(rows[2], sizeof rows[2], "V:%sV I:%smA", v, i);
    // row 4 - distance and alert flags, abbreviated to fit within 128 px.
    if (dist > 0) {
        snprintf(rows[3], sizeof rows[3], "D:%umm%s%s", (unsigned)dist, gas ? " GAS!" : "", water ? " H2O!" : "");
    } else {
        snprintf(rows[3], sizeof rows[3], "D:--%s%s", gas ? " GAS!" : "", water ? " H2O!" : "");
    }
    // row 5 - overall status in words so the state never depends on colour.
    snprintf(rows[4], sizeof rows[4], "STATUS: %s", status);

    // compare the rows as strings. the bytes after each terminator are not part of the text.
    static char last[5][26] = {{0}};
    static bool drawn = false;
    bool same = drawn;
    for (uint8_t r = 0; same && r < 5; r++) same = strcmp(last[r], rows[r]) == 0;
    if (same) return;
    for (uint8_t r = 0; r < 5; r++) strcpy(last[r], rows[r]);
    drawn = true;

    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    const int16_t ys[5] = { 0, 16, 32, 48, 57 };
    for (uint8_t r = 0; r < 5; r++) {
        display.setCursor(0, ys[r]);
        display.print(rows[r]);
    }
    display.display();
}

void displayStatusOnly(const char* status) {
    BME280Reading bme;
    bme.temperature = bme.humidity = bme.pressure = NAN;
    MPU6050Reading mpu;
    mpu.accel_x = mpu.accel_y = mpu.accel_z = NAN;
    mpu.gyro_x = mpu.gyro_y = mpu.gyro_z = NAN;
    INA219Reading ina;
    ina.bus_voltage = ina.current_ma = ina.power_mw = NAN;
    displayTelemetry(bme, mpu, ina, 0, false, false, status);
}
