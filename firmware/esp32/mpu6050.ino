// ============================================================
// mpu6050.ino - MPU6050 accelerometer / gyroscope (vibration)
// ============================================================

#include <Wire.h>
#include <MPU6050.h>
#include "config.h"

MPU6050 mpu;

void initMPU() {
  Wire.begin(MPU6050_SDA, MPU6050_SCL);
  mpu.initialize();
  if (!mpu.testConnection()) {
    Serial.println("MPU6050 connection failed");
  }
}

// Reads acceleration in g (gravity units)
// Z-axis at rest should read ~1g due to gravity
void readMPU(float &ax, float &ay, float &az) {
  int16_t rawAx, rawAy, rawAz, gx, gy, gz;
  mpu.getMotion6(&rawAx, &rawAy, &rawAz, &gx, &gy, &gz);

  // Scale factor for +/-2g range: 16384 LSB/g
  ax = rawAx / 16384.0;
  ay = rawAy / 16384.0;
  az = rawAz / 16384.0;
}
