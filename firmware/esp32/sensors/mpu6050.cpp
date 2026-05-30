// I include config.h first so I2C pin macros are available when Wire.h inits.
#include "../config.h"
#include "mpu6050.h"
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// I keep the object static so its calibration state survives across loop() calls.
static Adafruit_MPU6050 mpu;

void initMPU6050() {
    if (!mpu.begin(MPU6050_ADDR)) {
        // I print rather than hang so the watchdog can recover the node.
        Serial.println("[MPU6050] ERROR: sensor not found");
        return;
    }

    // I choose 8g range because Phaemos nodes are expected to see moderate
    // vibration - 2g is too easy to saturate, 16g wastes resolution.
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);

    // 500 deg/s covers fast rotations during installation without overflow.
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);

    // I use the 21 Hz low-pass filter to reject high-frequency electrical
    // noise on the I2C lines without introducing meaningful phase delay.
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

    Serial.println("[MPU6050] init OK");
}

void readMPU6050(MPU6050Reading* r) {
    sensors_event_t accel, gyro, temp;
    // I use getEvent() instead of raw register reads so the Adafruit driver
    // handles unit conversion and axis sign for us.
    mpu.getEvent(&accel, &gyro, &temp);

    // Adafruit already returns acceleration in m/s^2, so I divide by standard
    // gravity (9.80665) to convert to g-units as the struct documents.
    r->accel_x = accel.acceleration.x / 9.80665F;
    r->accel_y = accel.acceleration.y / 9.80665F;
    r->accel_z = accel.acceleration.z / 9.80665F;

    // Gyro comes back in rad/s from Adafruit - no conversion needed.
    r->gyro_x  = gyro.gyro.x;
    r->gyro_y  = gyro.gyro.y;
    r->gyro_z  = gyro.gyro.z;
}
