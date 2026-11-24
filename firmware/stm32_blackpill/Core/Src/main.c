/**
 * main.c - Vibration node firmware for STM32F411CEU6 (Black Pill)
 *
 * sampling strategy:
 * use TIM2 at 100 Hz to drive sampling rather than a HAL_Delay loop because
 * a delay-based approach accumulates drift: each I2C read takes a variable
 * ~0.8 ms so a 10 ms delay produces an actual period of ~10.8 ms, yielding
 * an effective sample rate of ~93 Hz instead of 100 Hz.  TIM2 fires at an
 * exact hardware-timed period regardless of I2C transaction length, so the
 * tick period is exact and does not drift.  the read follows the tick within
 * one pass of the loop.  the line is sent by interrupt from a buffer, so the
 * 14 ms it takes on the wire never holds the loop and the work after the
 * 128th read (statistics, FFT, number formatting) is estimated at a few ms,
 * well inside one tick.  the read instant therefore stays close to the tick.
 * none of this has been timed on a board.  the FFT relies on the period
 * (frequency = bin * sample_rate / N).
 *
 * the TIM2 interrupt only sets a flag.  the sensor is read in the main loop
 * because blocking HAL calls count their timeouts with the SysTick counter
 * and can hang when called from an interrupt that SysTick cannot pre-empt.
 *
 * this file keeps the hardware calls.  everything that needs no hardware
 * lives in plain C files that also build on a host compiler: crc16.c,
 * line.c, window_stats.c, status.c, sensor_state.c, node_core.c, ping.c,
 * tx_queue.c, uptime.c and fft.c.
 *
 * set-up code:
 * the SystemClock_Config, MX_GPIO_Init, MX_I2C1_Init, MX_USART1_UART_Init and
 * MX_TIM2_Init functions are written by hand in this file.  the pin modes and
 * clock enables they trigger live in stm32f4xx_hal_msp.c.
 *
 * watchdog timing (the independent watchdog, IWDG):
 * the IWDG runs from the LSI, nominally 32 kHz.  with the divide-by-64
 * prescaler and a reload of 2000 the timeout is 2000 * 64 / 32000 = 4.0 s.
 * the LSI is only specified as 17 to 47 kHz, so the real timeout lies between
 * about 2.7 s (47 kHz) and 7.5 s (17 kHz).  the 2.7 s end is the one the
 * margin below is measured against.  the watchdog starts straight after
 * HAL_Init, before the clock set-up, so a crystal that never starts ends in a
 * reset and not in a halt.  start-up needs well under a second.
 *
 * the longest legitimate stretch between two refreshes is one tick pass.
 * the figures come from reading the code and the HAL driver (1.8.5) and have not
 * been measured.  the HAL takes one deadline per call, counted from the start
 * of the call, plus a fixed 25 ms wait while the bus reports busy:
 *   - one accel read: about 1 ms.  on a hung bus it ends at the 20 ms
 *     timeout or after 25 ms when the bus is busy, so a failed read is
 *     bounded by about 25 ms.  a retry (3 ms timeout) follows only a quick
 *     failure.
 *   - Sensor_Recover: bus recovery under 1 ms, then the init writes, which
 *     stop at the first failure (about 25 ms), then one identity read
 *     (about 25 ms).  about 50 ms at worst.
 *   - the periodic identity and sleep check: up to three reads and an init,
 *     but only on a pass whose read just succeeded, so the bus is alive.
 *   - the window work: statistics, FFT and number formatting, estimated at
 *     a few ms.
 *   - sending a line or a pong costs the loop nothing: it is queued and the
 *     UART interrupt does the rest.
 * a failed read followed by a recovery is the worst pass: about 75 ms.  that
 * is about 35 times smaller than the shortest possible timeout.  a normal
 * pass is a few ms.  the idle spin between ticks refreshes the watchdog too,
 * but only while ticks keep arriving, so a stopped TIM2 is not hidden.
 */

