// I use #pragma once for consistency with every other header in this project.
#pragma once

#include <Arduino.h>

// NanoData - holds all values that the Arduino Nano transmits over UART1.
// I keep a bool valid flag rather than using sentinel values like -999 so that
// any caller can check success with a simple if (d.valid) test.
struct NanoData {
    bool  valid;         // true only when parsing succeeded without errors
    float temperature;   // degrees Celsius from the Nano's BME280
    float humidity;      // percent relative humidity
    float pressure;      // hPa
    float light_level;   // raw ADC count from LDR
    float moisture;      // raw ADC count from FC-28 soil moisture sensor
    bool  water_detected; // true when FC-28 digital pin goes HIGH
};

// STM32Data - holds the vibration analysis values that the STM32 transmits
// over UART2 after running its FFT on the MPU6050 axes.
// I separate this from NanoData because the two serial ports have different
// baud rates and message cadences.
struct STM32Data {
    bool  valid;          // true only when parsing succeeded without errors
    float fft_peak_hz;    // dominant frequency bin from STM32 FFT analysis
    float vib_magnitude;  // resultant vibration magnitude from STM32
};

// parseNanoSerial - parses one line in the format:
// "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0"
// Sets d->valid = true on success, false on any parse error.
void parseNanoSerial(const String& line, NanoData* d);

// parseSTM32Serial - parses one line in the format:
// "VIB:x,y,z,MAG:m,FFT_PEAK:hHz"
// Extracts MAG as vib_magnitude and FFT_PEAK as fft_peak_hz.
// Sets d->valid = true on success, false on any parse error.
void parseSTM32Serial(const String& line, STM32Data* d);
