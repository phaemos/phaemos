// esp32.ino - PHAEMOS v2 main firmware for the ESP32 hub node.
// this file is the wiring. the decisions (the order of setup(), the restore after a warm reset,
// the board check, the judgement of the three alarms and the panel) live in outputs/hub_core.cpp
// behind the HubPlatform interface, so the host can replay whole scenarios through them. what stays
// here is the sensor probing and the library set-up calls, the serial parsing, the post hand-over
// and the pin writes.
//
// two tasks run. this one (the Arduino loop, core 1) reads, judges, drives the display, the
// relays and the buzzer on a fixed timer and never waits on the network. the post task
// (comms/post_task.cpp, core 0) connects Wi-Fi, checks for updates and posts the newest body.

// ─── Arduino / ESP32 core ────────────────────────────────────────────────────
#include <Arduino.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <nvs.h>
#include <driver/gpio.h>
#include <esp_attr.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>

// ─── Project configuration ───────────────────────────────────────────────────
#include "config.h"

// ─── Sensor modules ──────────────────────────────────────────────────────────
#include "sensors/bme280.h"
#include "sensors/mpu6050.h"
#include "sensors/ina219.h"
#include "sensors/vl53l0x.h"
#include "sensors/mq2.h"
#include "sensors/fc28.h"
#include "sensors/ds18b20.h"
#include "sensors/ldr.h"
#include "sensors/mlx90614.h"
#include "sensors/as5600.h"
#include "sensors/i2c_probe.h"
#include "sensors/health.h"
#include "sensors/fitted.h"
#include "sensors/analog_checks.h"
#include "sensors/content_checks.h"
#include "sensors/stuck_check.h"
#include "sensors/input_voltage.h"
#include "sensors/sensor_rail.h"
#include "sensors/board_check.h"
#include "sensors/mcp23017.h"

// ─── Output modules ──────────────────────────────────────────────────────────
#include "outputs/oled.h"
#include "outputs/buzzer.h"
#include "outputs/rgb_led.h"
#include "outputs/relay.h"
#include "outputs/status_led.h"
#include "outputs/status_logic.h"
#include "outputs/saved_state.h"
#include "outputs/temp_judge.h"
#include "outputs/hub_core.h"

// ─── Comms modules ───────────────────────────────────────────────────────────
#include "comms/post_task.h"
#include "comms/post_queue.h"
#include "comms/serial_parser.h"
#include "comms/telemetry_body.h"
#include "comms/credentials.h"
#include "comms/post_rules.h"

// the saved-state code reads the reset reason as a number. keep it tied to the real enum.
static_assert(ESP_RST_SW == 3 && ESP_RST_PANIC == 4 && ESP_RST_INT_WDT == 5 &&
              ESP_RST_TASK_WDT == 6 && ESP_RST_WDT == 7,
              "saved_state.cpp assumes these esp_reset_reason() values");

// ─── Hardware serial ports ───────────────────────────────────────────────────
// use HardwareSerial(1) for the Nano because UART1 does not conflict with
// the USB debug port (UART0) or the STM32 (UART2).
HardwareSerial NanoSerial(1);
// use HardwareSerial(2) for the STM32 for the same isolation reason.
HardwareSerial STM32Serial(2);

// ─── Global sensor reading structs ───────────────────────────────────────────
// a reading that is absent is held as NAN so the display shows dashes.
BME280Reading  bmeData;
MPU6050Reading mpuData;
INA219Reading  inaData;

// one recovery record per I2C sensor. it says whether the sensor has been set up since it
// was last lost, so any lost probe leads to a new set-up and not only three in a row.
static Recovery bmeRec, mpuRec, inaRec, vlRec, mlxRec, asRec;
// the DS18B20 is searched for again on every pass while it is missing, which only costs a
// short 1-wire scan. the search is protected like every other set-up.
static bool dsOk = false;
static float dsPrevious = 0.0f;
static bool  dsHavePrevious = false;
// the BME280 raw data words, for the stuck test
static StuckDetector bmeStuck;
static uint32_t dsLastSearchMs = 0;

// xxxValid says whether the latest reading can be trusted.
bool bmeValid = false, mpuValid = false, inaValid = false, vlValid = false;
bool dsValid  = false, mlxValid = false, asValid  = false;

uint16_t distMm       = 0;
float    gasLevel     = 0.0f;
bool     gasAlert     = false;
int      gasRaw       = 0;
bool     gasLow       = false;
float    moistureLevel = 0.0f;
bool     waterAlert   = false;
float    ds18bTemp    = 0.0f;
float    ldrLevel     = 0.0f;
float    micLevel     = 0.0f;
float    mlxObject    = 0.0f;
float    as5600Angle  = 0.0f;
float    as5600Rpm    = 0.0f;

// ─── Serial links ────────────────────────────────────────────────────────────
static LinkCore nanoLink;
static LinkCore stm32Link;

// ─── Fault reporting state ───────────────────────────────────────────────────
static uint32_t bootCount   = 0;
// the boot counter was read and raised and read back. without it no body is built
static bool     identOk     = false;
// the stored credentials, read once at boot. the post task keeps a pointer to them
static Credentials g_creds;
// the provisioning console: one line at a time, never echoed
static ProvFields g_prov;
static ProvConsole g_console;
static uint32_t   g_buttonLowSinceMs = 0;
// counts every body built, including one that is replaced before it is sent, so the backend
// sees a gap where readings were lost.
static uint32_t postSeq     = 0;
static uint32_t bodyTooBig  = 0;
// the lowest free loop stack seen, in bytes. nothing else measures it.
static uint32_t loopStackFree = 8192;
static uint32_t lastLinkPoll = 0;
static float     inputVolts   = 0.0f;
static float     micMean      = 0.0f;
static uint8_t   moistLowPasses = 0;
// a BME280 reading above its range from a part that passed its register checks
static bool      bmeOverRange  = false;
// a sensor whose set-up must be skipped on this boot
static bool      skipOnce[SETUP_COUNT];
// when each sensor's set-up last completed and it has given good readings since (0 when not
// tracking), so a strike can be forgiven
static uint32_t  goodSinceMs[SETUP_COUNT];
static bool      goodTracking[SETUP_COUNT];

// ─── Warm reset state ────────────────────────────────────────────────────────
// RTC memory that a watchdog, panic or software reset does not clear. the core trusts it only
// after such a reset and only when the magic word, the layout version and the checksum are right.
RTC_NOINIT_ATTR static SavedState rtcSaved;
static HubCore core;

// ─── Timing state ────────────────────────────────────────────────────────────
// the reading timer is fixed. it moves on by whole intervals, so nothing that happens in a pass
// can push the next one back.
static uint32_t nextReadingMs = 0;
static uint32_t lastOLED      = 0;
static uint32_t lastAS5600    = 0;
static uint32_t lastDiagLog   = 0;

// ─── Status state ────────────────────────────────────────────────────────────
static LEDStatus currentStatus = STATUS_NORMAL;
static char      statusText[32] = "NORMAL";
// the sound follows the highest level, which does not alternate
static StatusKind soundBase    = STK_NORMAL;
static uint32_t  lastAlertMs   = 0;
static bool      alertPending  = false;
// the last outputs the core produced, for the body and the display
static HubStepOut lastOut;

// ─── Forward declarations ────────────────────────────────────────────────────
void serviceAlerts(uint32_t now);
void buildAndSubmitBody();
HubStepIn readAllSensors();
void applyOutputs(const HubStepOut& out);
void initCableSensors();
void recoverSensorRail();

// ============================================================
// node information helpers
// ============================================================

