/**
 * uart_output.h - UART formatting layer for the vibration node
 *
 * I keep UART formatting in its own translation unit so that if the output
 * protocol changes (e.g. switching to JSON or MQTT framing) only this file
 * and its .c companion need to be touched, leaving all sensor and DSP code
 * untouched.
 */

#ifndef UART_OUTPUT_H
#define UART_OUTPUT_H

#include "stm32f4xx_hal.h"

/**
 * UART_SendVibrationData - Format and transmit one vibration telemetry line.
 * @huart:        pointer to the HAL UART handle (USART1 on PA9/PA10)
 * @ax:           mean accelerometer X over the last 1-second window (g)
 * @ay:           mean accelerometer Y over the last 1-second window (g)
 * @az:           mean accelerometer Z over the last 1-second window (g)
 * @magnitude:    RMS vector magnitude of the acceleration (g)
 * @fft_peak_hz:  dominant vibration frequency from the DFT (Hz)
 *
 * Output format (CRLF terminated):
 *   "VIB:%.2f,%.2f,%.2f,MAG:%.2f,FFT_PEAK:%.1fHz\r\n"
 *
 * Example:
 *   "VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz\r\n"
 */
void UART_SendVibrationData(UART_HandleTypeDef *huart,
                            float ax, float ay, float az,
                            float magnitude, float fft_peak_hz);

#endif /* UART_OUTPUT_H */
