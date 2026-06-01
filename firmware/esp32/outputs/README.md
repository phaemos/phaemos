# ESP32 Output Modules

Handles all output peripherals on the primary gateway node.

| File pair | Purpose | GPIO |
|---|---|---|
| buzzer.h / .cpp | PWM tone generation for alerts | GPIO25 |
| oled.h / .cpp | SSD1306 128x64 I2C display driver | I2C 0x3C |
| relay.h / .cpp | 4-channel relay switching for external loads | GPIO26/27/14/12 |
| rgb_led.h / .cpp | WS2812B addressable LED strip status indicator | GPIO13 |