// the boot counter lives in non-volatile storage. the sketch asks the storage library directly
// (nvs_get_u32), because Preferences::getUInt returns the default 0 for a read error as well as for a
// counter that was never written, which would restart the counter at 1 on a storage fault. the
// backend refuses any pair that is not newer, so a hub back at boot 1 would be refused for ever until an
// admin accepts a new counter. the decisions are in bootAdvance (comms/post_rules.cpp, host tested).
class NvsBootStore : public BootStore {
public:
    NvsBootStore() { open_ = nvs_open("phaemos", NVS_READWRITE, &h_) == ESP_OK; }
    ~NvsBootStore() override { if (open_) nvs_close(h_); }
    NvsRead read(uint32_t* v) override {
        if (!open_) return NVSR_ERROR;
        esp_err_t e = nvs_get_u32(h_, "boot", v);
        if (e == ESP_OK) return NVSR_OK;
        return e == ESP_ERR_NVS_NOT_FOUND ? NVSR_NOT_FOUND : NVSR_ERROR;
    }
    bool write(uint32_t v) override {
        return open_ && nvs_set_u32(h_, "boot", v) == ESP_OK && nvs_commit(h_) == ESP_OK;
    }
    bool credsStored() override { return credsStoredInFlash(); }
private:
    nvs_handle_t h_ = 0;
    bool         open_ = false;
};

// nextBootCount raises the boot counter once per boot. any failure means the hub builds no bodies
// at all and sends no guessed boot. alarms, relays, panel and display do not depend on it.
static bool nextBootCount(uint32_t* out) {
    NvsBootStore store;
    BootResult r = bootAdvance(store, out);
    if (r != BOOT_OK) {
        Serial.print(F("Boot counter: "));
        Serial.print(bootResultName(r));
        Serial.println(F(". no telemetry will be sent"));
        return false;
    }
    return true;
}

// resetReasonName gives a short word for the reset reason.
static const char* resetReasonName(esp_reset_reason_t why) {
    switch (why) {
        case ESP_RST_POWERON:   return "poweron";
        case ESP_RST_EXT:       return "ext";
        case ESP_RST_SW:        return "sw";
        case ESP_RST_PANIC:     return "panic";
        case ESP_RST_INT_WDT:   return "int_wdt";
        case ESP_RST_TASK_WDT:  return "task_wdt";
        case ESP_RST_WDT:       return "wdt";
        case ESP_RST_DEEPSLEEP: return "deepsleep";
        case ESP_RST_BROWNOUT:  return "brownout";
        case ESP_RST_SDIO:      return "sdio";
        default:                return "unknown";
    }
}

// setHealth updates the table and logs only when the state changes. a sensor that is not fitted
// never has a state.
static void setHealth(SensorKey key, HealthState state) {
    if (!sensorFitted(key)) return;
    if (!healthSet(key, state, millis())) return;
    Serial.print(F("[health] "));
    Serial.print(healthKeyName(key));
    Serial.print(F(" is "));
    Serial.println(healthStateName(state));
}

// feedWatchdog feeds the loop's watchdog. it is harmless before the loop is subscribed.
static void feedWatchdog() {
    esp_task_wdt_reset();
}

// the sensor key that goes with each set-up id
static SensorKey keyForSetup(SetupId id) {
    switch (id) {
        case SETUP_BME280:  return SK_BME280;
        case SETUP_MPU6050: return SK_MPU6050;
        case SETUP_INA219:  return SK_INA219;
        case SETUP_VL53L0X: return SK_VL53L0X;
        case SETUP_MLX90614:return SK_MLX90614;
        case SETUP_AS5600:  return SK_AS5600;
        default:            return SK_DS18B20;
    }
}

// guardedInit runs one sensor's set-up with a marker in RTC memory naming it. a pinned library
// can wait in a loop that never ends once its part stops answering, which ends in a task watchdog
// reset. the next boot finds the marker, gives that sensor a strike and skips it. after
// SETUP_MAX_STRIKES it stays out until power-up. a strike is forgiven after the sensor has completed
// a set-up and given good readings for SETUP_FORGIVE_MS. every set-up goes through here, the
// DS18B20 search included. the MQ-2 and the display set-up call only bounded code.
static bool guardedInit(SetupId id, bool (*fn)(), bool* excluded) {
    *excluded = false;
    if (ssSetupExcluded(&rtcSaved, id)) {
        *excluded = true;
        return false;
    }
    ssSetupBegin(&rtcSaved, id);
    bool ok = fn();
    ssSetupEnd(&rtcSaved);
    goodTracking[id] = false;      // forgiveness is counted from the first good reading after this
    return ok;
}

// reportSkipped names why a sensor was not set up, in words and marks it missing
static void reportSkipped(SetupId id, bool excluded) {
    setHealth(keyForSetup(id), HS_MISSING);
    Serial.print(F("[setup] "));
    Serial.print(healthKeyName(keyForSetup(id)));
    Serial.println(excluded
        ? F(" is left out until power-up: its set-up ended in a reset twice. a power cycle brings it back")
        : F(" is skipped on this boot: its set-up was running when the hub reset"));
}

// noteSensorGood tracks a sensor that has completed a set-up and is giving good readings. once it
// has done so for SETUP_FORGIVE_MS its strikes are forgiven.
static void noteSensorGood(SetupId id, bool good, uint32_t now) {
    if (!good) {
        goodTracking[id] = false;
        return;
    }
    if (!goodTracking[id]) {
        goodTracking[id] = true;
        goodSinceMs[id] = now;
        return;
    }
    if (ssStrikeForgiveDue(goodSinceMs[id], now, SETUP_FORGIVE_MS) && ssForgive(&rtcSaved, id)) {
        Serial.print(F("[setup] "));
        Serial.print(healthKeyName(keyForSetup(id)));
        Serial.println(F(" has given good readings for a while, so its earlier strike is forgiven"));
    }
}

// setUpOne runs one sensor's set-up at boot, honouring the skip and the strikes.
static bool setUpOne(SetupId id, bool (*fn)(), Recovery* rec, uint32_t now) {
    bool excluded = false;
    bool ok = false;
    if (skipOnce[id]) {
        skipOnce[id] = false;
        reportSkipped(id, false);
    } else {
        ok = guardedInit(id, fn, &excluded);
        if (excluded) reportSkipped(id, true);
    }
    if (rec) recoveryNoteTry(rec, ok, now);
    feedWatchdog();
    return ok;
}

// initCableSensors sets up every I2C and 1-wire sensor that is fitted. the same call runs after a
// power cycle of the sensor rail. calling an init again is safe as long as the part answers: the
// Adafruit begin calls delete the old bus object first, the INA219 reuses its own and the
// DS18B20 and AS5600 inits only rescan and reset their counters. two pinned libraries
// (the MPU6050 reset and the BME280 calibration wait) can loop for ever if the part stops
// answering part way through. the BME280 and MPU6050 wrappers check the part with their own
// bounded reads first. the marker in RTC memory and the watchdog cover what is left.
void initCableSensors() {
    uint32_t now = millis();
    if (HAS_BME280)   { setUpOne(SETUP_BME280,   initBME280,   &bmeRec, now); stuckReset(&bmeStuck); }
    if (HAS_MPU6050)  setUpOne(SETUP_MPU6050,  initMPU6050,  &mpuRec, now);
    if (HAS_INA219)   setUpOne(SETUP_INA219,   initINA219,   &inaRec, now);
    if (HAS_VL53L0X)  setUpOne(SETUP_VL53L0X,  initVL53L0X,  &vlRec,  now);
    if (HAS_DS18B20)  dsOk = setUpOne(SETUP_DS18B20, []() { return initDS18B20(); }, nullptr, now);
    dsHavePrevious = false;
    if (HAS_MLX90614) setUpOne(SETUP_MLX90614, initMLX90614, &mlxRec, now);
    if (HAS_AS5600)   setUpOne(SETUP_AS5600,   initAS5600,   &asRec,  now);
}