#include "main.h"
#include "mpu6050_driver.h"
#include "fft.h"
#include "uart_output.h"
#include "window_stats.h"
#include "status.h"
#include "line.h"
#include "ping.h"
#include "uptime.h"
#include "sensor_state.h"
#include "node_core.h"
#include "imu_config.h"

/* ---------------------------------------------------------------------
 * HAL peripheral handles
 * declare these at file scope so the MX_*_Init functions, the MSP file and
 * the interrupt file can all reach them without passing pointers through
 * every layer.
 * --------------------------------------------------------------------- */
I2C_HandleTypeDef   hi2c1;
UART_HandleTypeDef  huart1;
TIM_HandleTypeDef   htim2;
IWDG_HandleTypeDef  hiwdg;

/* ---------------------------------------------------------------------
 * large buffers, all static so none of them sits on the stack.  the stack is
 * left for the call chain into snprintf and the HAL.
 *   s_core     about 800 bytes  raw samples of the current window, status and the
 *                         lost-sensor state
 *   s_fft_z    512 bytes  Z axis in g for the FFT (fft.c holds its own work
 *                         buffers, about 2.5 KB, also static)
 *   s_line     161 bytes  the line being built (it is copied into the transmit
 *                         queue, 4 slots of 160 bytes in uart_output.c)
 * --------------------------------------------------------------------- */
static float       s_fft_z[FFT_SIZE];
static char        s_line[LINE_BUF_SIZE];

static ByteRing    s_rx_ring;
static PingParser  s_ping;
static NodeCore    s_core;      /* window, status word and the lost-sensor rule */
static Uptime      s_uptime;

static uint16_t    s_seq = 0U;      /* data lines sent since boot, wraps at 65536 */

/* use volatile here because sample_tick is written in the TIM2 interrupt
 * and read in the main loop - without volatile the compiler may cache the
 * read in a register and never see the interrupt's update. */
static volatile uint8_t sample_tick = 0U;

/* diagnostic counters, see main.h.  uint32_t loads and stores are atomic on
 * the Cortex-M4 so the main loop can read them without masking interrupts. */
volatile uint32_t g_missed_ticks   = 0U;
volatile uint32_t g_read_failures  = 0U;
volatile uint32_t g_bus_recoveries = 0U;
volatile uint32_t g_tx_skipped     = 0U;

/* the WHO_AM_I value of the last identity check, for a debugger or the bench.
 * 0x68 is the only value accepted as a genuine MPU6050.  0x00 means no check
 * has succeeded yet. */
volatile uint8_t  g_imu_id          = 0U;

/* check WHO_AM_I and the sleep bit once every this many windows (128 s) */
#define IDENTITY_CHECK_WINDOWS      100U

/* the watchdog is refreshed while ticks keep arriving.  a tick older than
 * this means TIM2 has stopped. */
#define TICK_STALE_MS               1000U

/* slow LED blink while the sensor is lost, 1 Hz */
#define LOST_BLINK_HALF_MS          500U

/* IWDG: 32 kHz / 64 = 500 Hz, reload 2000 -> 4.0 s nominal (see header) */
#define IWDG_PRESCALER_VALUE        IWDG_PRESCALER_64
#define IWDG_RELOAD_VALUE           2000U

static uint16_t s_windows_since_check = 0U;

/* ---------------------------------------------------------------------
 * forward declarations
 * --------------------------------------------------------------------- */
static void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_I2C1_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_TIM2_Init(void);
static void MX_IWDG_Init(void);
static void I2C_BusRecover(void);
static void I2C_Restart(void);
static bool Sensor_Start(void);
static void Sensor_Recover(void);
static void Sensor_CheckIdentity(void);
static void Sensor_CheckAwake(void);
static void Window_Complete(void);
static void Line_Emit(const WindowStats *stats, float fft_peak_hz, bool missing, bool no_data);
static void Comms_Service(void);

