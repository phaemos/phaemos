#pragma once

// initInputVoltage sets the attenuation for GPIO39. call it once from setup().
void initInputVoltage();

// readInputVoltage returns the 12 V input in volts: the average of a few calibrated
// millivolt reads at the pin, times the divider ratio.
float readInputVoltage();
