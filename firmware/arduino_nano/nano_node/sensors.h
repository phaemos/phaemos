#pragma once
// sensors.h - Sensor abstraction for the Arduino Nano secondary node
//
// use #pragma once rather than a traditional #ifndef guard because every
// modern Arduino-supported compiler (avr-gcc, arm-none-eabi-gcc) supports it
// and it is less error-prone than manually keeping guard macro names unique.

#include <Arduino.h>

// group the sensor readings into a struct rather than using global variables
// because structs let the compiler catch type mismatches at the call site and
// make the main sketch read like self-documenting data flow.
struct BME280Data {
    float temperature;  // degrees Celsius
    float humidity;     // percent relative humidity, only valid when has_humidity is true
    float pressure;     // hPa
    bool  ok;           // true only when the values are real: no status bit below is set
    bool  has_humidity; // false for a BMP280, which has no humidity element
    uint8_t status;     // the ST_BME_* bits that apply to this read, 0 when all is well
};

// status bit mask sent as ST.  the numbers are fixed by the serial link contract.
// the first four bits and the last one come from the sensor driver, the rest from the sketch.
static const uint8_t ST_BME_MISSING     = 1;   // the sensor does not answer
static const uint8_t ST_BME_STUCK       = 2;   // every raw value identical for BME_STUCK_READS reads
static const uint8_t ST_BME_ASLEEP      = 4;   // control registers read back wrong, set-up rewritten
static const uint8_t ST_SUPPLY_RANGE    = 8;   // VCC under 4000 or over 6000 mV (4500 and 5500 when calibrated)
static const uint8_t ST_RESET_WATCHDOG  = 16;  // this boot followed a watchdog reset
static const uint8_t ST_RESET_BROWNOUT  = 32;  // this boot followed a brown-out reset
static const uint8_t ST_BME_RANGE       = 64;  // a compensated value is outside the data sheet range

// initBME280Nano - Try I2C addresses 0x76 then 0x77 and accept a BME280 or BMP280.
// the chip ID register tells the two parts apart (0x60 for a BME280 and 0x58
// for a BMP280) so one firmware image serves both breakouts.
// try both addresses here so the same firmware works with both the common
// 0x76 (SDO tied low) and 0x77 (SDO tied high) module variants without
// requiring a recompile.
void initBME280Nano();

// readBME280Nano - Return temperature, humidity and pressure in a single struct.
// return a struct from readBME280Nano rather than output params because the
// Nano has enough SRAM for small structs and it makes the main sketch more
// readable - the caller gets one named result rather than three pointer args.
BME280Data readBME280Nano();

// readLDRNano - Return raw ADC value (0-1023) from the LDR on A0.
// expose this as a raw ADC integer rather than a lux value because
// converting to lux requires knowing the specific LDR's resistance curve and
// the voltage divider resistor value, which varies by hardware build.
int readLDRNano();

// readMoisture - Return raw ADC value (0-1023) from the FC-28 on A1.
// higher value = drier (more resistance). Lower value = wetter.
int readMoisture();

// isWaterDetected - Return true when the soil is wet.
// use threshold 500 as the water-detected cutoff because the FC-28
// datasheet suggests ~500 ADC counts as the air/water boundary with a 5V
// supply and 10-bit ADC.  Adjust this constant for your specific sensor and
// supply voltage.
bool isWaterDetected(int moisture);

// readSupplyMv - Return the supply voltage in millivolts, measured against the internal band gap.
// the ADC is shared with the LDR and the moisture probe, so the multiplexer and reference are
// put back afterwards.  returns 0 if the conversion gave nothing usable.
uint16_t readSupplyMv();
