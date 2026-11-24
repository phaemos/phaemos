# ESP32 Output Modules

Handles all output peripherals on the primary gateway node.

| File pair | Purpose | GPIO |
|---|---|---|
| buzzer.h / .cpp | Non-blocking 2 kHz tone patterns for alerts (NPN stage, HIGH on) | GPIO25 |
| oled.h / .cpp | SSD1306 128x64 I2C display driver | I2C 0x3C |
| relay.h / .cpp | 4-channel relay switching for external loads (active HIGH). Remembers the commanded state so a warm reset can restore it | GPIO13/12/23/27 (relay 3 is GPIO14 on the present board) |
| rgb_led.h / .cpp | WS2812B addressable LED strip status indicator, current capped at 1.2 A | GPIO26 |
| temp_judge.h / .cpp | Judges the over-temperature state from the BME280, the DS18B20 and the MLX90614. Each source has its own count and latch. No Arduino types, so `test_host/test_temp.cpp` covers it | none |
| hub_core.h / .cpp | The order of `setup()`, the restore after a warm reset, the board check and the judgement of every reading pass, behind a platform interface. No Arduino types, so `test_host/test_core.cpp` replays whole scenarios through it. `esp32.ino` is the wiring that implements the platform | none |
| status_logic.h / .cpp | The panel precedence (CRITICAL, WARNING, FAULT, NORMAL), the alternation between a warning and a fault and the fault codes. No Arduino types, so `test_host/test_post.cpp` covers it | none |
| saved_state.h / .cpp | The state kept in RTC memory across a warm reset: the per-source counts and latches, the relay mask, the reset-loop count, the set-up markers and strikes, the magic word, the checksum and the restore decisions. No Arduino types | none |
| status_led.h / .cpp | Red, amber and green panel LEDs (red and amber LOW on, green HIGH on) | GPIO15/5/2 |
