/**
 * stm32f4xx_hal_conf.h - HAL configuration for the vibration node
 *
 * only the modules this firmware uses are enabled.  leaving the rest out
 * keeps the build small because each HAL source file compiles to nothing
 * when its module macro is not defined.
 */

#ifndef STM32F4xx_HAL_CONF_H
#define STM32F4xx_HAL_CONF_H

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------
 * module selection
 * DMA is enabled although no transfer uses it because the I2C and UART
 * handle types contain DMA handle pointers and need its header.
 * --------------------------------------------------------------------- */
#define HAL_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_I2C_MODULE_ENABLED
#define HAL_IWDG_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED

/* ---------------------------------------------------------------------
 * oscillator values in Hz
 * HSE_VALUE is normally set by the build flag in platformio.ini.  the guard
 * here is only a fallback with the same 25 MHz crystal value.
 * --------------------------------------------------------------------- */
#if !defined(HSE_VALUE)
#define HSE_VALUE               25000000U
#endif

#if !defined(HSE_STARTUP_TIMEOUT)
#define HSE_STARTUP_TIMEOUT     100U    /* ms */
#endif

#if !defined(HSI_VALUE)
#define HSI_VALUE               16000000U
#endif

#if !defined(LSI_VALUE)
#define LSI_VALUE               32000U
#endif

#if !defined(LSE_VALUE)
#define LSE_VALUE               32768U
#endif

#if !defined(LSE_STARTUP_TIMEOUT)
#define LSE_STARTUP_TIMEOUT     5000U   /* ms */
#endif

#if !defined(EXTERNAL_CLOCK_VALUE)
#define EXTERNAL_CLOCK_VALUE    12288000U
#endif

/* ---------------------------------------------------------------------
 * system configuration
 * TICK_INT_PRIORITY is 0 (the highest) rather than the template's lowest
 * value so SysTick always pre-empts TIM2 (priority 1).  blocking HAL calls
 * count timeouts with the SysTick counter and would stall if it were held
 * off by a lower or equal priority interrupt.
 * --------------------------------------------------------------------- */
#define VDD_VALUE                   3300U   /* mV */
#define TICK_INT_PRIORITY           0x00U
#define USE_RTOS                    0U
#define PREFETCH_ENABLE             1U
#define INSTRUCTION_CACHE_ENABLE    1U
#define DATA_CACHE_ENABLE           1U

/* callbacks are weak functions rather than registered pointers */
#define USE_HAL_I2C_REGISTER_CALLBACKS      0U
#define USE_HAL_TIM_REGISTER_CALLBACKS      0U
#define USE_HAL_UART_REGISTER_CALLBACKS     0U

/* ---------------------------------------------------------------------
 * module headers
 * --------------------------------------------------------------------- */
#ifdef HAL_RCC_MODULE_ENABLED
#include "stm32f4xx_hal_rcc.h"
#endif

#ifdef HAL_GPIO_MODULE_ENABLED
#include "stm32f4xx_hal_gpio.h"
#endif

#ifdef HAL_DMA_MODULE_ENABLED
#include "stm32f4xx_hal_dma.h"
#endif

#ifdef HAL_CORTEX_MODULE_ENABLED
#include "stm32f4xx_hal_cortex.h"
#endif

#ifdef HAL_FLASH_MODULE_ENABLED
#include "stm32f4xx_hal_flash.h"
#endif

#ifdef HAL_I2C_MODULE_ENABLED
#include "stm32f4xx_hal_i2c.h"
#endif

#ifdef HAL_IWDG_MODULE_ENABLED
#include "stm32f4xx_hal_iwdg.h"
#endif

#ifdef HAL_PWR_MODULE_ENABLED
#include "stm32f4xx_hal_pwr.h"
#endif

#ifdef HAL_TIM_MODULE_ENABLED
#include "stm32f4xx_hal_tim.h"
#endif

#ifdef HAL_UART_MODULE_ENABLED
#include "stm32f4xx_hal_uart.h"
#endif

/* ---------------------------------------------------------------------
 * parameter checking
 * left off to save flash.  define USE_FULL_ASSERT to enable it and provide
 * assert_failed in main.c.
 * --------------------------------------------------------------------- */
#ifdef USE_FULL_ASSERT
#define assert_param(expr) ((expr) ? (void)0U : assert_failed((uint8_t *)__FILE__, __LINE__))
void assert_failed(uint8_t *file, uint32_t line);
#else
#define assert_param(expr) ((void)0U)
#endif

#ifdef __cplusplus
}
#endif

#endif /* STM32F4xx_HAL_CONF_H */