/* =====================================================================
 * timer period elapsed callback - runs at 100 Hz from the TIM2 interrupt
 * ===================================================================== */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance != TIM2) return;

    /* a flag still set means the main loop never consumed the previous tick.
     * count it so an overrun is visible instead of silently stretching the
     * window. */
    if (sample_tick)
    {
        g_missed_ticks++;
    }
    sample_tick = 1U;
}

/* =====================================================================
 * main
 * ===================================================================== */
int main(void)
{
    /* the reset flags in RCC->CSR are the only record of why the chip
     * restarted and they persist until cleared, so read them before anything
     * else runs and then clear them.  a stale flag would otherwise be
     * reported again after the next reset of a different kind. */
    uint32_t csr = RCC->CSR;
    __HAL_RCC_CLEAR_RESET_FLAGS();
    uint8_t boot_bits =
                Status_ResetBits((csr & RCC_CSR_IWDGRSTF) != 0U,
                                 (csr & RCC_CSR_WWDGRSTF) != 0U,
                                 (csr & RCC_CSR_BORRSTF)  != 0U,
                                 (csr & RCC_CSR_PORRSTF)  != 0U);

    /* HAL_Init must be the first HAL call - it configures the SysTick timer
     * for HAL_Delay and initialises the Flash prefetch and instruction cache. */
    HAL_Init();

    /* start the watchdog before the clock set-up, so a crystal that never
     * starts, a failed PLL or any fault in start-up ends in a reset about 4 s
     * later and not in a halt for ever.  start-up needs well under a second
     * (the crystal wait is capped at 100 ms, the I2C init stops at its first
     * failure) and the loop refreshes from its first pass.  the clock runs
     * from the HSI at this point and the IWDG from the LSI, so neither depends
     * on what comes next. */
    MX_IWDG_Init();

    SystemClock_Config();  /* 96 MHz from the 25 MHz crystal through the PLL */

    MX_GPIO_Init();
    MX_I2C1_Init();
    MX_USART1_UART_Init();
    MX_TIM2_Init();

    ByteRing_Init(&s_rx_ring);
    Ping_Init(&s_ping);
    UART_RxStart(&huart1, &s_rx_ring);

    /* the HAL tick starts at zero in HAL_Init, so uptime counts from there */
    Uptime_Init(&s_uptime, 0U);

    /* the status word must exist before the first identity check writes to it */
    Node_Init(&s_core, true, boot_bits, HAL_GetTick());

    /* configure the MPU6050 once.  a sensor that is unplugged or still
     * powering up is not a fault the firmware can fix and it must not stop
     * the node sending lines, so a failure here only makes the sensor count as lost.  the
     * loop below keeps retrying and reports the sensor as missing meanwhile. */
    bool init_ok = Sensor_Start();

    /* build the FFT tables now so the first window cannot overrun */
    FFT_Init();

    SensorState_Init(&s_core.sensor, init_ok, HAL_GetTick());
    sample_tick = 0U;

    /* start TIM2 in interrupt mode.  Use Base_Start_IT rather than
     * PWM or OC modes because only the period-elapsed interrupt is needed
     * to trigger sampling; no output compare or capture is required. */
    if (HAL_TIM_Base_Start_IT(&htim2) != HAL_OK)
    {
        Error_Handler();
    }

    /* give the loop a full timeout to start from */
    (void)HAL_IWDG_Refresh(&hiwdg);

    uint32_t missed_seen    = g_missed_ticks;
    uint32_t last_tick_ms   = HAL_GetTick();
    uint32_t last_blink_ms  = last_tick_ms;

    /* main loop.  avoid a WFI/sleep here because the STM32F411 wakes from
     * WFI on any interrupt including SysTick and managing re-entry correctly
     * adds complexity that is not needed at 100 Hz.  the loop spins between
     * ticks, which is what lets a ping be answered within a few
     * milliseconds. */
    while (1)
    {
        uint32_t now = HAL_GetTick();

        Comms_Service();

        /* slow blink while the sensor is lost.  done from the tick count so
         * it never blocks the loop. */
        if (s_core.sensor.lost && ((now - last_blink_ms) >= LOST_BLINK_HALF_MS))
        {
            last_blink_ms = now;
            LED_TOGGLE();
        }

        if (!sample_tick)
        {
            /* idle spin: refresh only while ticks are still being consumed */
            if ((now - last_tick_ms) < TICK_STALE_MS)
            {
                (void)HAL_IWDG_Refresh(&hiwdg);
            }
            continue;
        }
        sample_tick = 0U;  /* clear before the read so a tick arriving during it is kept */
        last_tick_ms = now;
        (void)HAL_IWDG_Refresh(&hiwdg);

        /* keep the second counter current well inside the 49 day tick wrap */
        (void)Uptime_Update(&s_uptime, now);

        uint32_t missed_now = g_missed_ticks;
        TickInput  in = {0};
        TickOutput out;
        in.now_ms       = now;
        in.missed_ticks = missed_now - missed_seen;
        missed_seen     = missed_now;

        /* read the raw counts (6 bytes) rather than all 14 to keep the I2C
         * bus time short.  an exactly all-zero triple counts as a failed
         * read, because a sensor that browns out keeps acknowledging and
         * returns zeros. */
        uint32_t t0 = HAL_GetTick();
        in.first_ok = (MPU6050_ReadAccelRaw(&hi2c1, in.first_raw) == HAL_OK) &&
                      !((in.first_raw[0] == 0) && (in.first_raw[1] == 0) && (in.first_raw[2] == 0));
        uint32_t first_ms = HAL_GetTick() - t0;

        /* a read that failed quickly got an answer from the bus, so try
         * once more within the same tick with a short timeout.  a timeout
         * is never retried: it already used up the tick. */
        if (SensorState_ShouldRetry(in.first_ok, first_ms))
        {
            in.retried   = true;
            in.second_ok = (MPU6050_ReadAccelRawTimeout(&hi2c1, in.second_raw, RETRY_TIMEOUT_MS) == HAL_OK) &&
                           !((in.second_raw[0] == 0) && (in.second_raw[1] == 0) && (in.second_raw[2] == 0));
        }

        Comms_Service();   /* a read on a hung bus can be slow, so answer any ping now */

        Node_Tick(&s_core, &in, &out);
        g_read_failures += out.failed_reads;

        if (out.recover)
        {
            Sensor_Recover();
            Comms_Service();
        }

        if (out.window_complete)
        {
            Window_Complete();
        }

        /* while the sensor is lost the window never fills, so a line with
         * zero readings and SENSOR_MISSING goes out once per window period.
         * when it is not lost but reads keep failing, so that no run of 128
         * good ones forms, the same happens with NO_DATA once two periods
         * have passed without a window.  the node is therefore never silent
         * for more than two periods.  a single discarded window sends no
         * line and the next complete one reports WINDOW_DROPPED. */
        ZeroLine zl = Node_ZeroLineDue(&s_core);
        if (zl != ZERO_LINE_NONE)
        {
            Line_Emit(NULL, 0.0f, zl == ZERO_LINE_MISSING, zl == ZERO_LINE_NO_DATA);
        }
    }
}

