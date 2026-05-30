// sensors.cpp - Sensor driver implementations for the Arduino Nano node
//
// I return a struct from readBME280Nano rather than output params because the
// Nano has enough SRAM for small structs and it makes the main sketch more
// readable - one named return value beats three pointer arguments at the
// call site.

#include "sensors.h"
#include <Wire.h>
#include <Adafruit_BME280.h>

// I declare the BME280 object at file scope so both initBME280Nano and
// readBME280Nano share the same instance without passing a pointer.
// I use static linkage to prevent name collisions if other translation units
// include this file.
static Adafruit_BME280 bme;

// I track init success in a module-level flag so readBME280Nano can return
// ok=false immediately without attempting I2C reads when the sensor is absent.
static bool bme_initialised = false;

// initBME280Nano - Probe 0x76, fall back to 0x77.
// I try 0x76 first because it is the more common default (SDO=GND on most
// Chinese breakout boards).  Falling back to 0x77 means the firmware works
// without modification on boards where SDO is pulled high.
void initBME280Nano() {
    if (bme.begin(0x76)) {
        bme_initialised = true;
        return;
    }
    if (bme.begin(0x77)) {
        bme_initialised = true;
        return;
    }
    // I leave bme_initialised false here; readBME280Nano will set ok=false
    // in the returned struct so the main sketch knows to substitute sentinel
    // values in the CSV output.
    bme_initialised = false;
}

// readBME280Nano - Read temperature, humidity, pressure from the BME280.
// I check bme_initialised before every read rather than just on first read
// because power cycling or I2C bus errors can cause the sensor to drop off
// the bus mid-session.
BME280Data readBME280Nano() {
    BME280Data result;

    if (!bme_initialised) {
        result.temperature = -1.0f;
        result.humidity    = -1.0f;
        result.pressure    = -1.0f;
        result.ok          = false;
        return result;
    }

    result.temperature = bme.readTemperature();    // degrees C
    result.humidity    = bme.readHumidity();       // %RH
    result.pressure    = bme.readPressure() / 100.0f;  // Pa -> hPa
    result.ok          = true;
    return result;
}

// readLDRNano - Read LDR ADC value from pin A0.
// I use analogRead directly here rather than averaging multiple samples
// because the main loop already runs every 2 seconds, giving the ADC input
// capacitance enough time to settle between reads.
int readLDRNano() {
    return analogRead(A0);
}

// readMoisture - Read FC-28 moisture sensor ADC value from pin A1.
// The FC-28 is a resistive sensor: low ADC value = low resistance = high
// moisture.  I do not invert the reading here so the raw value is always
// available to the caller for calibration or logging purposes.
int readMoisture() {
    return analogRead(A1);
}

// isWaterDetected - Returns true when moisture ADC value indicates wet soil.
// I use a threshold of 500 because with a 5V supply and the FC-28's typical
// resistance range, values below ~500 correspond to the sensor being partially
// submerged.  Lower threshold = more sensitive to moisture; higher = less.
bool isWaterDetected(int moisture) {
    return moisture < 500;
}
