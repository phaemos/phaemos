// include config.h first so I2C pin macros are available when Wire.h inits.
#include "../config.h"
#include "mpu6050.h"
#include "i2c_probe.h"
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// keep the object static so its calibration state survives across loop() calls.
static Adafruit_MPU6050 mpu;

// the pinned Adafruit_MPU6050::reset() waits in `while (device_reset.read() == 1)`. a failed read
// returns -1, which compares equal to 1 in that loop, so it never ends once the part stops
// answering. this is the firmware's own bounded check, run before the library is called: the
// identity and the power register must both be readable three times in a row. what it cannot
// cover is the part dropping off during the library's reset wait. the watchdog and the set-up
// marker in RTC memory cover that (see esp32.ino).
static bool boundedReady(uint8_t addr) {
    for (uint8_t i = 0; i < 3; i++) {
        uint8_t id = 0, pwr = 0;
        if (!i2cReadReg8(addr, 0x75, &id) || id != 0x68) return false;
        if (!i2cReadReg8(addr, 0x6B, &pwr)) return false;
    }
    return true;
}

bool initMPU6050() {
    if (!boundedReady(MPU6050_ADDR)) {
        Serial.println("[MPU6050] ERROR: the part does not answer its identity and power registers, set-up skipped");
        return false;
    }
    if (!mpu.begin(MPU6050_ADDR)) {
        // print rather than hang so the watchdog can recover the node.
        Serial.println("[MPU6050] ERROR: sensor not found");
        return false;
    }

    // choose 8g range because Phaemos nodes are expected to see moderate
    // vibration - 2g is too easy to saturate, 16g wastes resolution.
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);

    // 500 deg/s covers fast rotations during installation without overflow.
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);

    // use the 21 Hz low-pass filter to reject high-frequency electrical
    // noise on the I2C lines without introducing meaningful phase delay.
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

    Serial.println("[MPU6050] init OK");
    return true;
}

void readMPU6050(MPU6050Reading* r) {
    sensors_event_t accel, gyro, temp;
    // use getEvent() instead of raw register reads so the Adafruit driver
    // handles unit conversion and axis sign.
    mpu.getEvent(&accel, &gyro, &temp);

    // Adafruit already returns acceleration in m/s^2, so divide by standard
    // gravity (9.80665) to convert to g-units as the struct documents.
    r->accel_x = accel.acceleration.x / 9.80665F;
    r->accel_y = accel.acceleration.y / 9.80665F;
    r->accel_z = accel.acceleration.z / 9.80665F;

    // gyro comes back in rad/s from Adafruit - no conversion needed.
    r->gyro_x  = gyro.gyro.x;
    r->gyro_y  = gyro.gyro.y;
    r->gyro_z  = gyro.gyro.z;
}
