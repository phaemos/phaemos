// include config.h first so every macro (BME280_ADDR, I2C_SDA, etc.) is
// visible before any library header tries to use them.
#include "../config.h"
#include "bme280.h"
#include "i2c_probe.h"
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <Adafruit_BMP280.h>

// keep the sensor objects at file scope because they must persist between
// calls to initBME280() and readBME280().
static Adafruit_BME280 bme;
static Adafruit_BMP280 bmp;

// the carrier socket may hold a BMP280 (chip ID 0x56 to 0x58) which has no
// humidity element. the BME280 driver rejects that chip, so a second driver
// handles it and humidity is reported as absent.
static bool s_isBmp = false;
static uint8_t s_addr = BME280_ADDR;

// read the chip ID register (0xD0) so the right driver is chosen before begin().
static int readChipId(uint8_t addr) {
    Wire.beginTransmission(addr);
    Wire.write(0xD0);
    if (Wire.endTransmission(false) != 0) return -1;
    if (Wire.requestFrom(addr, (uint8_t)1) != 1) return -1;
    return Wire.read();
}

// the pinned Adafruit_BME280::init() waits in `while (isReadingCalibration()) delay(10);`. a
// failed read returns the register address 0xF3, whose bit 0 is set, so that loop never ends once
// the part stops answering. this is the firmware's own bounded check, run before the library is
// called: the status register (0xF3) must be readable three times in a row and its im_update bit
// must be clear within 100 ms. what it cannot cover is the part dropping off in the few
// milliseconds between this check and the library's own wait. the watchdog and the set-up marker
// in RTC memory cover that (see esp32.ino).
static bool boundedReady(uint8_t addr) {
    for (uint8_t waited = 0; waited <= 100; waited += 10) {
        bool ok = true;
        uint8_t status = 0;
        for (uint8_t i = 0; i < 3 && ok; i++) ok = i2cReadReg8(addr, 0xF3, &status);
        if (!ok) return false;
        if ((status & 0x01) == 0) return true;
        delay(10);
    }
    return false;
}

bool initBME280() {
    // try the address from config.h first, then fall back to 0x77 because
    // some breakout boards ship with the alternate address soldered.
    const uint8_t addrs[2] = { BME280_ADDR, 0x77 };
    for (uint8_t i = 0; i < 2; i++) {
        int id = readChipId(addrs[i]);
        if (id >= 0 && !boundedReady(addrs[i])) {
            Serial.println("[BME280] ERROR: the part does not answer its status register, set-up skipped");
            return false;
        }
        if (id == 0x60 && bme.begin(addrs[i])) {
            s_isBmp = false;
            s_addr  = addrs[i];
            Serial.println("[BME280] init OK");
            return true;
        }
        if (id >= 0x56 && id <= 0x58 && bmp.begin(addrs[i], (uint8_t)id)) {
            s_isBmp = true;
            s_addr  = addrs[i];
            Serial.println("[BMP280] init OK - no humidity on this chip");
            return true;
        }
    }

    // print to Serial here rather than halting execution so the rest of
    // the system can still run and report errors over telemetry.
    Serial.println("[BME280] ERROR: no BME280 or BMP280 found at 0x76 or 0x77");
    return false;
}

uint8_t bme280Address() {
    return s_addr;
}

void readBME280(BME280Reading* r) {
    // pass the pointer fields directly to the Adafruit methods to avoid
    // an extra copy of the float values on the stack.
    if (s_isBmp) {
        r->temperature = bmp.readTemperature();
        r->humidity    = NAN;
        r->pressure    = bmp.readPressure() / 100.0F; // Pa to hPa
        return;
    }
    r->temperature = bme.readTemperature();
    r->humidity    = bme.readHumidity();
    r->pressure    = bme.readPressure() / 100.0F; // Pa to hPa
}