// recoverSensorRail power-cycles the cable sensor rail and sets every sensor up again.
// nothing calls it yet. this firmware has no I2C bus recovery path to hang it on, so it
// waits for the step that adds one. it refuses to run unless the board check agrees that this is
// the revised board, because on the present board GPIO14 is a relay and driving it high would
// switch it on. the display is set up again afterwards in case it sits on the switched rail.
void recoverSensorRail() {
#if HAS_SENSOR_RAIL_SWITCH
    if (!maySwitchSensorRail(HAS_SENSOR_RAIL_SWITCH != 0, core.board())) {
        Serial.println(F("Sensor rail cycle refused: the board check does not say this is the revised board"));
        return;
    }
    Serial.println(F("Power-cycling the sensor rail"));
    feedWatchdog();
    sensorRailPowerCycle();
    // the cycle takes longer than a normal pass is allowed to hold the loop.
    feedWatchdog();
    initCableSensors();
    initOLED();
    Wire.setClock(I2C_FREQ_HZ);
    feedWatchdog();
#endif
}

// ============================================================
// provisioning over the serial console
// ============================================================

// restart after a short pause so the reply can leave the serial buffer
static void restartSoon() {
    Serial.flush();
    delay(300);
    ESP.restart();
}

// provisionPoll reads the console one byte at a time and handles a line when it ends. it never
// echoes what it reads and never prints a line it was given, so the key and the password do not
// come back out. the main loop calls it on every pass and it never waits.
static void provisionPoll() {
    // bytes that an earlier pass read and did not use. at most PROV_BYTES_PER_PASS are taken per pass
    // and one line handled, so a flood of lines never holds the loop and never costs a blocking
    // reply for every line
    static uint8_t carry[PROV_BYTES_PER_PASS];
    static size_t carryLen = 0;
    if (carryLen == 0) {
        int avail = Serial.available();
        if (avail <= 0) return;
        carryLen = Serial.readBytes(carry, avail > (int)sizeof carry ? sizeof carry : (size_t)avail);
        if (carryLen == 0) return;
    }
    char reply[128];
    ProvResult r = PR_OK;
    bool hasReply = false;
    size_t used = provConsoleFeed(&g_console, &g_prov, ALLOW_PLAIN_HTTP != 0, carry, carryLen, millis(),
                                  reply, sizeof reply, &r, &hasReply);
    memmove(carry, carry + used, carryLen - used);
    carryLen -= used;
    if (hasReply) Serial.println(reply);
    if (r == PR_SAVE) {
        if (credsSave(&g_prov)) {
            provWipe(&g_prov);
            restartSoon();
        } else {
            Serial.println(F("ERR the credentials could not be stored (this build may use compiled secrets)"));
        }
    } else if (r == PR_CLEAR) {
        credsClear();
        provWipe(&g_prov);
        restartSoon();
    }
}

// provisionButtonPoll clears the stored credentials when the button is held low for
// PROVISION_CLEAR_HOLD_MS during the first PROVISION_CLEAR_WINDOW_MS after boot.
static void provisionButtonPoll(uint32_t now) {
    // once the window has closed it stays closed. millis() wraps after 49.7 days and a plain
    // comparison would open the window again for another 30 seconds
    static bool windowClosed = false;
    if (windowClosed) return;
    if (now > PROVISION_CLEAR_WINDOW_MS) {
        windowClosed = true;
        return;
    }
    if (digitalRead(PROVISION_CLEAR_PIN) != LOW) {
        g_buttonLowSinceMs = 0;
        return;
    }
    if (g_buttonLowSinceMs == 0) g_buttonLowSinceMs = now ? now : 1;
    if ((uint32_t)(now - g_buttonLowSinceMs) >= PROVISION_CLEAR_HOLD_MS) {
        Serial.println(F("Button held: clearing the stored credentials and restarting"));
        credsClear();
        restartSoon();
    }
}

#if HAS_EXPANDER
// expanderButtonPoll takes the revised board's push button events from the expander driver. a short
// press is only logged, because nothing in the firmware asks for a button press. a long press
// (BUTTON_LONG_PRESS_MS, the same hold as the BOOT button) clears the stored credentials in the first
// PROVISION_CLEAR_WINDOW_MS after a power-up and never otherwise. a warm reset (a brown-out or a
// watchdog) does not open the window, because a node reset next to a pressed button must not clear
// its credentials. the BOOT button's window above counts from every reset. an expander that is down
// gives no events, so it can never clear anything.
static void expanderButtonPoll(uint32_t now) {
    static bool windowClosed = false;
    static const bool coldPowerUp = (esp_reset_reason() == ESP_RST_POWERON);
    bool allowed = mcp::buttonClearAllowed(coldPowerUp, now, &windowClosed);
    if (expanderTakePress()) Serial.println(F("[button] pressed"));
    if (expanderTakeLongPress()) {
        if (!allowed) {
            Serial.println(F("[button] long press ignored: credentials are cleared only in the first 30 seconds after a power-up and not after a reset"));
        } else {
            Serial.println(F("[button] long press: clearing the stored credentials and restarting"));
            credsClear();
            restartSoon();
        }
    }
}
#endif

// ============================================================
// the platform: the hub core's view of the hardware
// ============================================================
class EspPlatform : public HubPlatform {
public:
    void relayInitPins() override { initRelay(); }

    // arm the watchdog straight away with a short setup timeout and feed it between stages, so a
    // library call that never returns during sensor set-up ends in a reset and not a hang. it is
    // armed right after the relay pins are set low, before anything that can wait. setup() does
    // not wait for Wi-Fi or OTA. the timeout drops to the run value at the end of setup().
    void armWatchdog() override {
        esp_task_wdt_init(WDT_SETUP_TIMEOUT_S, true);
        esp_task_wdt_add(NULL);
    }

    void relaySet(uint8_t ch, bool on) override { triggerRelay((RelayChannel)ch, on); }

    // GPIO14 is released as a plain input on both images. nothing drives it until the board check says so
    void gpio14Release() override { sensorRailInit(); }
    void gpio14DriveRelayLow() override { relayAllowGpio14(true); }

    void delayMs(uint32_t ms) override {
        while (ms > 0) {
            uint32_t step = ms > 100 ? 100 : ms;
            delay(step);
            feedWatchdog();
            ms -= step;
        }
    }

    void i2cBegin() override { Wire.begin(I2C_SDA, I2C_SCL, I2C_FREQ_HZ); }

    // both lines of an idle I2C bus read high. a line held low means a part is holding the bus
    bool i2cLinesIdle() override {
        pinMode(I2C_SDA, INPUT_PULLUP);
        pinMode(I2C_SCL, INPUT_PULLUP);
        bool idle = digitalRead(I2C_SDA) == HIGH && digitalRead(I2C_SCL) == HIGH;
        Wire.begin(I2C_SDA, I2C_SCL, I2C_FREQ_HZ);   // hand the pins back to the bus
        return idle;
    }

    bool i2cProbe(uint8_t addr) override { return i2cPresent(addr); }

