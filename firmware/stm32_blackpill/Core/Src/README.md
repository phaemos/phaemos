# STM32 Source Files

| File | Purpose |
|---|---|
| main.c | Entry point - initialises peripherals, runs the sample/FFT/transmit loop |
| fft.c | FFT implementation - applies window function, runs DFT, extracts peak frequency |
| mpu6050_driver.c | MPU6050 SPI driver - configures sensor, reads raw XYZ accelerometer data |
| uart_output.c | UART transmission - formats FFT peak Hz and vibration magnitude as JSON for ESP32 |
