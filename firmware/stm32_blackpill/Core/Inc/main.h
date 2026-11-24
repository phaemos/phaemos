/**
 * main.h - shared declarations for the vibration node firmware
 *
 * keep pin names and the few cross-file globals here so the interrupt file
 * and the MSP file do not need to know about main.c internals.
 */

#ifndef MAIN_H
#define MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"

/* PC13 drives the on-board LED from 3.3 V through a resistor, so the LED is
 * lit when the pin is LOW.  the macros hide that inversion from callers. */
#define LED_GPIO_Port   GPIOC
#define LED_Pin         GPIO_PIN_13
#define LED_ON()        HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_RESET)
#define LED_OFF()       HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_SET)
#define LED_TOGGLE()    HAL_GPIO_TogglePin(LED_GPIO_Port, LED_Pin)

/* I2C1 pins on the carrier board.  PA0 is deliberately unused: the sensor
 * INT line only reaches it through a solder jumper that is open as made and
 * PA0 is also the board's KEY button. */
#define I2C_GPIO_Port   GPIOB
#define I2C_SCL_Pin     GPIO_PIN_6
#define I2C_SDA_Pin     GPIO_PIN_7

/* USART1 pins.  the board pulls PA10 up so no internal pull is needed. */
#define UART_GPIO_Port  GPIOA
#define UART_TX_Pin     GPIO_PIN_9
#define UART_RX_Pin     GPIO_PIN_10

/* sampling rate in Hz.  TIM2 is configured for this in MX_TIM2_Init. */
#define SAMPLE_RATE_HZ  100.0f

/* peripheral handles, defined in main.c */
extern I2C_HandleTypeDef   hi2c1;
extern UART_HandleTypeDef  huart1;
extern TIM_HandleTypeDef   htim2;
extern IWDG_HandleTypeDef  hiwdg;

/* diagnostic counters, defined in main.c.  they are plain globals so a
 * debugger watch window shows whether the node is keeping up.  they are also
 * sent on every line as MT, RF and BR. */
extern volatile uint32_t g_missed_ticks;      /* TIM2 ticks the main loop did not consume in time */
extern volatile uint32_t g_read_failures;     /* failed sensor reads since reset */
extern volatile uint32_t g_bus_recoveries;    /* I2C bus recoveries since reset */
extern volatile uint32_t g_tx_skipped;        /* lines skipped because the previous one was still going out */
extern volatile uint8_t  g_imu_id;            /* WHO_AM_I of the last identity check, 0 until one has worked */

/* fatal fault indicator: fast LED blink forever, never returns */
void Error_Handler(void) __attribute__((noreturn));

#ifdef __cplusplus
}
#endif

#endif /* MAIN_H */
