/* ============================================================
 * mpu6050_driver.c - Minimal I2C driver for MPU6050 on STM32
 * ============================================================ */

#include "mpu6050_driver.h"

#define MPU6050_ADDR    (0x68 << 1)   /* 7-bit address shifted for HAL */
#define REG_PWR_MGMT_1  0x6B
#define REG_ACCEL_XOUT  0x3B
#define ACCEL_SCALE     16384.0f      /* +/-2g range */

void MPU6050_Init(I2C_HandleTypeDef *hi2c) {
  /* Wake the MPU6050 by clearing SLEEP bit in PWR_MGMT_1 */
  uint8_t data = 0x00;
  /* Register write: device address, register, data byte. */
  HAL_I2C_Mem_Write(hi2c, MPU6050_ADDR, REG_PWR_MGMT_1,
                    I2C_MEMADD_SIZE_8BIT, &data, 1, HAL_MAX_DELAY);
}

void MPU6050_ReadAccel(I2C_HandleTypeDef *hi2c,
                       float *ax, float *ay, float *az) {
  uint8_t raw[6];
  /* Read 6 bytes: AX_H, AX_L, AY_H, AY_L, AZ_H, AZ_L. */
  HAL_I2C_Mem_Read(hi2c, MPU6050_ADDR, REG_ACCEL_XOUT,
                   I2C_MEMADD_SIZE_8BIT, raw, 6, HAL_MAX_DELAY);

  /* Combine high/low bytes into signed 16-bit raw acceleration values. */
  int16_t rawX = (int16_t)((raw[0] << 8) | raw[1]);
  int16_t rawY = (int16_t)((raw[2] << 8) | raw[3]);
  int16_t rawZ = (int16_t)((raw[4] << 8) | raw[5]);

  /* Convert raw counts to g-units using selected full-scale range. */
  *ax = rawX / ACCEL_SCALE;
  *ay = rawY / ACCEL_SCALE;
  *az = rawZ / ACCEL_SCALE;
}
