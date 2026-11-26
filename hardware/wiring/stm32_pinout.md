# STM32 Black Pill Vibration Node - Pin Assignment and Wiring Guide

This note covers the wiring of the STM32F411CEU6 Black Pill board that runs the vibration node. Every figure
below comes from the firmware in `firmware/stm32_blackpill/` and the file it comes from is named beside it.
If the firmware changes, change this note with it. The firmware has not yet run on a board, so none of this is
confirmed by measurement.

---

## Section 1: MPU6050 on I2C1

The node reads the MPU6050 at **100 kHz** (standard mode) over I2C1. The sensor sits on a cable and its
capacitance slows the edges, so 400 kHz is not used (`Core/Src/main.c`, `MX_I2C1_Init`).

| Signal | Black Pill pin | MPU6050 pin | Notes | Source |
|---|---|---|---|---|
| SCL | PB6 (I2C1_SCL, AF4) | SCL | open drain, no internal pull. 100 ohm series resistor recommended | `Core/Inc/main.h`, `Core/Src/stm32f4xx_hal_msp.c`, firmware README |
| SDA | PB7 (I2C1_SDA, AF4) | SDA | open drain, no internal pull. 100 ohm series resistor recommended | same |
| VCC | 3.3V | VCC | 3.3V only, do not connect to 5V | firmware README |
| GND | GND | GND | common ground | |
| AD0 | GND | AD0 | sets the I2C address to 0x68 | `Core/Inc/mpu6050_driver.h` (`MPU6050_I2C_ADDR`) |
| INT | not connected | INT | not used: sampling is driven by a timer. PA0 is the board's KEY button and only reaches the sensor INT line through a solder jumper that is open as made | `Core/Inc/main.h`, firmware README |

Pull-ups: the firmware turns the internal pulls off (`GPIO_NOPULL` in `stm32f4xx_hal_msp.c`), so the bus needs
external pull-ups to 3.3V. The usual carrier board has 4.7 kohm pull-ups on SCL and SDA. A bare breakout needs
them added. Check the carrier you use.

Sensor set-up written at start-up (`Core/Src/mpu6050_driver.c`): `PWR_MGMT_1` = 0x00 (wake), `CONFIG` = 0x03
(44 Hz low-pass), accelerometer range +/-2 g (16384 LSB per g), gyro +/-250 deg/s. The firmware checks
`WHO_AM_I` for 0x68 at start-up and every 100 windows.

If a sensor holds SDA low after a reset, the firmware pulses SCL up to nine times and makes a STOP before it starts
I2C (`I2C_BusRecover` in `main.c`).

---

## Section 2: UART link to the hub

The node sends a checksummed text line per window and answers a ping. Settings: 115200 baud, 8 data bits, no
parity, 1 stop bit (`MX_USART1_UART_Init` in `main.c`). Both boards use 3.3V logic, so no level shifter is
needed.

| Black Pill pin | Hub (ESP32) pin | Direction | Notes | Source |
|---|---|---|---|---|
| PA9 (USART1_TX, AF7) | GPIO18 (`STM32_RX_PIN`) | node to hub | the line, once per window | `Core/Src/stm32f4xx_hal_msp.c`, `STM32_RX_PIN`, `STM32_TX_PIN` and `STM32_BAUD` in `firmware/esp32/config.h` |
| PA10 (USART1_RX, AF7) | GPIO19 (`STM32_TX_PIN`) | hub to node | the ping, `PING:<n>` every 30 s | same and `LINK_PING_INTERVAL_MS` in `config.h` |
| GND | GND | | common ground is required | |

On the **revised** hub board the receive pins have 100 kohm pull-downs, so an unplugged cable reads as a steady
low and the hub reports `line_low` (`HAS_INPUT_PULLDOWNS` in `config.h`, set for the `esp32dev_revb` build). On the
**present** hub board there is no pull-down and the receive pin keeps its internal pull-up, so an unplugged cable
reads high and the hub reports a silent link. See `esp32_pinout.md`. The node does not enable an internal pull on
PA10. A comment in `stm32f4xx_hal_msp.c` says the Black Pill board pulls it up, which has not been checked against
the board.

### The line

One line per window, 1.28 s of simulated or real time, at most 160 bytes with CR LF (`Core/Inc/line.h`):

```text
VIB:x,y,z,MAG:m,FFT_PEAK:fHz,RMS:x,y,z,PK:p,ST:s,SEQ:n,UP:u,MT:a,RF:b,BR:c*CCCC\r\n
```

