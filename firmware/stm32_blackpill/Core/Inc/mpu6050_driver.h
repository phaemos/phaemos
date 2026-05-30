/**
 * mpu6050_driver.h - MPU6050 IMU driver header for STM32F411CEU6 (Black Pill)
 *
 * I target the STM32F4 HAL here because the Black Pill ships with an F411CEU6
 * and STM32CubeIDE generates HAL-based projects by default, so staying in HAL
 * avoids mixing abstraction layers and keeps the project portable to other
 * F4-series chips.
 */

#ifndef MPU6050_DRIVER_H
#define MPU6050_DRIVER_H

#include "stm32f4xx_hal.h"

/* ---------------------------------------------------------------------
 * I2C address
 * I shift left by 1 because STM32 HAL uses 8-bit I2C addresses (the 7-bit
 * address occupies bits [7:1] and the R/W bit is bit 0 which HAL manages).
 * AD0 tied to GND means the 7-bit address is 0x68.
 * --------------------------------------------------------------------- */
#define MPU6050_I2C_ADDR        (0x68 << 1)

/* ---------------------------------------------------------------------
 * Register map - only the registers this driver touches
 * I define these as macros rather than an enum so they can be passed
 * directly to HAL_I2C_Mem_Read without a cast.
 * --------------------------------------------------------------------- */
#define MPU6050_PWR_MGMT_1      0x6B    /* Power management - write 0x00 to wake */
#define MPU6050_CONFIG          0x1A    /* DLPF and FSYNC config */
#define MPU6050_GYRO_CONFIG     0x1B    /* Full-scale gyro range */
#define MPU6050_ACCEL_CONFIG    0x1C    /* Full-scale accel range */
#define MPU6050_ACCEL_XOUT_H    0x3B    /* First accel register (6 bytes: X,Y,Z each 2 bytes big-endian) */
#define MPU6050_GYRO_XOUT_H     0x43    /* First gyro register (6 bytes: X,Y,Z each 2 bytes big-endian) */

/* ---------------------------------------------------------------------
 * Data structure
 * I pack all six axes into one struct so callers can pass a single pointer
 * and avoid managing six separate variables in the main sampling loop.
 * --------------------------------------------------------------------- */
typedef struct {
    float accel_x;  /* Acceleration X in g-units */
    float accel_y;  /* Acceleration Y in g-units */
    float accel_z;  /* Acceleration Z in g-units */
    float gyro_x;   /* Angular rate X in degrees/s */
    float gyro_y;   /* Angular rate Y in degrees/s */
    float gyro_z;   /* Angular rate Z in degrees/s */
} MPU6050_Data;

/* ---------------------------------------------------------------------
 * Public API
 * --------------------------------------------------------------------- */

/**
 * MPU6050_Init - Wake the sensor and configure measurement ranges.
 * @hi2c: pointer to the HAL I2C handle (MX_I2C1_Init must have run first)
 * Returns HAL_OK on success, HAL_ERROR or HAL_TIMEOUT on failure.
 */
HAL_StatusTypeDef MPU6050_Init(I2C_HandleTypeDef *hi2c);

/**
 * MPU6050_ReadAccel - Read only the three accelerometer axes.
 * @hi2c:  pointer to HAL I2C handle
 * @data:  output struct (only accel_x/y/z are written; gyro fields untouched)
 * Returns HAL_OK on success.
 * I provide this lighter function for the vibration node's 100Hz ISR where
 * reading only 6 bytes instead of 14 reduces the I2C bus time per interrupt.
 */
HAL_StatusTypeDef MPU6050_ReadAccel(I2C_HandleTypeDef *hi2c, MPU6050_Data *data);

/**
 * MPU6050_ReadAll - Read all six axes (accel + gyro) in one transaction.
 * @hi2c:  pointer to HAL I2C handle
 * @data:  output struct (all six fields written)
 * Returns HAL_OK on success.
 * I burst-read all 14 bytes (accel + temp + gyro) in one Mem_Read call to
 * minimise I2C overhead and ensure all axes are sampled at the same instant.
 */
HAL_StatusTypeDef MPU6050_ReadAll(I2C_HandleTypeDef *hi2c, MPU6050_Data *data);

#endif /* MPU6050_DRIVER_H */
