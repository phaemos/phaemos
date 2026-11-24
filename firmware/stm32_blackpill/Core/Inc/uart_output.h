/**
 * uart_output.h - UART transmit and receive layer for the vibration node
 *
 * the line text itself is built in line.c, which has no HAL dependency.  this
 * file only moves bytes: an interrupt driven send and an interrupt driven
 * receive that hands every byte to a ring buffer.
 */

#ifndef UART_OUTPUT_H
#define UART_OUTPUT_H

#include <stddef.h>
#include <stdbool.h>
#include "stm32f4xx_hal.h"
#include "ping.h"
#include "tx_queue.h"

/**
 * transmit is interrupt driven and never blocks the main loop.  a 160 byte
 * line takes about 14 ms at 115200 baud, longer than one 10 ms sample tick, so
 * a blocking send would cost a tick whatever the order of the calls.
 *
 * every message is copied into the transmit queue (tx_queue.h) and goes out in
 * the order it arrived, one at a time.  a message that arrives while another
 * is on the wire waits behind it and is never written over it.  UART_TxService,
 * called from every pass of the main loop, starts the next one when the
 * previous transfer has finished.  a line or pong that finds no room is
 * dropped and counted (g_tx_skipped, g_pong_dropped).
 */
bool UART_QueueLine(const char *buf, size_t len);
bool UART_QueuePong(const char *buf, size_t len);
bool UART_LineSpace(void);
void UART_TxService(UART_HandleTypeDef *huart);

/**
 * UART_RxStart - begin interrupt driven receive into the given ring.
 * call once after the UART is initialised.
 */
void UART_RxStart(UART_HandleTypeDef *huart, ByteRing *ring);

/* receive errors seen since reset (framing, noise, parity and overrun), for
 * a debugger watch window */
extern volatile uint32_t g_rx_errors;

/* pongs dropped because the transmit queue held its limit of pongs */
extern volatile uint32_t g_pong_dropped;

/* times HAL_UART_Receive_IT refused to start again.  receive is restarted only
 * in the two callbacks, so a non-zero value means it has stopped */
extern volatile uint32_t g_rx_rearm_failed;

/* bytes dropped because the receive ring was full */
extern volatile uint32_t g_rx_dropped;

#endif /* UART_OUTPUT_H */