    // the panel, the display and the buzzer come up before any sensor set-up and the post task starts
    // before it too. the panel shows a fault and the display says STARTING until the first judgement
    void outputsInit() override {
        initStatusLeds();
        initBuzzer();
        initRGBLed();
        initOLED();
        setPanelStatus(STATUS_FAULT);
        setLEDStatus(STATUS_FAULT);
        currentStatus = STATUS_FAULT;
        snprintf(statusText, sizeof statusText, "STARTING");
        displayStatusOnly(statusText);
        feedWatchdog();
    }

    void startPostTask() override { postTaskStart(&g_creds); }

    void initSensors(const BootInfo& info) override {
        // say what the boot found, in words
        if (info.board != BOARD_OK) {
            Serial.println(info.board == BOARD_UNKNOWN
                ? F("BOARD UNKNOWN: the bus could not prove which board this is. GPIO14 is not driven.")
                : F("BOARD MISMATCH: the image and the board disagree about the MCP23017. GPIO14 is not driven."));
        }
        if (info.verdict == RV_REFUSE) {
            Serial.println(F("Reset loop: warm resets without a trusted temperature reading, so nothing is restored and the cooling relay takes its no-information state"));
        }
#if HAS_FC28
        if (!WATER_ALARM_PROVEN) {
            Serial.println(F("WATER ALARM UNPROVEN: WATER_THRESHOLD is worked out and not measured on a real probe"));
        }
#endif
#if HAS_MQ2
        if (!GAS_ALARM_PROVEN) {
            Serial.println(F("GAS ALARM ANALOGUE PATH UNPROVEN: GAS_ANALOGUE_ALARM_COUNTS and the clean-air band are not measured"));
        }
#endif
        for (uint8_t i = 0; i < SETUP_COUNT; i++) skipOnce[i] = info.setup.skipThisBoot[i];
#if HAS_INPUT_MONITOR
        initInputVoltage();
#endif
        // start both secondary serial ports. a link that is not fitted is never started. the receive
        // buffers are set before begin() and hold several lines, because the core's default of 256
        // bytes is two Black Pill lines.
        if (HAS_NANO) {
            NanoSerial.setRxBufferSize(UART_RX_BUFFER_BYTES);
            NanoSerial.begin(NANO_BAUD, SERIAL_8N1, NANO_RX_PIN, NANO_TX_PIN);
        }
        if (HAS_STM32) {
            STM32Serial.setRxBufferSize(UART_RX_BUFFER_BYTES);
            STM32Serial.begin(STM32_BAUD, SERIAL_8N1, STM32_RX_PIN, STM32_TX_PIN);
        }
        if (HAS_INPUT_PULLDOWNS) {
            // the serial driver switches the internal pull-up on for a receive pin (uart_set_pin
            // in ESP-IDF 4.4 calls gpio_set_pull_mode with pull-up only). the revised board has
            // 100 kohm pull-downs so that an unplugged cable reads low. a pull-up would defeat them.
            // gpio_pullup_dis leaves the pin attached to the port, which pinMode might not.
            if (HAS_NANO)  gpio_pullup_dis((gpio_num_t)NANO_RX_PIN);
            if (HAS_STM32) gpio_pullup_dis((gpio_num_t)STM32_RX_PIN);
        }

#if HAS_EXPANDER
        // the expander starts only when the board check found it. a failed start is reported and
        // counted and the boot carries on, because nothing here depends on it.
        if (mcp::expanderMayStart(HAS_EXPANDER != 0, info.board)) expanderStart(millis());
        feedWatchdog();
#endif
        // each set-up is marked in RTC memory while it runs. a failed init is logged by the module
        // and only clears its flag so the boot carries on without that sensor.
        initCableSensors();
        if (HAS_MQ2) initMQ2(info.gasSkipWarmup);
        Wire.setClock(I2C_FREQ_HZ);
        feedWatchdog();

        // a line that rests low can leave one framing error byte at start-up. drop whatever
        // is waiting so it is never read as a line.
        if (HAS_NANO)  while (NanoSerial.available())  NanoSerial.read();
        if (HAS_STM32) while (STM32Serial.available()) STM32Serial.read();
        // the links start their clock here, after set-up, so a long set-up cannot use up the
        // start-up window and report a link as silent in the first post. a link that has already
        // delivered a checksummed line since power-up (kept across a warm reset) refuses the old
        // format from the start.
        lcInit(&nanoLink,  LINK_NANO,  millis(), (info.linksSeen & 1) != 0);
        lcInit(&stm32Link, LINK_STM32, millis(), (info.linksSeen & 2) != 0);
    }

    HubStepIn readAll() override { return readAllSensors(); }
    void applyOutputs(const HubStepOut& out) override { ::applyOutputs(out); }

    // two startup beeps so the installer knows the node has finished booting and the splash last.
    // the splash says when the water alarm is unproven. the serial monitor says so for the gas path
    void splashAndBeeps(bool waterUnproven, bool gasUnproven) override {
        beep(100);
        delay(100);
        beep(100);
        displaySplash("PHAEMOS", waterUnproven ? "WATER ALARM UNPROVEN"
                                               : (gasUnproven ? "GAS ALARM UNPROVEN" : "v2 starting..."));
        feedWatchdog();
    }

    void dropWatchdog() override { esp_task_wdt_init(WDT_TIMEOUT_S, true); }
    uint32_t nowMs() override { return millis(); }
};

static EspPlatform plat;

// ============================================================
// setup
// ============================================================
void setup() {
    // drive the relay pins LOW before anything else. GPIO12 is a boot strap that must be low at
    // reset and the others must not switch a load while booting. GPIO14 is not touched: it is
    // relay 3 on the present board and the sensor supply switch on the revised board, so it waits
    // for the board check. the core calls this again as the first step of its recorded order.
    initRelay();

    Serial.begin(115200);
    Serial.println(F("PHAEMOS v2 booting..."));

    credsLoad(&g_creds);
    identOk = nextBootCount(&bootCount);
    provInit(&g_prov);
    provConsoleInit(&g_console);
    pinMode(PROVISION_CLEAR_PIN, INPUT_PULLUP);
    if (!g_creds.present) {
        Serial.println(F("No credentials stored. send HELP on this console to provision the hub"));
    }
    healthInit();
    recoveryInit(&bmeRec);
    recoveryInit(&mpuRec);
    recoveryInit(&inaRec);
    recoveryInit(&vlRec);
    recoveryInit(&mlxRec);
    recoveryInit(&asRec);

    // the whole boot is in the core, in a fixed order the host test checks
    core.init(&rtcSaved);
    core.boot(plat, (int)esp_reset_reason());

    nextReadingMs = millis() + TELEMETRY_INTERVAL_MS;
    Serial.print(F("Setup complete. boot "));
    Serial.print(bootCount);
    Serial.print(F(", reset reason "));
    Serial.println(resetReasonName(esp_reset_reason()));
}

