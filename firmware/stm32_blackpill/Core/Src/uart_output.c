/**
 * uart_output.c - UART telemetry formatter for the vibration node
 *
 * I isolate all string formatting in this file so the output protocol can
 * be changed (e.g. to JSON or MQTT framing) without touching sensor or DSP
 * code.  The ESP32 upstream parser looks for the "VIB:" prefix to identify
 * packets from this node.
 */

#include "uart_output.h"
#include <stdio.h>   /* snprintf */
#include <string.h>  /* strlen */

/* I size the buffer to 128 bytes which is well above the worst-case formatted
 * length (around 60 characters) to give comfortable headroom.  I chose 128
 * because it is a power of two and matches the typical UART DMA buffer
 * alignment recommendation in STM32 AN4671. */
#define TX_BUF_SIZE  128U

/**
 * UART_SendVibrationData - Format and transmit one telemetry line.
 *
 * I use snprintf rather than sprintf to prevent buffer overrun if floats
 * format wider than expected (e.g. NaN or Inf representations can be longer
 * than normal float strings on some libc implementations).
 *
 * I use HAL_UART_Transmit in blocking mode rather than DMA because this
 * function is called once per second from the main loop - not from an ISR -
 * so blocking for the ~5 ms it takes to transmit 60 bytes at 9600 baud is
 * acceptable and avoids the complexity of managing a DMA completion callback
 * just for a 1 Hz heartbeat.
 */
void UART_SendVibrationData(UART_HandleTypeDef *huart,
                            float ax, float ay, float az,
                            float magnitude, float fft_peak_hz)
{
    char buf[TX_BUF_SIZE];

    /* snprintf writes at most TX_BUF_SIZE-1 characters and always
     * null-terminates, so buf[TX_BUF_SIZE-1] == '\0' is guaranteed. */
    int len = snprintf(buf, TX_BUF_SIZE,
                       "VIB:%.2f,%.2f,%.2f,MAG:%.2f,FFT_PEAK:%.1fHz\r\n",
                       ax, ay, az, magnitude, fft_peak_hz);

    /* I guard against snprintf returning a negative value (encoding error)
     * or a value larger than the buffer (truncated output) before transmitting
     * to avoid sending garbled or incomplete lines to the upstream parser. */
    if (len > 0 && len < (int)TX_BUF_SIZE)
    {
        HAL_UART_Transmit(huart, (uint8_t *)buf, (uint16_t)len, 100U);
    }
}
