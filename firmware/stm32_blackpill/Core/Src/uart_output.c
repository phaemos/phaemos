/**
 * uart_output.c - UART transmit and receive for the vibration node
 *
 * transmit is interrupt driven from a queue, one message at a time.  a
 * blocking send of a 160 byte line would hold the main loop for about 14 ms,
 * longer than the 10 ms sample tick and cost a sample.  DMA would add
 * channel set-up for no gain at this rate.  the HAL reads the bytes from the
 * queue's slot while the transfer runs, so a slot is released only when the
 * HAL reports the transfer finished.
 *
 * receive is one byte at a time by interrupt.  the interrupt does the least
 * it can: it pushes the byte into a ring and re-arms.  the parser runs in
 * the main loop.
 */

#include "uart_output.h"

static uint8_t           s_rx_byte;
static ByteRing         *s_ring;
static TxQueue           s_tx;

volatile uint32_t g_rx_errors       = 0U;
volatile uint32_t g_rx_dropped      = 0U;
volatile uint32_t g_pong_dropped    = 0U;
volatile uint32_t g_rx_rearm_failed = 0U;

bool UART_QueueLine(const char *buf, size_t len)
{
    return TxQueue_PushLine(&s_tx, (const uint8_t *)buf, len);
}

bool UART_QueuePong(const char *buf, size_t len)
{
    bool ok = TxQueue_PushPong(&s_tx, (const uint8_t *)buf, len);
    g_pong_dropped = s_tx.pongs_dropped;
    return ok;
}

bool UART_LineSpace(void)
{
    return TxQueue_LineSpace(&s_tx);
}

void UART_TxService(UART_HandleTypeDef *huart)
{
    /* the HAL is free again once the last byte has left */
    if (huart->gState != HAL_UART_STATE_READY)
    {
        return;
    }
    if (s_tx.in_flight)
    {
        TxQueue_Done(&s_tx);    /* the message that was going out has finished */
    }

    const uint8_t *data;
    uint16_t       len;
    if (TxQueue_Start(&s_tx, &data, &len))
    {
        if (HAL_UART_Transmit_IT(huart, (uint8_t *)data, len) != HAL_OK)
        {
            /* not started: put it back to be tried again on the next pass */
            s_tx.in_flight = false;
        }
    }
}

void UART_RxStart(UART_HandleTypeDef *huart, ByteRing *ring)
{
    s_ring = ring;
    if (HAL_UART_Receive_IT(huart, &s_rx_byte, 1U) != HAL_OK)
    {
        g_rx_rearm_failed++;
    }
}

/* one byte has arrived */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance != USART1) return;

    /* a framing, noise or parity error is reported in ErrorCode before this
     * callback runs and the byte that came with it is not trustworthy.  it
     * is dropped rather than fed to the parser.  the error callback that
     * follows does the counting. */
    if ((huart->ErrorCode & (HAL_UART_ERROR_FE | HAL_UART_ERROR_NE | HAL_UART_ERROR_PE)) == 0U)
    {
        if ((s_ring != NULL) && !ByteRing_Push(s_ring, s_rx_byte))
        {
            g_rx_dropped++;
        }
    }

    /* the HAL stops after every byte in this mode, so arm the next one */
    if (HAL_UART_Receive_IT(huart, &s_rx_byte, 1U) != HAL_OK)
    {
        g_rx_rearm_failed++;
    }
}

/* an overrun, framing, noise or parity error.  the HAL ends the receive on an
 * overrun and leaves the state READY and it would stay stopped for ever, so
 * start it again here.  after the lesser errors it is still running and the
 * state is BUSY_RX, so nothing is done.
 *
 * this and the callback above are the only places that restart receive and
 * both run in the interrupt.  the main loop does not restart it: a write to
 * the control register from the main loop is not atomic against this
 * interrupt and the transmit interrupt and could re-enable the transmit
 * interrupt with nothing left to send.  every way the HAL can stop receiving
 * (a completed byte or an overrun) ends in one of the two callbacks. */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance != USART1) return;

    g_rx_errors++;
    if (huart->RxState == HAL_UART_STATE_READY)
    {
        if (HAL_UART_Receive_IT(huart, &s_rx_byte, 1U) != HAL_OK)
        {
            g_rx_rearm_failed++;
        }
    }
}
