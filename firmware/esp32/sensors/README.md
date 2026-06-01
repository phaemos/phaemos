# ESP32 Sensor Modules

Each sensor has a `.h` header and `.cpp` implementation. Include the header in `esp32.ino` and call `init()` then `read()`.

| File pair | Sensor | Interface | Notes |
|---|---|---|---|
| bme280.h / .cpp | BME280 | I2C 0x76 | Temperature, humidity, pressure |
| mpu6050.h / .cpp | MPU6050 | I2C 0x68 | Accelerometer, gyroscope (6-axis) |
| ina219.h / .cpp | INA219 | I2C 0x40 | Bus voltage, current, power |
| mlx90614.h / .cpp | MLX90614 | I2C 0x5A | Non-contact IR surface temperature |
| vl53l0x.h / .cpp | VL53L0X | I2C 0x29 | Time-of-flight distance |
| as5600.h / .cpp | AS5600 | I2C 0x36 | Magnetic shaft angle and RPM |
| mq2.h / .cpp | MQ-2 | Analog GPIO34/35 | Gas level, alert threshold |
| ldr.h / .cpp | LDR | Analog GPIO33 | Ambient light level |
| ds18b20.h / .cpp | DS18B20 | OneWire GPIO4 | Contact temperature probe |
| fc28.h / .cpp | FC-28 | Analog GPIO36 | Moisture / water ingress |

All I2C sensors share SDA=GPIO21 and SCL=GPIO22. See `../../wiring/esp32_pinout.md` for full wiring details.
