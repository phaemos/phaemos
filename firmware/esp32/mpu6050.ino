// ============================================================
// mpu6050.ino - MPU6050 accelerometer / gyroscope (vibration)
// ============================================================

#include <Wire.h>
#include <MPU6050.h>
#include "config.h"

// Driver instance for I2C communication with MPU6050.
MPU6050 mpu;

void initMPU() {
  // Use configured SDA/SCL pins for boards with custom wiring.
  Wire.begin(MPU6050_SDA, MPU6050_SCL);
  mpu.initialize();
  // Helpful serial hint if wiring/power/address is incorrect.
  if (!mpu.testConnection()) {
    Serial.println("MPU6050 connection failed");
  }
}

// Reads acceleration in g (gravity units)
// Z-axis at rest should read ~1g due to gravity
void readMPU(float &ax, float &ay, float &az) {
  // Motion6 returns accel (rawAx/rawAy/rawAz) and gyro (gx/gy/gz).
  int16_t rawAx, rawAy, rawAz, gx, gy, gz;
  mpu.getMotion6(&rawAx, &rawAy, &rawAz, &gx, &gy, &gz);

  // Scale factor for +/-2g range: 16384 LSB/g
  // Converting to g-units keeps values human-readable and model-friendly.
  ax = rawAx / 16384.0;
  ay = rawAy / 16384.0;
  az = rawAz / 16384.0;
}