// ============================================================
// loop
// ============================================================
void loop() {
    uint32_t now = millis();

    provisionPoll();
    provisionButtonPoll(now);
#if HAS_EXPANDER
    // a board check that was unknown at boot and has since said the expander answers starts it late
    if (!expanderStarted() && mcp::expanderMayStart(HAS_EXPANDER != 0, core.board())) expanderStart(now);
    // polls the expander when a poll is due. it never holds the loop for longer than one bus time-out.
    expanderTick(now);
    expanderButtonPoll(now);
#endif

    // feed the watchdog once per pass, but only while the post task is healthy. the task
    // watchdog has one timeout for everything it watches, so the post task (which can wait
    // up to the post wall clock on the network) is supervised here with its own limits instead of
    // being subscribed.
    if (postTaskHealthy(now)) feedWatchdog();

    // ── Watch the receive lines ──────────────────────────────────────────────
    // sample the pins on a steady cadence so a run of low samples means a line at rest.
    if (now - lastLinkPoll >= SERIAL_POLL_MS) {
        lastLinkPoll = now;
        if (HAS_NANO)  lcNoteLevel(&nanoLink,  gpio_get_level((gpio_num_t)NANO_RX_PIN)  != 0, now);
        if (HAS_STM32) lcNoteLevel(&stm32Link, gpio_get_level((gpio_num_t)STM32_RX_PIN) != 0, now);
    }

    // ── Move bytes from the Nano and STM32 ───────────────────────────────────
    // read what has arrived without waiting for a line end, so a partial line never holds
    // the loop. each call also sends a ping when one is due.
    if (HAS_NANO)  serialLinkPoll(&nanoLink,  NanoSerial,  now);
    if (HAS_STM32) serialLinkPoll(&stm32Link, STM32Serial, now);

    // ── Shaft sampling ───────────────────────────────────────────────────────
    if (HAS_AS5600 && asRec.ready && now - lastAS5600 >= AS5600_SAMPLE_MS) {
        lastAS5600 = now;
        sampleAS5600();
    }

    // ── Reading interval: read sensors, judge them, build the body ───────────
    // the timer is fixed and nothing in the pass can move it. handing the body over takes
    // microseconds, because the post task does the waiting.
    if ((int32_t)(now - nextReadingMs) >= 0) {
        // move on by whole intervals. if the loop was ever held up for a whole interval or
        // more, start again from now instead of running a burst to catch up.
        nextReadingMs += TELEMETRY_INTERVAL_MS;
        if ((int32_t)(now - nextReadingMs) >= 0) nextReadingMs = now + TELEMETRY_INTERVAL_MS;
        core.recheckBoard(plat);              // only does anything while the board is unknown
        HubStepIn in = readAllSensors();
        // the core keeps that a link has delivered a checksummed line since power-up in the saved state
        core.setLinksSeen((uint8_t)((HAS_NANO && nanoLink.seenSincePower ? 1 : 0) |
                                    (HAS_STM32 && stm32Link.seenSincePower ? 2 : 0)));
        HubStepOut out = core.step(in);
        applyOutputs(out);
        buildAndSubmitBody();
    }

    // ── Bench counters on the serial monitor once a minute ───────────────────
    // the backend schema may not keep diag yet and the loop task's stack mark is printed nowhere else
    if (now - lastDiagLog >= 60000UL) {
        lastDiagLog = now;
        Serial.printf("diag: post ok %u failed %u replaced %u too_big %u stack post %u loop %u heap min %u block %u\n",
                      (unsigned)postCountOk(), (unsigned)postCountFailed(), (unsigned)postCountReplaced(),
                      (unsigned)bodyTooBig, (unsigned)postStackHighWater(), (unsigned)loopStackFree,
                      (unsigned)ESP.getMinFreeHeap(), (unsigned)ESP.getMaxAllocHeap());
#if HAS_EXPANDER
        const mcp::ExCounters& ec = expanderCounters();
        Serial.printf("expander: rails_unknown_s %u start_failed %u lost %u recovered %u reconfigured %u untrusted %u bus_stuck %u read_failed %u presses %u long %u sens_not_back %u\n",
                      (unsigned)(expanderRailsUnknownForMs(now) / 1000u),
                      (unsigned)ec.startFailures, (unsigned)ec.lost, (unsigned)ec.recovered, (unsigned)ec.reconfigured,
                      (unsigned)ec.untrusted, (unsigned)ec.busStuck, (unsigned)ec.readFailures,
                      (unsigned)ec.presses, (unsigned)ec.longPresses, (unsigned)ec.sensRailNotBack);
#endif
    }

    // ── OLED refresh interval ─────────────────────────────────────────────────
    // the display only redraws when the text changed.
    if (now - lastOLED >= OLED_UPDATE_MS) {
        lastOLED = now;
        displayTelemetry(bmeData, mpuData, inaData, distMm, gasAlert, waterAlert,
                         statusText);
    }

    // ── Alert sounds ──────────────────────────────────────────────────────────
    serviceAlerts(now);
    buzzerUpdate();
}

// ============================================================
// sensor state helpers
// ============================================================

// noteState records whether a reading can be trusted and logs only when that
// changes, so a sensor that stays missing does not flood the serial monitor.
static void noteState(const char* name, bool* valid, bool now, const char* why) {
    if (now == *valid) return;
    *valid = now;
    Serial.print('[');
    Serial.print(name);
    Serial.print(now ? F("] reading is back") : F("] reading left out - "));
    if (!now) Serial.print(why);
    Serial.println();
}

// observeAbsent counts one probe and logs when the sensor's reported state changes.
static void observeAbsent(SensorKey key, bool absent) {
    HealthState before = healthState(key);
    healthObserveAbsent(key, absent, millis());
    HealthState after = healthState(key);
    if (after != before) {
        Serial.print(F("[health] "));
        Serial.print(healthKeyName(key));
        Serial.print(F(" is "));
        Serial.println(healthStateName(after));
    }
}

// identity checks. an address that answers is not enough, because another part could sit
// on it or the chip could have come back in an odd state.
static bool bmeIdOk(uint8_t id)  { return id == 0x60 || (id >= 0x56 && id <= 0x58); }
static bool mpuIdOk(uint8_t id)  { return id == 0x68; }
static bool vl53IdOk(uint8_t id) { return id == 0xEE; }

// probeSensor checks a sensor still answers on the bus before it is read.
// it also checks the identity register where the part has one. a driver would otherwise hand back junk (the
// BME280 returns about 180 degC) for a device that dropped off. three failed probes in a
// row mark it missing. three inside a minute that never run in a row mark it
// intermittent. any failed probe marks its set-up as lost, so the next probe that succeeds
// runs the set-up again before the sensor is read. that covers a short power dip that resets
// the part and leaves its address and identity unchanged. the set-up is tried at most every
// REINIT_MIN_INTERVAL_MS. a set-up that fails on a part that answers is reported as a
// fault. returns true when the sensor is present and set up.
static bool probeSensor(SensorKey key, const char* name, SetupId setupId, uint8_t addr,
                        bool (*initFn)(), Recovery* rec, bool* valid,
                        int idReg = -1, bool (*idOk)(uint8_t) = nullptr) {
    uint32_t now = millis();
    bool present = i2cPresent(addr);
    if (present && idOk) {
        uint8_t id = 0;
        present = i2cReadReg8(addr, (uint8_t)idReg, &id) && idOk(id);
    }
    observeAbsent(key, !present);
    if (!present) {
        recoveryNoteLost(rec);
        noteState(name, valid, false, "no answer on the I2C bus");
        return false;
    }

    if (!rec->ready) {
        if (!recoveryMayTry(rec, now, REINIT_MIN_INTERVAL_MS)) {
            noteState(name, valid, false, "waiting to be set up again");
            return false;
        }
        Serial.print('[');
        Serial.print(name);
        Serial.println(F("] answering - running its set-up"));
        // the set-up is marked in RTC memory, so a stall in it costs one reset and not every boot
        bool excluded = false;
        bool ok = guardedInit(setupId, initFn, &excluded);
        recoveryNoteTry(rec, ok, now);
        if (excluded) {
            reportSkipped(setupId, true);
            noteState(name, valid, false, "left out until power-up");
            return false;
        }
        if (!ok) {
            // it answers but cannot be set up. never leave that as ok.
            setHealth(key, HS_MISSING);
            noteState(name, valid, false, "set-up failed");
            return false;
        }
        setHealth(key, HS_OK);
    }
    return true;
}

