# STM32 Black Pill F411CEU6 - Vibration Node

This node samples the MPU6050 IMU at 100 Hz, runs a 128-point CMSIS-DSP
radix-2 FFT over each 1.28-second window, and emits one UART line per window:

```text
VIB:0.02,-0.01,1.01,MAG:1.01,FFT_PEAK:12.5Hz
```

---

## CMSIS-DSP dependency

The FFT uses `arm_rfft_fast_f32` from the CMSIS-DSP library included with
STM32CubeIDE. Three project settings must be configured before the first build.

### 1. Preprocessor defines

In **Project Properties -> C/C++ Build -> Settings -> MCU GCC Compiler ->
Preprocessor -> Defined symbols**, add:

```text
ARM_MATH_CM4
__FPU_PRESENT=1U
```

`ARM_MATH_CM4` selects the Cortex-M4 code path inside `arm_math.h`.
`__FPU_PRESENT` enables the FPU intrinsics that the DSP library uses.

### 2. Include path

In **Project Properties -> C/C++ Build -> Settings -> MCU GCC Compiler ->
Include paths**, add:

```text
Drivers/CMSIS/DSP/Include
```

This path is relative to the project root and is present in every
STM32CubeIDE project that uses the F4 HAL pack.

### 3. Linker library

In **Project Properties -> C/C++ Build -> Settings -> MCU GCC Linker ->
Libraries**:

| Field | Value |
| --- | --- |
| Library name | `arm_cortexM4lf_math` |
| Library search path | `Drivers/CMSIS/DSP/Lib/GCC` |

The `lf` suffix selects the little-endian FPU variant for the Cortex-M4F.

---

## STM32CubeIDE project setup

1. **New project**: File -> New -> STM32 Project, search for `STM32F411CEU6`.
2. **Project name**: `phaemos_vibration_node`.
3. Copy the files from `Core/Inc/` and `Core/Src/` into the generated project,
   replacing the auto-generated `main.c`.
4. Open the `.ioc` file and configure peripherals as described below.
5. Click **Generate Code** to regenerate the `MX_*_Init` function bodies.
6. Apply the CMSIS-DSP settings above (preprocessor, include path, linker).
7. Build with **Project -> Build All** (Ctrl+B).

---

## Peripheral configuration in CubeMX (.ioc)

### System clock - 96 MHz

| Parameter | Value |
| --- | --- |
| Clock source | HSE (25 MHz crystal) |
| PLL M divider | 25 |
| PLL N multiplier | 192 |
| PLL P divider | 2 |
| SYSCLK | 96 MHz |
| APB1 prescaler | 1 (PCLK1 = 96 MHz) |
| APB2 prescaler | 1 (PCLK2 = 96 MHz) |

### TIM2 - 100 Hz sampling timer

TIM2 is on APB1 and clocked at 96 MHz.

```text
Timer tick rate  = PCLK1 / (PSC + 1) = 96,000,000 / 9,600 = 10,000 Hz
Interrupt period = Timer tick rate / (ARR + 1) = 10,000 / 100 = 100 Hz
```

| CubeMX field | Value |
| --- | --- |
| Prescaler (PSC) | 9599 |
| Counter period (ARR) | 99 |
| Counter mode | Up |
| NVIC TIM2 global IRQ | Enable |

> Both PSC and ARR use (value - 1) because TIM2 counts from 0 to ARR inclusive.

The ISR collects 128 samples per window (1.28 seconds at 100 Hz). This matches
`FFT_SIZE` in `fft.h` - arm_rfft_fast_f32 requires a power-of-two input.

### I2C1 - MPU6050

| Pin | Function | CubeMX setting |
| --- | --- | --- |
| PB6 | I2C1_SCL | Alternate Function AF4 |
| PB7 | I2C1_SDA | Alternate Function AF4 |

CubeMX I2C1 settings:
- Speed mode: **Fast Mode (400 kHz)**
- Rise time: 100 ns
- Fall time: 10 ns

### USART1 - telemetry output

| Pin | Function | CubeMX setting |
| --- | --- | --- |
| PA9 | USART1_TX | Alternate Function AF7 |
| PA10 | USART1_RX | Alternate Function AF7 |

CubeMX USART1 settings:
- Baud rate: **115200**
- Word length: 8 bits
- Stop bits: 1
- Parity: None
- Mode: TX/RX

---

## MPU6050 wiring

```text
MPU6050 Pin    Black Pill Pin    Notes
-----------    --------------    -----
VCC            3.3V              The F411 is 3.3V; do NOT connect to 5V
GND            GND
SCL            PB6               100 ohm series resistor recommended
SDA            PB7               100 ohm series resistor recommended
AD0            GND               Sets I2C address to 0x68
INT            Not connected     Interrupt not used - timer-driven sampling
```

Pull-up resistors (4.7 kohm to 3.3V) are required on SCL and SDA. Many
MPU6050 breakout boards include these on-board; check your specific board.

---

## Flashing

### Via ST-Link V2

1. Connect ST-Link to the Black Pill 4-pin SWD header:
   - SWDIO -> A13
   - SWDCLK -> A14
   - GND -> GND
   - 3.3V -> 3.3V (only if not powered separately)
2. In STM32CubeIDE: **Run -> Run** (or Ctrl+F11) to flash and start.

### Via DFU (USB without ST-Link)

1. Hold **BOOT0** button, press and release **NRST**, then release **BOOT0**.
2. The Black Pill enumerates as a DFU device.
3. Use `dfu-util`:

   ```bash
   dfu-util -a 0 -s 0x08000000:leave -D build/phaemos_vibration_node.bin
   ```

4. Or use STM32CubeProgrammer with the DFU connection type.

---

## Verifying output

Connect a USB-to-serial adapter to PA9 (TX) and GND. Open a terminal at
115200 8N1. You should see one line every 1.28 seconds:

```text
VIB:0.02,-0.01,1.00,MAG:1.00,FFT_PEAK:0.8Hz
```

A `FFT_PEAK` near 0 Hz indicates no vibration (expected when stationary).
Tap the board to see the peak frequency change.

---

## FFT implementation notes

| Property | Value |
| --- | --- |
| Algorithm | CMSIS-DSP arm_rfft_fast_f32 (radix-2 real FFT) |
| Window size | 128 points |
| Sample rate | 100 Hz |
| Frequency resolution | 100 / 128 = 0.78 Hz per bin |
| Nyquist limit | 50 Hz |
| DC bin | Skipped (gravity dominates accel-Z DC) |
| Execution time | ~19 us at 96 MHz (vs ~171 us for the previous DFT) |

The `arm_rfft_fast_instance_f32` twiddle factors are computed once on first
call to `FFT_GetPeakFrequency`, after the FPU is enabled by `SystemClock_Config`.
The instance and output buffer are static - no heap allocation.
