# STM32 Source Files

Files marked "no HAL" include no HAL header, so each one also builds on a
normal computer and has a host test in `../../test_host/`. See the folder
README one level up for the line format, the status bits, the watchdog, the
ping and how to run the tests. We have not yet run any of this firmware on a
board.

| File | HAL | Purpose |
|---|---|---|
| main.c | yes | Entry point - reset cause, clock and peripheral set-up, I2C bus recovery, watchdog, the sample/window/line loop and the ping service. Wires the plain C files together |
| stm32f4xx_it.c | yes | Interrupt handlers - SysTick, TIM2, USART1 and the fault handlers |
| stm32f4xx_hal_msp.c | yes | Clock enables, pin modes and interrupt priorities for each peripheral |
| mpu6050_driver.c | yes | MPU6050 I2C driver - configures the sensor, reads raw XYZ counts, WHO_AM_I and the power register |
| uart_output.c | yes | Interrupt driven transmit of a built line (it never blocks the loop) and interrupt driven receive into a ring buffer, with error recovery |
| fft.c | no | FFT peak frequency - built-in radix-2 FFT or CMSIS-DSP, chosen by a build flag |
| crc16.c | no | CRC-16/CCITT-FALSE for the line checksum |
| line.c | no | Builds the data line and the pong into one fixed buffer, with the length guard |
| window_stats.c | no | Window of raw samples - RMS and peak with the mean removed, stuck and clipping tests |
| status.c | no | Status word, reset cause mapping and the dropped flag |
| sensor_state.c | no | When the sensor counts as lost (five failed reads in a row) and when a zero-reading line is due (`SENSOR_MISSING` while lost, `NO_DATA` after two periods without a window, so the node is never silent for more than two periods). A read that fails quickly is retried once in the same tick |
| node_core.c | no | The per-tick logic `main.c` and the host test share: tick counting, window discard, the lost-sensor rule with the in-tick retry result, filling the window |
| tx_queue.c | no | The queue of messages for the UART transmitter: copy in, one at a time, a slot freed only when its transfer has finished |
| ping.c | no | Byte ring for the receive interrupt and the `PING:<n>` parser |
| uptime.c | no | Whole seconds since boot from the wrapping millisecond tick |