// ============================================================
// readAllSensors - called on every reading interval
// ============================================================
HubStepIn readAllSensors() {
    uint32_t now = millis();

    // BME280 or BMP280. a part that has reset keeps answering with the right identity. its
    // ctrl_meas register reads 0 (sleep mode) and the data registers hold the reset word. the
    // BME280 driver turns that into NAN, but the BMP280 driver compensates it into a plausible
    // 26 degC, so the check reads the register and does not rely on the reading. the chip may
    // answer on either address, so a set-up that has not worked yet looks at both.
    uint8_t bmeAddr = bmeRec.ready ? bme280Address()
                                   : (i2cPresent(BME280_ADDR) ? (uint8_t)BME280_ADDR : (uint8_t)0x77);
    if (HAS_BME280 && probeSensor(SK_BME280, "BME280", SETUP_BME280, bmeAddr, initBME280, &bmeRec, &bmeValid, 0xD0, bmeIdOk)) {
        uint8_t ctrl = 0x03;
        bool asleep = i2cReadReg8(bmeAddr, 0xF4, &ctrl) && bmeLostSetup(ctrl);
        bool isNan = false;
        bool sane = false;
        bmeOverRange = false;
        if (!asleep) {
            readBME280(&bmeData);
            isNan = isnan(bmeData.temperature) || isnan(bmeData.pressure);
            // a part that stopped converting keeps returning the same data words. with the
            // oversampling in use the lowest bits carry noise, so 24 identical reads in a row
            // (two minutes) means a frozen part. the raw words are read, because the compensated
            // value would hide a change in a low bit
            uint8_t raw[8];
            bool stuck = i2cReadBytes(bmeAddr, 0xF7, raw, 8) && stuckNote(&bmeStuck, raw, BME_STUCK_READS);
            if (stuck) {
                isNan = true;
                Serial.println(F("[BME280] data words have not changed for a long time - treated as stuck"));
            }
            sane = !isNan
                && bmeData.temperature >= BME_TEMP_MIN_C
                && bmeData.temperature <= BME_TEMP_MAX_C;
            // a part that passed its address, identity and control register checks and reads
            // above its range is hot and not dead. the reading is still left out of the post and
            // reported out_of_range, but it counts as over-temperature for the relay. values beyond
            // BME_TEMP_OVERRANGE_MAX_C are junk.
            bmeOverRange = !isNan && bmeData.temperature > BME_TEMP_MAX_C &&
                           bmeData.temperature <= BME_TEMP_OVERRANGE_MAX_C;
        }
        noteState("BME280", &bmeValid, sane, asleep ? "set-up lost after a reset"
                                                    : "reading outside what the part can report");
        setHealth(SK_BME280, sane ? HS_OK : HS_OUT_OF_RANGE);
        noteSensorGood(SETUP_BME280, sane, now);
        // a lost set-up or a NAN sets it up again at once. an impossible value does after a few passes.
        if (recoveryNoteContent(&bmeRec, !sane, (asleep || isNan) ? 1 : CONTENT_REINIT_PASSES)) {
            Serial.println(F("[BME280] bad readings - set-up will run again"));
        }
    }
    else {
        bmeOverRange = false;     // not probed this pass
    }
    if (!bmeValid) {
        bmeData.temperature = bmeData.humidity = bmeData.pressure = NAN;
    }

    // MPU6050 - a reset leaves it asleep and answering with the right identity. the sleep bit
    // and an all-zero reading both show that.
    if (HAS_MPU6050 && probeSensor(SK_MPU6050, "MPU6050", SETUP_MPU6050, MPU6050_ADDR, initMPU6050, &mpuRec, &mpuValid,
                    0x75, mpuIdOk)) {
        uint8_t pwr = 0;
        bool asleep = i2cReadReg8(MPU6050_ADDR, 0x6B, &pwr) && mpuSleepBitSet(pwr);
        bool good = false;
        if (!asleep) {
            readMPU6050(&mpuData);
            good = !mpuAllZero(mpuData.accel_x, mpuData.accel_y, mpuData.accel_z);
        }
        noteState("MPU6050", &mpuValid, good, asleep ? "asleep after a reset" : "all axes read zero");
        setHealth(SK_MPU6050, good ? HS_OK : HS_OUT_OF_RANGE);
        noteSensorGood(SETUP_MPU6050, good, now);
        if (recoveryNoteContent(&mpuRec, !good, 1)) {
            Serial.println(F("[MPU6050] reset detected - set-up will run again"));
        }
    }
    if (!mpuValid) {
        mpuData.accel_x = mpuData.accel_y = mpuData.accel_z = NAN;
        mpuData.gyro_x  = mpuData.gyro_y  = mpuData.gyro_z  = NAN;
    }

    // INA219 - the library writes the calibration again on every current read, so a reset
    // part recovers by itself. the calibration register still shows the loss. the
    // overflow bit marks current and power as unusable.
    if (HAS_INA219 && probeSensor(SK_INA219, "INA219", SETUP_INA219, INA219_ADDR, initINA219, &inaRec, &inaValid)) {
        uint16_t cal = 1;
        uint16_t bus = 0;
        if (i2cReadReg16(INA219_ADDR, 0x05, &cal) && inaLostSetup(cal)) {
            recoveryNoteContent(&inaRec, true, 1);
            Serial.println(F("[INA219] calibration lost - set-up will run again"));
        }
        readINA219(&inaData);
        bool overflow = i2cReadReg16(INA219_ADDR, 0x02, &bus) && inaOverflow(bus);
        noteState("INA219", &inaValid, !overflow, "overflow flag set");
        setHealth(SK_INA219, overflow ? HS_OUT_OF_RANGE : HS_OK);
        noteSensorGood(SETUP_INA219, !overflow, now);
    }
    if (!inaValid) {
        inaData.bus_voltage = inaData.current_ma = inaData.power_mw = NAN;
    }

    // VL53L0X - an error return from the driver means the part needs its set-up again. a
    // failed range status is only a reading left out. the part has no register that the
    // pinned library sets and that we could read back to tell a reset, so only the driver's
    // own error return shows it.
    if (HAS_VL53L0X && probeSensor(SK_VL53L0X, "VL53L0X", SETUP_VL53L0X, VL53L0X_ADDR, initVL53L0X, &vlRec, &vlValid,
                    0xC0, vl53IdOk)) {
        uint16_t mm = 0;
        Vl53Result r = readVL53L0X(&mm);
        noteState("VL53L0X", &vlValid, r == VL53_OK, r == VL53_ERROR ? "ranging error" : "no valid range");
        setHealth(SK_VL53L0X, r == VL53_ERROR ? HS_OUT_OF_RANGE : HS_OK);
        noteSensorGood(SETUP_VL53L0X, r != VL53_ERROR, now);
        if (r == VL53_OK) distMm = mm;
        if (recoveryNoteContent(&vlRec, r == VL53_ERROR, 1)) {
            Serial.println(F("[VL53L0X] ranging error - set-up will run again"));
        }
    }
    if (!vlValid) distMm = 0;

    if (HAS_MLX90614 && probeSensor(SK_MLX90614, "MLX90614", SETUP_MLX90614, MLX90614_ADDR, initMLX90614, &mlxRec, &mlxValid)) {
        mlxObject = readMLX90614();
        bool sane = !isnan(mlxObject) && mlxObject >= MLX_TEMP_MIN_C && mlxObject <= MLX_TEMP_MAX_C;
        noteState("MLX90614", &mlxValid, sane, "no valid temperature");
        setHealth(SK_MLX90614, sane ? HS_OK : HS_OUT_OF_RANGE);
        noteSensorGood(SETUP_MLX90614, sane, now);
        // the part keeps its set-up in its own memory, so a reset loses nothing. a long run
        // of bad reads still gets one set-up in case the bus object is stale.
        recoveryNoteContent(&mlxRec, !sane, CONTENT_REINIT_PASSES);
    }
    if (!mlxValid) mlxObject = NAN;

    // AS5600 - the loop samples it often. a missing device, a missing magnet or an empty
    // window means there is no usable angle. the part needs no set-up of its own, so a reset
    // loses nothing. the status register says whether the magnet is there.
    if (HAS_AS5600 && probeSensor(SK_AS5600, "AS5600", SETUP_AS5600, AS5600_ADDR, initAS5600, &asRec, &asValid)) {
        uint8_t stat = 0x20;
        bool gotStat = i2cReadReg8(AS5600_ADDR, 0x0B, &stat);
        HealthState mag = gotStat ? as5600MagnetState(stat) : HS_OK;
        static bool wasMarginal = false;
        bool marginal = gotStat && as5600MagnetMarginal(stat);
        if (marginal != wasMarginal) {
            wasMarginal = marginal;
            Serial.println(marginal ? F("[AS5600] magnet too weak or too strong - angle still valid")
                                    : F("[AS5600] magnet gap back in range"));
        }
        bool good = readAS5600(&as5600Angle, &as5600Rpm);
        setHealth(SK_AS5600, mag);
        noteSensorGood(SETUP_AS5600, good && mag == HS_OK, now);
        noteState("AS5600", &asValid, good && mag == HS_OK,
                  mag != HS_OK ? "magnet not detected" : "too few samples in the window");
    }

    // DS18B20 - the driver returns -127 on a failed read. a read is the probe. a probe
    // that was never found or is marked missing is searched for again on every pass, quietly.
    // the pass that finds it again only sets it up, because the first conversion is not
    // ready yet. a part that has reset holds exactly 85.0 degC until its first conversion
    // ends, so that value is not believed unless the reading before it was close.
    if (!HAS_DS18B20) {
        dsValid = false;
    } else if (!dsOk) {
        // the search is guarded like any set-up: marked in RTC memory, struck after a task
        // watchdog reset, left out after two and tried at most every REINIT_MIN_INTERVAL_MS
        if (dsLastSearchMs == 0 || now - dsLastSearchMs >= REINIT_MIN_INTERVAL_MS) {
            dsLastSearchMs = now ? now : 1;
            bool excluded = false;
            dsOk = guardedInit(SETUP_DS18B20, []() { return initDS18B20(true); }, &excluded);
            if (excluded) reportSkipped(SETUP_DS18B20, true);
            dsHavePrevious = false;
            observeAbsent(SK_DS18B20, !dsOk);
            if (dsOk) setHealth(SK_DS18B20, HS_OK);
        }
        noteState("DS18B20", &dsValid, false, "probe not found");
    } else {
        ds18bTemp = readDS18B20();
        bool absent = !(ds18bTemp > -100.0f);
        observeAbsent(SK_DS18B20, absent);
        if (absent) {
            noteState("DS18B20", &dsValid, false, "probe read failed");
            // once confirmed missing the probe is searched for again on the next pass.
            if (healthState(SK_DS18B20) == HS_MISSING) dsOk = false;
        } else {
            bool powerOn = ds18PowerOnValue(ds18bTemp, dsPrevious, dsHavePrevious);
            bool sane = !powerOn && ds18bTemp >= DS18_TEMP_MIN_C && ds18bTemp <= DS18_TEMP_MAX_C;
            setHealth(SK_DS18B20, sane ? HS_OK : HS_OUT_OF_RANGE);
            noteSensorGood(SETUP_DS18B20, sane, now);
            noteState("DS18B20", &dsValid, sane, powerOn ? "power-on value after a reset"
                                                         : "temperature outside -55 to 125 degC");
            if (!powerOn) {
                dsPrevious = ds18bTemp;
                dsHavePrevious = true;
            }
        }
    }

    // MQ-2 - the module keeps its own warm-up and fault logic.
    if (HAS_MQ2) {
        readMQ2(&gasLevel, &gasAlert, &gasRaw, &gasLow);
        if (mq2WarmingUp())                    setHealth(SK_MQ2, HS_WARMING_UP);
        else if (mq2Fault() || mq2Disagree())  setHealth(SK_MQ2, HS_OUT_OF_RANGE);
        else                                   setHealth(SK_MQ2, HS_OK);
    }

#if HAS_FC28
    // moisture - an unplugged input reads 0 V on the revised board. a probe flooded with a
    // conductive liquid can read nearly as low. the two cannot be told apart here. the
    // leak alarm therefore wins: readFC28 raises the water flag for any reading under
    // WATER_THRESHOLD and this check never clears it. the unplugged state withholds only the
    // moisture level from the post. water_detected is still posted and the backend alarms on it.
    readFC28(&moistureLevel, &waterAlert);
    if (HAS_INPUT_PULLDOWNS || HAS_PROBE_SERIES_R) setHealth(SK_FC28, moistureState(moistureLevel, &moistLowPasses));
#else
    waterAlert = false;
#endif

    // the LDR has no fault band, because a short cannot be told from bright light.
    if (HAS_LDR) ldrLevel = readLDR();

    if (HAS_MAX4466) micLevel = readMAX4466(&micMean);
    if (HAS_MAX4466 && HAS_INPUT_PULLDOWNS) setHealth(SK_MAX4466, micState(micMean));

    // 12 V input
#if HAS_INPUT_MONITOR
    inputVolts = readInputVoltage();
    setHealth(SK_SUPPLY, supplyState(inputVolts));
#endif

    // serial links. a satellite's status bits only count as faults while its link is usable.
    // they also have to be set on two lines in a row (stStable).
    if (HAS_NANO) {
        LinkHealth h = lcHealth(&nanoLink, now);
        setHealth(SK_NANO_LINK,   h.link);
        setHealth(SK_NANO_BME280, h.partA);
        setHealth(SK_NANO_SUPPLY, h.partB);
    }
    if (HAS_STM32) {
        LinkHealth h = lcHealth(&stm32Link, now);
        setHealth(SK_STM32_LINK,   h.link);
        setHealth(SK_STM32_MPU6050, h.partA);
    }

#if HAS_EXPANDER
    // a cable sensor that answered this pass is what lets the sensor rail be called present, because
    // SENS_OK can be held high through the I2C pull-ups with the rail off. these are the sensors
    // initCableSensors sets up
    if (bmeValid || mpuValid || inaValid || vlValid || mlxValid || asValid || dsValid) expanderNoteSensorAnswered(now);
    // the expander and the seven rails, with plain words already on the serial monitor. an expander
    // that is not running is stale and every watched rail with it
    expanderSyncHealth();
#endif

    // reduce the pass to what the core judges
    HubStepIn in;
    memset(&in, 0, sizeof in);
    in.nowMs = now;
    in.temp.bme.trusted = bmeValid;
    in.temp.bme.tempC   = bmeValid ? bmeData.temperature : 0.0f;
    in.temp.bmeOverRange = bmeOverRange;
    in.temp.ds.trusted  = dsValid;
    in.temp.ds.tempC    = ds18bTemp;
    in.temp.mlx.trusted = mlxValid;
    in.temp.mlx.tempC   = mlxObject;
    in.bmeFault   = HAS_BME280 && !bmeValid;
    in.gasWarming = HAS_MQ2 && mq2WarmingUp();
    in.gasRaw     = gasRaw;
    in.gasDigitalLow = gasLow;
    in.moistureCounts = moistureLevel;
    in.postOkCount = postCountOk();
    in.postRejected = postKeyRejected() || postAddressWrong();
    in.counterRejected = postCounterRejected();
    in.plainHttp = postPlainMode();
    // any other fitted sensor or link that is not ok. the three the panel names itself are left out
    for (uint8_t k = 0; k < SK_COUNT; k++) {
        SensorKey key = (SensorKey)k;
        if (key == SK_BME280 || key == SK_MQ2 || key == SK_FC28 || !sensorFitted(key)) continue;
        if (healthState(key) != HS_OK) in.otherFault = true;
    }
    return in;
}