/* =====================================================================
 * receive side: pings
 * ===================================================================== */

/* drain the receive ring into the parser and answer each ping.  called from
 * the main loop, never from an interrupt and it never waits for input. */
static void Comms_Service(void)
{
    uint8_t  byte;
    uint16_t n;

    while (ByteRing_Pop(&s_rx_ring, &byte))
    {
        if (Ping_Feed(&s_ping, byte, &n))
        {
            char   pong[PONG_BUF_SIZE];
            size_t len = Line_BuildPong(pong, sizeof(pong), n);
            (void)UART_QueuePong(pong, len);     /* a pong does not move SEQ */
        }
    }

    UART_TxService(&huart1);
}

/* =====================================================================
 * window handling
 * ===================================================================== */

/* turn one full window into a telemetry line */
static void Window_Complete(void)
{
    WindowStats stats;
    float       peak_hz = 0.0f;

    if (!WinBuf_Compute(&s_core.win, &stats))
    {
        WinBuf_Clear(&s_core.win);   /* not full: cannot happen, but never send a guess */
        return;
    }

    /* once every IDENTITY_CHECK_WINDOWS windows confirm the part is still
     * the right one and still awake */
    s_windows_since_check++;
    if (s_windows_since_check >= IDENTITY_CHECK_WINDOWS)
    {
        s_windows_since_check = 0U;
        Sensor_CheckIdentity();
        Sensor_CheckAwake();
    }

    if (stats.stuck)
    {
        /* a part that went back to sleep after a glitch keeps returning its
         * last values, which looks exactly like this.  look at the sleep bit
         * now rather than wait for the periodic check.  a constant window has
         * no spectrum, so the peak is reported as 0 instead of an arbitrary
         * bin. */
        Sensor_CheckAwake();
    }
    else
    {
        WinBuf_ZToFloat(&s_core.win, s_fft_z);
        peak_hz = FFT_GetPeakFrequency(s_fft_z, FFT_SIZE, SAMPLE_RATE_HZ);
    }

    Line_Emit(&stats, peak_hz, false, false);

    /* heartbeat: one toggle per window, so the LED changes state every
     * 1.28 s while the node is sampling normally.  the slow blink owns the
     * LED while the sensor is lost. */
    if (!s_core.sensor.lost)
    {
        LED_TOGGLE();
    }
    WinBuf_Clear(&s_core.win);
}

