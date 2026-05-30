// I use #pragma once consistently across all sensor headers in this project.
#pragma once

// INA219Reading groups voltage, current, and derived power in one struct
// so the telemetry builder never has to call three separate read functions.
struct INA219Reading {
    float bus_voltage; // volts
    float current_ma;  // milliamps
    float power_mw;    // milliwatts
};

void initINA219();
void readINA219(INA219Reading* r);
