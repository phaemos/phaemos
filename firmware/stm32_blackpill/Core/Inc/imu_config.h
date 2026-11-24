/**
 * imu_config.h - MPU6050 constants shared by the driver and the host-testable logic
 *
 * this header needs no HAL header, so the window statistics and the status
 * logic can use the same numbers as the driver without a second copy that
 * could drift.  the accelerometer range is set in MPU6050_Init: ACCEL_CONFIG
 * = 0x00 selects +/-2 g.
 */

#ifndef IMU_CONFIG_H
#define IMU_CONFIG_H

#include <stdbool.h>
#include <stdint.h>

/* +/-2 g full scale gives 16384 LSB per g (data sheet, accelerometer
 * specification table). */
#define IMU_ACCEL_RANGE_G       2
#define IMU_ACCEL_LSB_PER_G     16384

/* a raw sample is a signed 16-bit count.  full scale is reached at 32767 on
 * the positive side and -32768 on the negative side, 2 g exactly and the
 * sensor saturates there.  a sample at either limit has been cut off, so the
 * true acceleration was at least that large. */
#define IMU_RAW_FULL_SCALE_MAX  32767
#define IMU_RAW_FULL_SCALE_MIN  (-32768)

/* identity and power registers */
#define IMU_REG_WHO_AM_I        0x75U
#define IMU_WHO_AM_I_EXPECTED   0x68U
#define IMU_REG_PWR_MGMT_1      0x6BU
#define IMU_PWR_SLEEP_BIT       0x40U

/* true when the WHO_AM_I register holds the value of a genuine MPU6050 */
static inline bool IMU_IdIsExpected(uint8_t who_am_i)
{
    return who_am_i == IMU_WHO_AM_I_EXPECTED;
}

/* true when PWR_MGMT_1 shows the part has gone back to sleep, which a power
 * glitch can do without the bus noticing */
static inline bool IMU_IsAsleep(uint8_t pwr_mgmt_1)
{
    return (pwr_mgmt_1 & IMU_PWR_SLEEP_BIT) != 0U;
}

#endif /* IMU_CONFIG_H */
