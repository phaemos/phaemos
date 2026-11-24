# STM32 Header Files

| File | Purpose |
|---|---|
| main.h | Pin names, LED macros, shared handles and diagnostic counters |
| stm32f4xx_hal_conf.h | HAL configuration - only the modules the firmware uses |
| stm32f4xx_it.h | Interrupt handler declarations |
| fft.h | FFT declarations - peak frequency from accelerometer samples (no HAL dependency) |
| mpu6050_driver.h | MPU6050 I2C driver declarations - raw accelerometer counts, WHO_AM_I and power register reads |
| uart_output.h | Interrupt driven transmit of a built line (it never blocks the loop) and interrupt driven receive into a ring buffer |
| imu_config.h | Accelerometer range, full-scale counts and identity constants shared by the driver and the tests (no HAL dependency) |
| crc16.h | CRC-16/CCITT-FALSE (no HAL dependency) |
| line.h | Data line and pong builder, with the 160-byte limit (no HAL dependency) |
| window_stats.h | Window of raw samples and its statistics (no HAL dependency) |
| status.h | Status bits, reset cause mapping and status word (no HAL dependency) |
| tx_queue.h | Transmit queue (no HAL dependency) |
| ping.h | Receive ring and ping parser (no HAL dependency) |
| uptime.h | Seconds since boot across the tick wrap (no HAL dependency) |
| sensor_state.h | Lost-sensor rule and line pacing (no HAL dependency) |
| node_core.h | Per-tick logic shared by `main.c` and the host test (no HAL dependency) |