/* build and send one data line.  stats is NULL for a line sent while the
 * sensor is lost, which carries zeros in every reading. */
static void Line_Emit(const WindowStats *stats, float fft_peak_hz, bool missing, bool no_data)
{
    /* the transmit queue has room for a line unless the transmitter has
     * stopped (two slots stay free of pongs, see tx_queue.h).  if it is full
     * the line is skipped and counted. */
    if (!UART_LineSpace())
    {
        g_tx_skipped++;
        SensorState_OnLineSent(&s_core.sensor);
        return;
    }

    LineFields f = {0};
    bool stuck    = false;
    bool clipping = false;

    if (stats != NULL)
    {
        f.vib_x = stats->mean_x;
        f.vib_y = stats->mean_y;
        f.vib_z = stats->mean_z;
        f.magnitude   = stats->magnitude;
        f.fft_peak_hz = fft_peak_hz;
        f.rms_x = stats->rms_x;
        f.rms_y = stats->rms_y;
        f.rms_z = stats->rms_z;
        f.peak  = stats->peak;
        stuck    = stats->stuck;
        clipping = stats->clipping;
    }

    f.status         = Status_Compose(&s_core.status, missing, stuck, clipping, no_data);
    f.seq            = s_seq;
    f.up_s           = Uptime_Update(&s_uptime, HAL_GetTick());
    f.missed_ticks   = g_missed_ticks;
    f.read_failures  = g_read_failures;
    f.bus_recoveries = g_bus_recoveries;

    size_t len = Line_Build(s_line, sizeof(s_line), &f);
    if (len > 0U)
    {
        (void)UART_QueueLine(s_line, len);
        s_seq++;    /* wraps at 65535 by the type */
    }

    /* the next line is due one window period after this one */
    SensorState_OnLineSent(&s_core.sensor);
}

/* =====================================================================
 * sensor start-up, identity and recovery
 * ===================================================================== */

/* one attempt at start-up.  the node carries on either way.  returns false
 * when the sensor did not answer, which makes it count as lost. */
static bool Sensor_Start(void)
{
    if (MPU6050_Init(&hi2c1) != HAL_OK)
    {
        return false;
    }
    Sensor_CheckIdentity();
    return true;
}

/* read WHO_AM_I and record whether it is the expected 0x68.  a failed read
 * leaves the last result alone, because a bus that does not answer is a
 * missing sensor, which has its own flag, not a wrong part. */