// ============================================================
// applyOutputs - drives the light, the strip, the display text, the sound and the relay
// ============================================================
void applyOutputs(const HubStepOut& out) {
    LEDStatus next = (LEDStatus)out.status.shown;
    bool changed = (next != currentStatus);
    if (changed || strcmp(out.status.text, statusText) != 0) {
        snprintf(statusText, sizeof statusText, "%s", out.status.text);
        // state the status in words so it never depends on colour alone.
        Serial.print(F("Status: "));
        Serial.println(statusText);
    }
    if (changed) {
        currentStatus = next;
        // drive the LEDs only on a change because every strip update blocks
        // the loop for the length of the data frame.
        setPanelStatus(next);
        setLEDStatus(next);
    }
    // the sound follows the highest level and not the alternating one, so it does not beep on
    // every flip. sound straight away on any change away from normal.
    if (out.soundChanged) {
        soundBase    = out.soundBase;
        alertPending = (soundBase != STK_NORMAL);
        if (soundBase == STK_NORMAL) beepPattern(PATTERN_NORMAL);
    }
    // CH1 is the cooling fan/valve. load switching is reserved for confirmed CRITICAL so the
    // cooling system is not cycled on minor alerts.
    triggerRelay(RELAY_CH1, out.relayCh1);
    gasAlert   = out.gasAlert;
    waterAlert = out.waterAlarm;
    lastOut = out;
}

