// ============================================================
// mpu6050.ino - MPU6050 accelerometer / gyroscope (vibration)
// ============================================================

// Wire.h is the Arduino I2C library; the MPU6050 communicates over I2C (SDA + SCL lines).
#include <Wire.h>
// MPU6050.h is provided by the "MPU6050" library by Electronic Cats - install via Arduino Library Manager.
#include <MPU6050.h>
// config.h defines MPU6050_SDA, MPU6050_SCL and other board constants.
#include "config.h"

// Use a global driver instance for I2C communication with the MPU6050.
// The default I2C address (0x68) is used; tie AD0 HIGH on the breakout board to use 0x69 instead.
MPU6050 mpu;

void initMPU() {
  // Use the configured SDA/SCL pins to support boards with custom wiring.
  // On a standard Arduino Uno these are fixed, but the ESP32 lets you remap them.
  Wire.begin(MPU6050_SDA, MPU6050_SCL);
  // Wake the chip from sleep mode and configure default full-scale ranges.
  mpu.initialize();
  // Print a serial hint so wiring, power or address problems are obvious.
  if (!mpu.testConnection()) {
    Serial.println("MPU6050 connection failed");
  }
}

// Read acceleration in g (gravity units).
// The Z-axis at rest should read ~1g due to gravity.
void readMPU(float &ax, float &ay, float &az) {
  // Use Motion6 to get accel (rawAx/rawAy/rawAz) and gyro (gx/gy/gz) together.
  // int16_t is a 16-bit signed integer - the MPU6050 ADC produces exactly 16-bit raw values.
  int16_t rawAx, rawAy, rawAz, gx, gy, gz;
  // Pass by pointer so the library fills all six variables in a single I2C transaction.
  mpu.getMotion6(&rawAx, &rawAy, &rawAz, &gx, &gy, &gz);

  // Apply the scale factor for the +/-2g range: 16384 LSB/g.
  // Convert to g-units to keep values human-readable and model-friendly.
  // Use 16384.0 (a float literal) to force floating-point division; integer division would truncate to 0 or 1.
  ax = rawAx / 16384.0;
  ay = rawAy / 16384.0;
  az = rawAz / 16384.0;
}
