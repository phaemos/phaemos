# STM32 Black Pill Vibration Node - Pin Assignment and Wiring Guide

This document covers all wiring for the STM32F411CEU6 Black Pill board acting as the dedicated vibration analysis node in Phaemos.

---

## Section 1: MPU6050 - I2C1 Connection

The STM32 reads the MPU6050 at 400 kHz (fast mode) over I2C1. Place 4.7k ohm pull-ups from SDA and SCL to 3.3V.

| Pin | STM32 Pin | MPU6050 Pin | Notes |
|---|---|---|---|
| SCL | PB6 (I2C1_SCL) | SCL | 4.7k pull-up to 3.3V |
| SDA | PB7 (I2C1_SDA) | SDA | 4.7k pull-up to 3.3V |
| VCC | 3.3V | VCC | 3.3V only - do not connect to 5V |
| GND | GND | GND | Common ground |
| AD0 | GND | AD0 | Ties I2C address to 0x68 |
| INT | PA0 (optional) | INT | Optional data-ready interrupt; leave unconnected if polling |

---

## Section 2: UART Output to ESP32

The STM32 streams FFT results and raw vibration data to the ESP32 over UART1 at 115200 baud. Both boards run at 3.3V logic so no level shifter is required.

| STM32 Pin | ESP32 Pin | Direction | Notes |
|---|---|---|---|
| PA9 (USART1_TX) | GPIO18 (UART2 RX) | STM32 -> ESP32 | Direct wire, no level shifter needed |
| PA10 (USART1_RX) | GPIO19 (UART2 TX) | ESP32 -> STM32 | Used for commands from ESP32 if needed |
| GND | GND | - | Common ground between boards is required |

---

## Section 3: Power Supply

The Black Pill can be powered in two ways:

| Option | Connection | Notes |
|---|---|---|
| USB Micro-B | On-board USB connector | Convenient for development and flashing; provides regulated 3.3V |
| External 3.3V | 3V3 pin (pin 1) | Power from the AMS1117-3.3 regulator on the main ESP32 board; share GND |

For final deployment, power the Black Pill from the shared 3.3V rail. Ensure the AMS1117 is rated for sufficient current (the Black Pill draws around 40-80mA under normal operation).

Do not connect the Vbus (5V USB) pin when powering from the external 3.3V rail, as this will back-feed into whatever USB host was connected.

---

## Section 4: TIM2 Clock Configuration for 100Hz Sampling

The STM32F411 runs at 96 MHz when using the internal PLL with default STM32CubeIDE settings (HSI 16 MHz x 6 = 96 MHz).

**Goal:** generate a 100 Hz interrupt (one interrupt every 10 ms) to trigger MPU6050 reads.

**Timer math:**

The APB1 timer clock is 96 MHz (when APB1 prescaler = 1, timer clock = HCLK).

Timer update frequency = Timer clock / ((PSC + 1) x (ARR + 1))

**Option A - 1ms tick base, 100Hz interrupt:**
- PSC = 9 gives a tick rate of 96 MHz / 10 = 9.6 MHz - not a clean 1ms tick.
- Better: PSC = 95 gives 96 MHz / 96 = 1 MHz (1 microsecond ticks). ARR = 9999 gives 1 MHz / 10000 = 100 Hz exactly.

**Option B - direct 100Hz:**
- PSC = 9599 gives 96 MHz / 9600 = 10 kHz. ARR = 99 gives 10 kHz / 100 = 100 Hz exactly.

Both options produce a 100 Hz interrupt. Option A is preferred when you also need a 1 MHz timebase for other timing (e.g. ultrasonic sensors). Option B uses a larger prescaler and is simpler to reason about.

In STM32CubeIDE, set TIM2 in the .ioc file:
- Clock source: Internal Clock
- Prescaler (PSC): 9599
- Counter Period (ARR): 99
- Auto-reload preload: Enable
- Enable TIM2 global interrupt in NVIC settings

The HAL_TIM_PeriodElapsedCallback will fire at 100 Hz. Collect 256 or 512 samples before running the FFT.