// ============================================================
void serviceAlerts(uint32_t now) {
    if (soundBase == STK_NORMAL) return;

    bool critical = (soundBase == STK_CRITICAL);
    uint32_t repeatMs = critical ? ALERT_REPEAT_CRITICAL_MS : ALERT_REPEAT_WARNING_MS;

    if (alertPending || now - lastAlertMs >= repeatMs) {
        // restart the repeat timer only when the sound really started. a request
        // dropped because another pattern is playing is tried again on the next pass.
        if (beepPattern(critical ? PATTERN_CRITICAL : PATTERN_WARNING)) {
            lastAlertMs  = now;
            alertPending = false;
        }
    }
}

// ============================================================
// buildAndSubmitBody - serialises the readings and hands them to the post task
// ============================================================
void buildAndSubmitBody() {
    // every body takes a number, even one that is replaced before it is sent, so a gap in the
    // numbers at the backend means readings were lost.
    // no body is built when the boot counter could not be trusted or the sequence is spent, so
    // the backend never sees a pair that repeats or goes backwards. seq restarts at 0 on every
    // boot, which is fine because boot has gone up. at its limit (about 680 years) it stops
    // and never wraps
    if (!identOk) return;
    if (!seqNext(&postSeq)) return;
    uint32_t seq = postSeq;

    TelemetryInput in;
    memset(&in, 0, sizeof in);
    in.deviceId    = g_creds.present ? g_creds.id : "unprovisioned";
    in.plainHttp   = postPlainMode();
    in.fw          = FIRMWARE_VERSION;
    in.resetReason = resetReasonName(esp_reset_reason());
    in.seq         = seq;
    in.boot        = bootCount;
    in.upSeconds   = (uint32_t)(esp_timer_get_time() / 1000000LL);
    in.haveRssi    = postWifiRssi(&in.rssi);
    in.heapFree    = ESP.getFreeHeap();

    in.bmeValid = bmeValid;  in.temperature = bmeData.temperature;
    in.humidity = bmeData.humidity;  in.pressure = bmeData.pressure;
    in.mpuValid = mpuValid;
    in.ax = mpuData.accel_x; in.ay = mpuData.accel_y; in.az = mpuData.accel_z;
    in.gx = mpuData.gyro_x;  in.gy = mpuData.gyro_y;  in.gz = mpuData.gyro_z;
    in.inaValid = inaValid;
    in.busVoltage = inaData.bus_voltage; in.currentMa = inaData.current_ma; in.powerMw = inaData.power_mw;
    in.vlValid = vlValid;    in.distMm = distMm;
    in.dsValid = dsValid;    in.contactTemp = ds18bTemp;
    in.mlxValid = mlxValid;  in.irTemp = mlxObject;
    in.asValid = asValid;    in.shaftAngle = as5600Angle; in.shaftRpm = as5600Rpm;
    in.gasValid = HAS_MQ2 && !mq2WarmingUp() && !mq2Fault();
    in.gasLevel = gasLevel;  in.gasAlert = gasAlert;
    in.moistureLevel = moistureLevel; in.waterAlert = waterAlert;
    in.ldrLevel = ldrLevel;  in.micLevel = micLevel;
    in.nano  = HAS_NANO  ? &nanoLink  : nullptr;
    in.stm32 = HAS_STM32 ? &stm32Link : nullptr;
    in.boardMismatch = core.board() == BOARD_MISMATCH;
    in.boardCheck = core.board() == BOARD_OK ? "ok" : (core.board() == BOARD_MISMATCH ? "mismatch" : "unknown");
    in.resetLoop = core.resetLoop();
    for (uint8_t i = 0; i < SETUP_COUNT; i++) {
        if (ssSetupExcluded(&rtcSaved, (SetupId)i)) in.setupExcludedMask |= (uint8_t)(1u << i);
    }
    static bool notFittedSent = false;
    in.sendNotFitted = !notFittedSent;
    notFittedSent = true;

    // counters for the first bench session
    uint32_t loopFree = uxTaskGetStackHighWaterMark(NULL);
    if (loopFree < loopStackFree) loopStackFree = loopFree;
    in.postOk = postCountOk();
    in.postFailed = postCountFailed();
    in.bodiesReplaced = postCountReplaced();
    in.bodiesTooBig = bodyTooBig;
    in.stackPostFree = postStackHighWater();
    in.stackLoopFree = loopStackFree;
    in.heapMinFree = ESP.getMinFreeHeap();
    in.heapLargestBlock = ESP.getMaxAllocHeap();

    // static buffers keep the document and the body off the loop task's stack and off the heap.
    static StaticJsonDocument<TELEMETRY_DOC_BYTES> doc;
    static char body[TELEMETRY_BODY_MAX_BYTES];
    doc.clear();
    bool fits = buildTelemetry(doc, in);

    // never send a cut-off body. a document that overflowed or a body that would not fit is
    // dropped and counted.
    size_t need = measureJson(doc);
    if (!fits || need >= sizeof body) {
        bodyTooBig++;
        Serial.print(F("Telemetry body too large ("));
        Serial.print(need);
        Serial.print(F(" bytes, limit "));
        Serial.print(sizeof body - 1);
        Serial.print(F(") - dropped, total dropped "));
        Serial.println(bodyTooBig);
        return;
    }
    size_t len = serializeJson(doc, body, sizeof body);
    if (!postSubmit(body, len)) {
        Serial.println(F("Telemetry body could not be handed to the post task"));
    }
}

