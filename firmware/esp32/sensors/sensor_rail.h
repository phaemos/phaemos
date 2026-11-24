#pragma once


// sensorRailInit leaves GPIO14 as an input. call it first thing in setup() so nothing
// ever drives the switch by accident.
void sensorRailInit();

// sensorRailPowerCycle switches the 3.3 V feed to the cable sensors off and back on, then
// starts the I2C bus again. the caller must initialise every sensor afterwards.
// it blocks for about SENSOR_RAIL_OFF_MS plus SENSOR_RAIL_SETTLE_MS plus
// SENSOR_RAIL_STARTUP_MS.
void sensorRailPowerCycle();
