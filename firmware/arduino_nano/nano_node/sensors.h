#pragma once
// sensors.h - Sensor abstraction for the Arduino Nano secondary node
//
// I use #pragma once rather than a traditional #ifndef guard because every
// modern Arduino-supported compiler (avr-gcc, arm-none-eabi-gcc) supports it
// and it is less error-prone than manually keeping guard macro names unique.

#include <Arduino.h>
#include <Adafruit_BME280.h>

// I group the BME280 readings into a struct rather than using global variables
// because structs let the compiler catch type mismatches at the call site and
// make the main sketch read like self-documenting data flow.
struct BME280Data {
    float temperature;  // degrees Celsius
    float humidity;     // percent relative humidity
    float pressure;     // hPa
    bool  ok;           // true if the sensor initialised and the read succeeded
};

// initBME280Nano - Try I2C addresses 0x76 then 0x77.
// I try both addresses here so the same firmware works with both the common
// 0x76 (SDO tied low) and 0x77 (SDO tied high) module variants without
// requiring a recompile.
void initBME280Nano();

// readBME280Nano - Return temperature, humidity and pressure in a single struct.
// I return a struct from readBME280Nano rather than output params because the
// Nano has enough SRAM for small structs and it makes the main sketch more
// readable - the caller gets one named result rather than three pointer args.
BME280Data readBME280Nano();

// readLDRNano - Return raw ADC value (0-1023) from the LDR on A0.
// I expose this as a raw ADC integer rather than a lux value because
// converting to lux requires knowing the specific LDR's resistance curve and
// the voltage divider resistor value, which varies by hardware build.
int readLDRNano();

// readMoisture - Return raw ADC value (0-1023) from the FC-28 on A1.
// Higher value = drier (more resistance). Lower value = wetter.
int readMoisture();

// isWaterDetected - Return true when the soil is wet.
// I use threshold 500 as the water-detected cutoff because the FC-28
// datasheet suggests ~500 ADC counts as the air/water boundary with a 5V
// supply and 10-bit ADC.  Adjust this constant for your specific sensor and
// supply voltage.
bool isWaterDetected(int moisture);
