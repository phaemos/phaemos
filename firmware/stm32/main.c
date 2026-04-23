/* ============================================================
 * PHAEMOS - STM32 Firmware
 * High-frequency MPU6050 sampling (100 Hz) via I2C
 * Outputs readings over UART to ESP32 or USB serial
 *
 * UART format (one line per reading):
 *   VX:0.12,VY:-0.04,VZ:9.81
 * ============================================================ */

#include "mpu6050_driver.h"
#include <stdio.h>
#include <string.h>

/* HAL_Delay is provided by STM32 HAL. Adjust peripheral init
 * (I2C handle, UART handle) to match your board pinout.      */

extern I2C_HandleTypeDef  hi2c1;
extern UART_HandleTypeDef huart2;

#define SAMPLE_INTERVAL_MS 10   /* 100 Hz */

int main(void) {
  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_I2C1_Init();
  MX_USART2_UART_Init();

  MPU6050_Init(&hi2c1);

  char buf[64];
  float ax, ay, az;

  while (1) {
    MPU6050_ReadAccel(&hi2c1, &ax, &ay, &az);

    int len = snprintf(buf, sizeof(buf),
                       "VX:%.4f,VY:%.4f,VZ:%.4f\r\n",
                       ax, ay, az);

    HAL_UART_Transmit(&huart2, (uint8_t *)buf, len, HAL_MAX_DELAY);
    HAL_Delay(SAMPLE_INTERVAL_MS);
  }
}