static void Sensor_CheckIdentity(void)
{
    uint8_t id;

    if (MPU6050_ReadWhoAmI(&hi2c1, &id) == HAL_OK)
    {
        g_imu_id = id;
        Status_SetIdMismatch(&s_core.status, !IMU_IdIsExpected(id));
    }
}

/* read PWR_MGMT_1 and configure the sensor again when it has gone back to
 * sleep.  a glitch on the supply can reset the part without the I2C bus
 * noticing. */
static void Sensor_CheckAwake(void)
{
    uint8_t pwr;

    if ((MPU6050_ReadPwrMgmt1(&hi2c1, &pwr) == HAL_OK) && IMU_IsAsleep(pwr))
    {
        (void)MPU6050_Init(&hi2c1);
    }
}

/* called after repeated read failures: free the bus and configure the sensor
 * again.  a reset can leave the MPU6050 asleep so it needs its registers
 * rewritten, not just a working bus.  a failed init is not fatal because
 * the main loop keeps counting failures and comes back here. */
static void Sensor_Recover(void)
{
    g_bus_recoveries++;
    I2C_Restart();
    if (MPU6050_Init(&hi2c1) == HAL_OK)
    {
        Sensor_CheckIdentity();
    }
}

/* =====================================================================
 * peripheral init
 * ===================================================================== */

/**
 * SystemClock_Config: set the PLL for a 96 MHz system clock.
 *
 * clock tree:
 *   HSE 25 MHz / M(25) = 1 MHz VCO input
 *   x N(192)           = 192 MHz VCO
 *   / P(2)             = 96 MHz SYSCLK
 *   / Q(4)             = 48 MHz for USB (unused here but kept valid)
 *   AHB  /1 = 96 MHz
 *   APB1 /2 = 48 MHz (PCLK1, limit 50 MHz)
 *   APB2 /1 = 96 MHz (PCLK2, limit 100 MHz)
 * use 96 MHz rather than the maximum 100 MHz because it is the highest
 * speed that still divides to a 48 MHz USB clock and gives whole-number
 * TIM2 prescaler values for exactly 100 Hz.  APB1 cannot run undivided at
 * 96 MHz because it is limited to 50 MHz.
 *
 * voltage scale 1 and 3 flash wait states are what the datasheet requires
 * for 90 to 100 MHz at 2.7 to 3.6 V.
 */
static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};

    /* the voltage scale must be raised before the clock is, because the
     * core needs the higher supply to run at 96 MHz. */
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    osc.HSEState       = RCC_HSE_ON;
    osc.PLL.PLLState   = RCC_PLL_ON;
    osc.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    osc.PLL.PLLM       = 25U;
    osc.PLL.PLLN       = 192U;
    osc.PLL.PLLP       = RCC_PLLP_DIV2;
    osc.PLL.PLLQ       = 4U;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK)
    {
        Error_Handler();
    }

    clk.ClockType      = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                         RCC_CLOCKTYPE_PCLK1  | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider  = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV2;
    clk.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_3) != HAL_OK)
    {
        Error_Handler();
    }
}

/**
 * MX_GPIO_Init: enable the port clocks and set up the LED on PC13.
 * the I2C and UART pins are configured in stm32f4xx_hal_msp.c when their
 * peripherals start.  PA0 is left untouched on purpose (see main.h).
 */
static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();

    /* drive the pin high before making it an output so the LED (active low)
     * does not flash at start-up. */
    LED_OFF();

    gpio.Pin   = LED_Pin;
    gpio.Mode  = GPIO_MODE_OUTPUT_PP;
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GPIO_Port, &gpio);
}

/**
 * I2C_DelayUs: crude busy-wait delay of roughly the given microseconds.
 * a loop is used rather than HAL_Delay because HAL_Delay only has 1 ms
 * resolution and the bus recovery clock needs about 5 us per half period.
 * the result is approximate and only ever errs towards a slower clock.
 */
static void I2C_DelayUs(uint32_t us)
{
    volatile uint32_t n = us * (SystemCoreClock / 5000000U);
    while (n--) { }
}

