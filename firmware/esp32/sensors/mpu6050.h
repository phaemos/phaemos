// I use #pragma once for the same reason as the other headers in this folder -
// it prevents duplicate-inclusion without boilerplate.
#pragma once

// MPU6050Reading bundles all six motion axes together so one function call
// gives callers everything they need for orientation and vibration detection.
struct MPU6050Reading {
    float accel_x; // g-units
    float accel_y; // g-units
    float accel_z; // g-units
    float gyro_x;  // rad/s
    float gyro_y;  // rad/s
    float gyro_z;  // rad/s
};

void initMPU6050();
void readMPU6050(MPU6050Reading* r);
