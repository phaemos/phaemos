/**
 * stm32f4xx_hal_msp.c - low-level peripheral set-up called by the HAL
 *
 * the HAL calls these functions from HAL_Init and from each peripheral's
 * Init function.  clock enables and pin modes live here rather than in main.c
 * so that re-initialising a peripheral (for example after an I2C bus
 * recovery) also restores its pins.
 */

#include "main.h"

/* HAL_Init calls this first. */
void HAL_MspInit(void)
{
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    __HAL_RCC_PWR_CLK_ENABLE();
}

/* I2C1 on PB6 (SCL) and PB7 (SDA).  open drain with no internal pull: the
 * carrier board has 4.7 kohm pull-ups.  the internal ~40 kohm pull-ups
 * would only weaken the edges. */
void HAL_I2C_MspInit(I2C_HandleTypeDef *hi2c)
{
    if (hi2c->Instance != I2C1) return;

    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_I2C1_CLK_ENABLE();

    gpio.Pin       = I2C_SCL_Pin | I2C_SDA_Pin;
    gpio.Mode      = GPIO_MODE_AF_OD;
    gpio.Pull      = GPIO_NOPULL;
    gpio.Speed     = GPIO_SPEED_FREQ_LOW;  /* gentler edges for a cabled 100 kHz bus */
    gpio.Alternate = GPIO_AF4_I2C1;
    HAL_GPIO_Init(I2C_GPIO_Port, &gpio);
}

/* force-reset the peripheral so a half-finished transfer cannot leave the
 * BUSY flag set, then hand the pins back for bus recovery. */
void HAL_I2C_MspDeInit(I2C_HandleTypeDef *hi2c)
{
    if (hi2c->Instance != I2C1) return;

    __HAL_RCC_I2C1_FORCE_RESET();
    __HAL_RCC_I2C1_RELEASE_RESET();
    __HAL_RCC_I2C1_CLK_DISABLE();

    HAL_GPIO_DeInit(I2C_GPIO_Port, I2C_SCL_Pin | I2C_SDA_Pin);
}

/* USART1 on PA9 (TX) and PA10 (RX).  no pull on RX because the board pulls
 * PA10 up. */
void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
    if (huart->Instance != USART1) return;

    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_USART1_CLK_ENABLE();

    gpio.Pin       = UART_TX_Pin | UART_RX_Pin;
    gpio.Mode      = GPIO_MODE_AF_PP;
    gpio.Pull      = GPIO_NOPULL;
    gpio.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    gpio.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(UART_GPIO_Port, &gpio);

    /* receive is interrupt driven.  priority 1 matches TIM2 and sits below
     * SysTick so the HAL tick is never held off. */
    HAL_NVIC_SetPriority(USART1_IRQn, 1U, 0U);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
}

void HAL_UART_MspDeInit(UART_HandleTypeDef *huart)
{
    if (huart->Instance != USART1) return;

    HAL_NVIC_DisableIRQ(USART1_IRQn);
    __HAL_RCC_USART1_CLK_DISABLE();
    HAL_GPIO_DeInit(UART_GPIO_Port, UART_TX_Pin | UART_RX_Pin);
}

/* TIM2 interrupt priority is 1 so it sits below SysTick (priority 0, set by
 * TICK_INT_PRIORITY).  the callback only sets a flag but the lower priority
 * keeps the HAL tick running whatever TIM2 does. */
void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim)
{
    if (htim->Instance != TIM2) return;

    __HAL_RCC_TIM2_CLK_ENABLE();

    HAL_NVIC_SetPriority(TIM2_IRQn, 1U, 0U);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
}

void HAL_TIM_Base_MspDeInit(TIM_HandleTypeDef *htim)
{
    if (htim->Instance != TIM2) return;

    HAL_NVIC_DisableIRQ(TIM2_IRQn);
    __HAL_RCC_TIM2_CLK_DISABLE();
}