/**
 * I2C_BusRecover: free an I2C bus held low by a sensor stuck mid-byte.
 *
 * if the MCU resets in the middle of a transfer the MPU6050 can keep
 * driving SDA low while it waits for clocks that will never come.  the
 * bus then stays dead until power is removed.  the standard fix is to pulse SCL
 * until the slave lets go of SDA (at most nine times, one per bit of a byte
 * plus the acknowledge) and then make a STOP condition.
 *
 * both pins are driven as open-drain GPIO for this, which relies on the
 * board's pull-ups for the high level.  the pins go back to I2C1 when
 * HAL_I2C_Init runs HAL_I2C_MspInit.
 */
static void I2C_BusRecover(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();

    /* write the pins high before making them outputs.  HAL_GPIO_Init leaves
     * the output register as it finds it (low after reset), which would pull
     * both lines low for an instant on the first call. */
    HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SCL_Pin | I2C_SDA_Pin, GPIO_PIN_SET);

    gpio.Pin   = I2C_SCL_Pin | I2C_SDA_Pin;
    gpio.Mode  = GPIO_MODE_OUTPUT_OD;
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(I2C_GPIO_Port, &gpio);

    /* let the released lines settle */
    I2C_DelayUs(10U);

    for (uint8_t i = 0U; i < 9U; i++)
    {
        if (HAL_GPIO_ReadPin(I2C_GPIO_Port, I2C_SDA_Pin) == GPIO_PIN_SET)
        {
            break;  /* slave has released SDA */
        }

        HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SCL_Pin, GPIO_PIN_RESET);
        I2C_DelayUs(5U);
        HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SCL_Pin, GPIO_PIN_SET);
        I2C_DelayUs(5U);
    }

    /* STOP condition: SDA rises while SCL is high.  pull SDA low first with
     * SCL low so the sequence cannot be read as a START. */
    HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SCL_Pin, GPIO_PIN_RESET);
    I2C_DelayUs(5U);
    HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SDA_Pin, GPIO_PIN_RESET);
    I2C_DelayUs(5U);
    HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SCL_Pin, GPIO_PIN_SET);
    I2C_DelayUs(5U);
    HAL_GPIO_WritePin(I2C_GPIO_Port, I2C_SDA_Pin, GPIO_PIN_SET);
    I2C_DelayUs(5U);
}

/**
 * MX_I2C1_Init: set up I2C1 at 100 kHz on PB6 (SCL) and PB7 (SDA).
 * use 100 kHz (standard mode) rather than 400 kHz because the sensor sits
 * on a cable: its capacitance slows the edges and a 400 kHz bus would
 * misread.  a 6-byte accel read still takes under 1 ms, well inside the
 * 10 ms sample period.
 */
static void MX_I2C1_Init(void)
{
    /* free the bus first so HAL_I2C_Init does not start against a line that
     * a sensor from the previous run is still holding low. */
    I2C_BusRecover();

    hi2c1.Instance             = I2C1;
    hi2c1.Init.ClockSpeed      = 100000U;
    hi2c1.Init.DutyCycle       = I2C_DUTYCYCLE_2;
    hi2c1.Init.OwnAddress1     = 0U;
    hi2c1.Init.AddressingMode  = I2C_ADDRESSINGMODE_7BIT;
    hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
    hi2c1.Init.OwnAddress2     = 0U;
    hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
    hi2c1.Init.NoStretchMode   = I2C_NOSTRETCH_DISABLE;
    if (HAL_I2C_Init(&hi2c1) != HAL_OK)
    {
        Error_Handler();
    }
}

/**
 * I2C_Restart: reset the I2C1 peripheral and recover the bus.
 * DeInit force-resets the peripheral (see HAL_I2C_MspDeInit) so a stuck BUSY
 * flag is cleared, then MX_I2C1_Init recovers the bus and starts it again.
 */
static void I2C_Restart(void)
{
    (void)HAL_I2C_DeInit(&hi2c1);
    MX_I2C1_Init();
}

