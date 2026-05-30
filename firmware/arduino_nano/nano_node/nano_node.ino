// nano_node.ino - Arduino Nano secondary node main sketch
//
// Reads BME280, LDR, and FC-28 moisture sensor.
// Outputs one CSV line every 2 seconds over Serial at 9600 baud.
//
// I chose CSV over Serial rather than JSON or a binary protocol because:
//   - It requires no library on either end - Serial.print() on the Nano and
//     String.indexOf()/substring() on the ESP32 parser are both built-in.
//   - Each field has a named prefix (TEMP:, HUM:, etc.) so the ESP32 can
//     parse individual fields without caring about field order, making the
//     format resilient to future additions.
//   - Baud rate 9600 keeps the signal clean over long duplex wires (>10 cm)
//     to the ESP32, where higher baud rates can introduce framing errors
//     without proper shielding.
//
// Example output:
//   TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0
//   TEMP:-1,HUM:-1,PRES:-1,LIGHT:512,MOIST:301,WATER:1   <- if BME absent

#include <Wire.h>
#include "sensors.h"

// I use a named constant for the interval rather than a magic number so it
// is easy to adjust during testing without hunting through the loop() body.
static const unsigned long REPORT_INTERVAL_MS = 2000UL;

// I track the last report time with millis() rather than delay() so the
// Nano's CPU is not blocked during the 2-second window - useful if we add
// interrupt-driven sensor features later.
static unsigned long last_report_ms = 0;

void setup() {
    // I initialise Serial before Wire so any I2C errors during initBME280Nano
    // can be observed on the serial monitor during bring-up.
    Serial.begin(9600);
    Wire.begin();
    initBME280Nano();
}

void loop() {
    unsigned long now = millis();

    // I use (now - last_report_ms) rather than comparing to a target time
    // to handle millis() overflow gracefully - unsigned subtraction wraps
    // correctly at the 49-day rollover boundary.
    if (now - last_report_ms >= REPORT_INTERVAL_MS) {
        last_report_ms = now;

        BME280Data bme   = readBME280Nano();
        int        light = readLDRNano();
        int        moist = readMoisture();
        int        water = isWaterDetected(moist) ? 1 : 0;

        if (bme.ok) {
            // Normal path: all sensors healthy
            Serial.print("TEMP:");
            Serial.print(bme.temperature, 1);
            Serial.print(",HUM:");
            Serial.print(bme.humidity, 1);
            Serial.print(",PRES:");
            Serial.print(bme.pressure, 1);
        } else {
            // BME280 not found or read failed - send sentinel values so the
            // upstream ESP32 parser can flag a sensor fault without crashing.
            // I use -1 rather than 0 because 0 is a plausible real temperature
            // and would be harder to distinguish from a valid reading.
            Serial.print("TEMP:-1,HUM:-1,PRES:-1");
        }

        Serial.print(",LIGHT:");
        Serial.print(light);
        Serial.print(",MOIST:");
        Serial.print(moist);
        Serial.print(",WATER:");
        Serial.println(water);  // println adds \r\n which the ESP32 uses as
                                // a line delimiter when reading from UART
    }
}
