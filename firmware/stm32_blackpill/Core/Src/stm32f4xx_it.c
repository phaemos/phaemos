/**
 * stm32f4xx_it.c - interrupt handlers for the vibration node
 *
 * the names match the weak aliases in the startup file, so defining them
 * here is all that is needed to take over a vector.
 */

#include "main.h"
#include "stm32f4xx_it.h"

/* every fault ends in Error_Handler, which blinks the LED with a busy loop.
 * a silent hang would look the same as a dead board, so the blink is the only
 * way to tell a fault apart from a missing power supply. */
void NMI_Handler(void)
{
    Error_Handler();
}

void HardFault_Handler(void)
{
    Error_Handler();
}

void MemManage_Handler(void)
{
    Error_Handler();
}

void BusFault_Handler(void)
{
    Error_Handler();
}

void UsageFault_Handler(void)
{
    Error_Handler();
}

void SVC_Handler(void)
{
}

void DebugMon_Handler(void)
{
}

void PendSV_Handler(void)
{
}

/* SysTick advances the HAL tick that every blocking HAL timeout depends on.
 * it runs at priority 0 (see TICK_INT_PRIORITY) so it is never held off by
 * the TIM2 interrupt. */
void SysTick_Handler(void)
{
    HAL_IncTick();
}

void TIM2_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&htim2);
}

/* the receive interrupt feeds the ping parser.  it runs at priority 1 like
 * TIM2 so SysTick can still pre-empt it. */
void USART1_IRQHandler(void)
{
    HAL_UART_IRQHandler(&huart1);
}
