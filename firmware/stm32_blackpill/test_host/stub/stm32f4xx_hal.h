/**
 * stub of the parts of stm32f4xx_hal.h that uart_output.c uses, so the real
 * uart_output.c builds on a host compiler.  the test supplies the behaviour of
 * HAL_UART_Transmit_IT and HAL_UART_Receive_IT (see test_uart.c).
 */

#ifndef STUB_STM32F4XX_HAL_H
#define STUB_STM32F4XX_HAL_H

#include <stddef.h>
#include <stdint.h>

typedef enum { HAL_OK = 0, HAL_ERROR = 1, HAL_BUSY = 2, HAL_TIMEOUT = 3 } HAL_StatusTypeDef;

#define HAL_UART_STATE_READY      0x20U
#define HAL_UART_STATE_BUSY_TX    0x21U
#define HAL_UART_STATE_BUSY_RX    0x22U

#define HAL_UART_ERROR_NONE       0x00U
#define HAL_UART_ERROR_PE         0x01U
#define HAL_UART_ERROR_NE         0x02U
#define HAL_UART_ERROR_FE         0x04U
#define HAL_UART_ERROR_ORE        0x08U

typedef struct { int dummy; } USART_TypeDef;
extern USART_TypeDef stub_usart1;
#define USART1 (&stub_usart1)

typedef struct
{
    USART_TypeDef     *Instance;
    volatile uint32_t  gState;
    volatile uint32_t  RxState;
    volatile uint32_t  ErrorCode;
} UART_HandleTypeDef;

HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *huart, uint8_t *pData, uint16_t Size);
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *huart, uint8_t *pData, uint16_t Size);
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart);

#endif /* STUB_STM32F4XX_HAL_H */
