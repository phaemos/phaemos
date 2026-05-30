/**
 * mpu6050_driver.c - MPU6050 I2C driver for STM32F411CEU6 (Black Pill)
 *
 * I use HAL_I2C_Mem_Read rather than two separate HAL_I2C_Master calls
 * because Mem_Read combines the register address write and data read in a
 * single I2C transaction with a repeated start, which the MPU6050 datasheet
 * requires.  Using two Master calls would produce a STOP condition between
 * the address write and the read, which can cause the sensor to reset its
 * internal register pointer before the data is clocked out.
 */

#include "mpu6050_driver.h"

/* I define the I2C timeout in ms as a named constant rather than a magic
 * number so it is easy to tune if the bus speed changes. */
#define I2C_TIMEOUT_MS  100U

/* Scale factors from the MPU6050 datasheet Section 4.17 / 4.19.
 * I use +/-2g accel range (ACCEL_CONFIG = 0x00) -> 16384 LSB/g.
 * I use +/-250 deg/s gyro range (GYRO_CONFIG = 0x00) -> 131 LSB/(deg/s). */
#define ACCEL_SCALE     16384.0f
#define GYRO_SCALE      131.0f

/**
 * MPU6050_Init - Wake the sensor and set measurement ranges.
 *
 * The MPU6050 powers up in sleep mode (PWR_MGMT_1 bit 6 = 1).
 * I write 0x00 to PWR_MGMT_1 to clear sleep and select the internal
 * 8 MHz oscillator as the clock source - sufficient for 100 Hz sampling.
 */
HAL_StatusTypeDef MPU6050_Init(I2C_HandleTypeDef *hi2c)
{
    HAL_StatusTypeDef status;
    uint8_t data;

    /* Wake up the MPU6050 by clearing the SLEEP bit in PWR_MGMT_1 */
    data = 0x00;
    status = HAL_I2C_Mem_Write(hi2c, MPU6050_I2C_ADDR,
                                MPU6050_PWR_MGMT_1, I2C_MEMADD_SIZE_8BIT,
                                &data, 1, I2C_TIMEOUT_MS);
    if (status != HAL_OK) return status;

    /* Configure DLPF to 44 Hz bandwidth (CONFIG register = 0x03).
     * I enable the DLPF to suppress high-frequency noise above 44 Hz that
     * would alias into the 100 Hz sample stream and corrupt the FFT. */
    data = 0x03;
    status = HAL_I2C_Mem_Write(hi2c, MPU6050_I2C_ADDR,
                                MPU6050_CONFIG, I2C_MEMADD_SIZE_8BIT,
                                &data, 1, I2C_TIMEOUT_MS);
    if (status != HAL_OK) return status;

    /* Set accelerometer range to +/-2g (ACCEL_CONFIG bits [4:3] = 00).
     * I choose +/-2g because most mechanical vibration in the intended use
     * case is below 2g; the higher resolution of the 16384 LSB/g setting
     * gives better FFT frequency resolution. */
    data = 0x00;
    status = HAL_I2C_Mem_Write(hi2c, MPU6050_I2C_ADDR,
                                MPU6050_ACCEL_CONFIG, I2C_MEMADD_SIZE_8BIT,
                                &data, 1, I2C_TIMEOUT_MS);
    if (status != HAL_OK) return status;

    /* Set gyro range to +/-250 deg/s (GYRO_CONFIG bits [4:3] = 00).
     * I keep the gyro at maximum sensitivity because gyro data is currently
     * not used in the FFT path but may be useful for orientation filtering
     * in a future firmware revision. */
    data = 0x00;
    status = HAL_I2C_Mem_Write(hi2c, MPU6050_I2C_ADDR,
                                MPU6050_GYRO_CONFIG, I2C_MEMADD_SIZE_8BIT,
                                &data, 1, I2C_TIMEOUT_MS);

    return status;
}

/**
 * MPU6050_ReadAccel - Read only the three accelerometer axes (6 bytes).
 *
 * I read only accel here rather than all 14 bytes to keep the I2C transaction
 * short.  At 400 kHz I2C, 6 data bytes + overhead takes ~0.2 ms compared to
 * ~0.4 ms for 14 bytes.  In the TIM2 ISR at 100 Hz every microsecond saved
 * reduces jitter in the sample timing.
 */
HAL_StatusTypeDef MPU6050_ReadAccel(I2C_HandleTypeDef *hi2c, MPU6050_Data *data)
{
    HAL_StatusTypeDef status;
    uint8_t raw[6];

    /* I use HAL_I2C_Mem_Read rather than two separate Master calls - see file
     * header for the rationale on repeated-start requirement. */
    status = HAL_I2C_Mem_Read(hi2c, MPU6050_I2C_ADDR,
                               MPU6050_ACCEL_XOUT_H, I2C_MEMADD_SIZE_8BIT,
                               raw, 6, I2C_TIMEOUT_MS);
    if (status != HAL_OK) return status;

    /* The MPU6050 outputs data big-endian: high byte first, then low byte.
     * I cast to int16_t before dividing to correctly handle negative values. */
    data->accel_x = (float)((int16_t)(raw[0] << 8 | raw[1])) / ACCEL_SCALE;
    data->accel_y = (float)((int16_t)(raw[2] << 8 | raw[3])) / ACCEL_SCALE;
    data->accel_z = (float)((int16_t)(raw[4] << 8 | raw[5])) / ACCEL_SCALE;

    return HAL_OK;
}

/**
 * MPU6050_ReadAll - Read accel, temperature, and gyro in one burst (14 bytes).
 *
 * I read all 14 bytes in a single Mem_Read call so that all axes are captured
 * at the same sensor measurement instant.  Reading accel and gyro in separate
 * transactions introduces inter-axis skew that corrupts orientation estimates.
 */
HAL_StatusTypeDef MPU6050_ReadAll(I2C_HandleTypeDef *hi2c, MPU6050_Data *data)
{
    HAL_StatusTypeDef status;
    /* 14 bytes: ACCEL_X(2) + ACCEL_Y(2) + ACCEL_Z(2) + TEMP(2) + GYRO_X(2)
     *           + GYRO_Y(2) + GYRO_Z(2).  I declare the buffer here rather
     *           than as a module-level variable to keep the driver re-entrant
     *           if it is ever called from multiple contexts. */
    uint8_t raw[14];

    status = HAL_I2C_Mem_Read(hi2c, MPU6050_I2C_ADDR,
                               MPU6050_ACCEL_XOUT_H, I2C_MEMADD_SIZE_8BIT,
                               raw, 14, I2C_TIMEOUT_MS);
    if (status != HAL_OK) return status;

    data->accel_x = (float)((int16_t)(raw[0]  << 8 | raw[1]))  / ACCEL_SCALE;
    data->accel_y = (float)((int16_t)(raw[2]  << 8 | raw[3]))  / ACCEL_SCALE;
    data->accel_z = (float)((int16_t)(raw[4]  << 8 | raw[5]))  / ACCEL_SCALE;
    /* raw[6] and raw[7] are temperature - I skip them here because the
     * vibration node does not log temperature from the IMU (the separate
     * BME280 on the ambient node handles environmental temperature). */
    data->gyro_x  = (float)((int16_t)(raw[8]  << 8 | raw[9]))  / GYRO_SCALE;
    data->gyro_y  = (float)((int16_t)(raw[10] << 8 | raw[11])) / GYRO_SCALE;
    data->gyro_z  = (float)((int16_t)(raw[12] << 8 | raw[13])) / GYRO_SCALE;

    return HAL_OK;
}
