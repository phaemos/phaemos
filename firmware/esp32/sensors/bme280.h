// I use #pragma once instead of an #ifndef guard because it is simpler and
// universally supported by every compiler this project targets.
#pragma once

// BME280Reading holds all three measurements in one struct so callers
// never have to manage three separate variables per sensor poll.
struct BME280Reading {
    float temperature; // degrees Celsius
    float humidity;    // percent relative humidity
    float pressure;    // hPa
};

// I forward-declare these as plain C-style functions so any .cpp file can
// call them without pulling in C++ class headers they do not need.
void initBME280();
void readBME280(BME280Reading* r);