A worked example, built on a host computer by the firmware's own line code (the worked line in
`firmware/stm32_blackpill/test_host/test_line.c`), not captured from a board:

```text
VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz,RMS:0.012,0.010,0.031,PK:0.094,ST:0,SEQ:7,UP:9,MT:0,RF:0,BR:0*AD94
```

`CCCC` is CRC-16/CCITT-FALSE (polynomial 0x1021, start 0xFFFF, no reflection, no final XOR) over every byte before
the asterisk. The check value for `123456789` is `29B1` (`Core/Src/crc16.c`, `test_line.c`).

`ST` is a status bit mask (`Core/Inc/status.h`): 1 SENSOR_MISSING, 2 SENSOR_STUCK, 4 CLIPPING, 8 ID_MISMATCH,
16 RESET_WATCHDOG, 32 WINDOW_DROPPED, 64 RESET_BROWNOUT, 128 NO_DATA. `SEQ` counts lines sent since boot (first line
0, wraps at 65536). `UP` is whole seconds since boot.

The hub answers with a ping and expects a pong:

```text
hub to node:  PING:42\n
node to hub:  PONG:42*881F\r\n
```

The node answers within 500 ms. A pong is not a data line and does not move `SEQ` (`Core/Inc/ping.h`,
`Core/Inc/line.h`). The hub treats a link as silent after 15 s without a valid line (`SERIAL_STALE_MS`,
`LINK_SILENT_MS` in `config.h`).

---

## Section 3: Power

The firmware does not set the power arrangement, so this section is not from the source and should be checked
against the board you build.

| Option | Connection | Notes |
|---|---|---|
| USB Micro-B | on-board connector | convenient for development and flashing |
| External 3.3V | the 3V3 pin | share ground with the hub. Do not connect the 5V USB pin while powering from an external 3.3V rail |

The firmware reports a brown-out reset as `RESET_BROWNOUT` and a watchdog reset as `RESET_WATCHDOG` on the next
line. These come from the reset flags (`Core/Src/main.c`).

Programming uses the SWD header: SWDIO on PA13 and SWCLK on PA14 (firmware README, Flashing).

---

## Section 4: Clock and the 100 Hz sample tick

### Clock tree (`SystemClock_Config` in `Core/Src/main.c`, `HSE_VALUE` in `platformio.ini`)

| Parameter | Value |
|---|---|
| Source | HSE, the 25 MHz crystal on the board (`HSE_VALUE=25000000U`) |
| PLL M | 25 (1 MHz into the PLL) |
| PLL N | 192 (192 MHz VCO) |
| PLL P | 2 (SYSCLK 96 MHz) |
| PLL Q | 4 (48 MHz) |
| AHB | /1 (HCLK 96 MHz) |
| APB1 | /2 (PCLK1 48 MHz, limit 50 MHz) |
| APB2 | /1 (PCLK2 96 MHz) |
| Voltage scale | scale 1 |
| Flash latency | 3 wait states |

The internal 16 MHz oscillator is not used for the system clock. The watchdog runs from the internal LSI and starts
before the clock set-up, so a crystal that does not start ends in a reset about 4 s later and not in a hang.

### TIM2 (`MX_TIM2_Init` in `main.c`)

TIM2 sits on APB1. Because the APB1 prescaler is not 1, the timer clock is doubled: 2 x 48 MHz = 96 MHz.

```text
tick rate   = 96,000,000 / (PSC + 1) = 96,000,000 / 9,600 = 10,000 Hz   (PSC = 9599)
interrupt   = 10,000 / (ARR + 1)     = 10,000 / 100       = 100 Hz      (ARR = 99)
```

Auto-reload preload is disabled. The interrupt has priority 1, below SysTick at 0 (`stm32f4xx_hal_msp.c`,
`stm32f4xx_hal_conf.h`) and only sets a flag. The main loop reads the sensor on that flag.

### Samples

The firmware collects **128** samples per window (`FFT_SIZE` in `Core/Inc/fft.h`) at **100 Hz**
(`SAMPLE_RATE_HZ` in `main.h`), so a window is 1.28 s and the FFT bins are 0.78 Hz apart over 0 to 50 Hz.

### LED

The on-board LED is on PC13 and is lit when the pin is low (`main.h`). It toggles once per window while the sensor
is working, blinks at 1 Hz while the sensor is lost and blinks about 10 Hz in a fault (`main.c`).