/**
 * MX_USART1_UART_Init: set up USART1 at 115200 baud on PA9 (TX) and PA10 (RX).
 * use 115200 rather than 9600 so a telemetry line of up to 160 bytes
 * transmits in about 14 ms rather than about 170 ms, keeping the main loop
 * responsive.  receive is started separately (UART_RxStart) once the
 * ring buffer exists.
 */
static void MX_USART1_UART_Init(void)
{
    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 115200U;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK)
    {
        Error_Handler();
    }
}

/**
 * MX_TIM2_Init: set up TIM2 for a 100 Hz period elapsed interrupt.
 *
 * TIM2 sits on APB1.  PCLK1 is 48 MHz because the APB1 prescaler is 2, but
 * when an APB prescaler is not 1 the timer clock is doubled, so TIM2 still
 * runs at 2 x 48 MHz = 96 MHz:
 *   prescaler (PSC) = 9600 - 1  -> timer clock = 96 MHz / 9600 = 10 000 Hz
 *   Auto-reload (ARR) = 100 - 1 -> period = 10 000 / 100 = 100 Hz
 *
 * subtract 1 from both because TIM2 counts from 0 to ARR inclusive (ARR+1
 * ticks per period) and from 0 to PSC inclusive (PSC+1 source clocks per
 * timer clock tick).
 */
static void MX_TIM2_Init(void)
{
    htim2.Instance               = TIM2;
    htim2.Init.Prescaler         = 9600U - 1U;
    htim2.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim2.Init.Period            = 100U - 1U;
    htim2.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
    {
        Error_Handler();
    }
}

/**
 * MX_IWDG_Init: start the independent watchdog, about 4 s (see the header
 * comment for the timing and the margin).  called right after HAL_Init.  once started it cannot be stopped
 * short of a reset.
 */
static void MX_IWDG_Init(void)
{
    hiwdg.Instance       = IWDG;
    hiwdg.Init.Prescaler = IWDG_PRESCALER_VALUE;
    hiwdg.Init.Reload    = IWDG_RELOAD_VALUE;
    if (HAL_IWDG_Init(&hiwdg) != HAL_OK)
    {
        Error_Handler();
    }

#if defined(DEBUG) || defined(__PLATFORMIO_BUILD_DEBUG__)
    /* the IWDG keeps counting while a debugger halts the core, which would
     * reset the chip at every breakpoint.  this stops it counting during a
     * halt.  debug builds only, so a release build is never exposed. */
    __HAL_DBGMCU_FREEZE_IWDG();
#endif
}

/**
 * Error_Handler: signal an unrecoverable fault with a very fast LED blink.
 * interrupts are disabled so nothing can pull the firmware out of the
 * blink.  the delay is a busy loop because SysTick no longer runs.
 * the GPIO is set up here again so the blink works even when the fault
 * happens before MX_GPIO_Init.  it halts rather than resets itself because
 * a reset loop could cause repeated I2C bus lockup if the sensor is absent.
 * the watchdog is running from just after HAL_Init, so a fault is not
 * permanent: nothing refreshes the watchdog here, so the chip resets about
 * 4 s later, I2C_BusRecover runs again at boot and the next line carries
 * RESET_WATCHDOG.  a crystal that does not start ends here too and repeats
 * every 4 s and the hub sees a silent link, which is the truth.
 */
void Error_Handler(void)
{
    GPIO_InitTypeDef gpio = {0};

    __disable_irq();

    __HAL_RCC_GPIOC_CLK_ENABLE();
    gpio.Pin   = LED_Pin;
    gpio.Mode  = GPIO_MODE_OUTPUT_PP;
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GPIO_Port, &gpio);

    while (1)
    {
        LED_TOGGLE();

        /* about 50 ms per state, so roughly 10 Hz, at about 11 cycles per
         * volatile loop iteration.  the figure is approximate and runs slower
         * if the fault happens before the PLL is up (16 MHz clock). */
        for (volatile uint32_t i = 0U; i < (SystemCoreClock / 220U); i++) { }
    }
}
