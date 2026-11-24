// ============================================================
// config.h - PHAEMOS ESP32 Configuration
// this file is tracked, so it holds defaults only and never a secret.
// the Wi-Fi password, the device key and the API address reach the hub in one of two ways:
//   1. at the bench over the serial console, stored in the hub's own flash (non-volatile
//      storage) and read from there on every boot. this is the default. one image fits every
//      hub and no secret is compiled in. see "Provisioning a hub" in README.md.
//   2. compiled in from secrets.h, which is never tracked (set USE_COMPILED_SECRETS to 1).
//      copy secrets.example.h to secrets.h and fill it in. a build that still has a placeholder
//      fails to compile and names what is missing.
// ============================================================

// `#pragma once` is a non-standard but universally supported guard that prevents this header
// being included more than once per compilation unit - safer than manual #ifndef guards.
#pragma once

// ─── Secrets ──────────────────────────────────────────────────────────────────
#ifndef USE_COMPILED_SECRETS
#define USE_COMPILED_SECRETS    0
#endif

// plain HTTP sends the device key and every reading across the network in clear. it exists for a
// bench with no certificate and nothing else. it is off by default and a release build refuses it.
// the hub shows PLN on its panel and posts plain_http while it runs in this mode.
#ifndef ALLOW_PLAIN_HTTP
#define ALLOW_PLAIN_HTTP        0
#endif

// a release build (-DPHAEMOS_RELEASE=1, the esp32dev_release and esp32dev_revb_release
// environments) has to carry real trust roots and cannot allow plain HTTP.
#ifndef PHAEMOS_RELEASE
#define PHAEMOS_RELEASE         0
#endif
#if PHAEMOS_RELEASE && ALLOW_PLAIN_HTTP
#error "PHAEMOS_RELEASE and ALLOW_PLAIN_HTTP together: a release build never posts over plain HTTP"
#endif

#if USE_COMPILED_SECRETS
#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "USE_COMPILED_SECRETS is 1 but secrets.h is missing: copy secrets.example.h to secrets.h and fill it in. secrets.h is never tracked."
#endif

// the placeholders that secrets.example.h carries. a value that is still one of them is a
// build that was never filled in.
constexpr bool cfgSame(const char* a, const char* b) {
    return *a == *b && (*a == 0 || cfgSame(a + 1, b + 1));
}
constexpr bool cfgStarts(const char* s, const char* prefix) {
    return *prefix == 0 || (*s == *prefix && cfgStarts(s + 1, prefix + 1));
}
#ifndef WIFI_SSID
#error "secrets.h does not define WIFI_SSID"
#endif
#ifndef WIFI_PASSWORD
#error "secrets.h does not define WIFI_PASSWORD"
#endif
#ifndef API_URL
#error "secrets.h does not define API_URL"
#endif
#ifndef DEVICE_API_KEY
#error "secrets.h does not define DEVICE_API_KEY"
#endif
#ifndef DEVICE_ID
#error "secrets.h does not define DEVICE_ID"
#endif
static_assert(!cfgSame(WIFI_SSID, "YourNetworkName"), "secrets.h still has the placeholder WIFI_SSID");
static_assert(!cfgSame(WIFI_PASSWORD, "YourNetworkPassword"), "secrets.h still has the placeholder WIFI_PASSWORD");
static_assert(!cfgStarts(API_URL, "http://your-backend-url") && !cfgStarts(API_URL, "https://your-backend-url"),
              "secrets.h still has the placeholder API_URL");
static_assert(!cfgSame(DEVICE_API_KEY, "your-device-api-key-from-admin-panel"),
              "secrets.h still has the placeholder DEVICE_API_KEY");
static_assert(!cfgSame(DEVICE_ID, "your-device-uuid"), "secrets.h still has the placeholder DEVICE_ID");
// a default build posts over TLS only, so its address has to start with https://. plain http
// needs ALLOW_PLAIN_HTTP, which is for a bench.
constexpr bool cfgEndsWithSlash(const char* s) {
    return *s != 0 && (s[1] == 0 ? *s == '/' : cfgEndsWithSlash(s + 1));
}
// the server answers 404 for a path with a trailing slash
static_assert(!cfgEndsWithSlash(API_URL), "API_URL must not end in a slash: the server answers 404 for it");
static_assert(ALLOW_PLAIN_HTTP || cfgStarts(API_URL, "https://"),
              "API_URL must start with https:// unless the bench flag ALLOW_PLAIN_HTTP is set");
#endif

// ─── Board switches ───────────────────────────────────────────────────────────
// these say what the hub hardware has. a part that is switched off is never watched,
// never reported in the faults map and has its forwarded fields left out, so a hub
// without it does not show a fault for ever. every switch can be set from the build
// (-DHAS_NANO=0 and so on). platformio.ini does that for the two boards:
//   esp32dev       the board that exists today. this is the default environment.
//   esp32dev_revb  the REVISED carrier board. it is not built yet and none of this
//                  firmware has run on it.
// the defaults below are the present board, so a build that sets nothing is that board.
#ifndef HAS_NANO
// a Nano board is plugged into the UART1 link.
#define HAS_NANO                1
#endif
#ifndef HAS_STM32
// a Black Pill board is plugged into the UART2 link.
#define HAS_STM32               1
#endif
#ifndef HAS_FC28
// a moisture probe is plugged into GPIO36. without one nothing is read or reported for it.
#define HAS_FC28                1
#endif
#ifndef HAS_PROBE_SERIES_R
// a 2.2 kohm resistor sits in the moisture probe's lead (a board change decided for the
// revised board, not built yet). with it an unplugged probe reads about 0 V, a flooded or
// shorted probe about 0.6 V and a dry probe about 3.0 V, so unplugged and flooded can be
// told apart and only a real flood raises the water alarm. without it near zero keeps the
// alarm on, because the two cannot be told apart.
#define HAS_PROBE_SERIES_R      0
#endif
// which of the hub's own sensors are fitted. a sensor that is switched off is never set up,
// never probed, never reported as a fault and never in the faults map, so a hub that does not
// carry every sensor does not sit on an amber light for ever (which would hide a real gas or
// water alarm in practice). the list is fixed at build time and is never learned at boot,
// because a sensor that is dead at power-up must not be taken for one that is not fitted. the
// keys that are switched off are posted as `not_fitted` until the first post succeeds, so the
// backend's own not-fitted list can be checked against them. the defaults are all fitted.
#ifndef HAS_BME280
#define HAS_BME280              1
#endif
#ifndef HAS_MPU6050
#define HAS_MPU6050             1
#endif
#ifndef HAS_INA219
#define HAS_INA219              1
#endif
#ifndef HAS_MLX90614
#define HAS_MLX90614            1
#endif
#ifndef HAS_VL53L0X
#define HAS_VL53L0X             1
#endif
#ifndef HAS_AS5600
#define HAS_AS5600              1
#endif
#ifndef HAS_DS18B20
#define HAS_DS18B20             1
#endif
#ifndef HAS_MQ2
#define HAS_MQ2                 1
#endif
#ifndef HAS_LDR
#define HAS_LDR                 1
#endif
#ifndef HAS_MAX4466
#define HAS_MAX4466             1
#endif
#ifndef HAS_INPUT_MONITOR
// the 12 V input divider is fitted on GPIO39. only the revised board has it.
#define HAS_INPUT_MONITOR       0
#endif
#ifndef HAS_SENSOR_RAIL_SWITCH
// GPIO14 is the sensor supply switch (revised board). when it is 0 the pin is relay 3 again
// (the present board). nothing here touches the sensor supply.
#define HAS_SENSOR_RAIL_SWITCH  0
#endif
#ifndef HAS_EXPANDER
// the MCP23017 at 0x20 is fitted (revised board). the driver is compiled in only when this is 1
// and starts only when the boot check has said the expander answers. the present board has none, so
// its image carries no expander code and its driver never starts. the boot check itself still
// probes 0x20 up to BOARD_PROBE_TRIES times on both images, to tell the two boards apart.
#define HAS_EXPANDER            0
#endif
#ifndef HAS_INPUT_PULLDOWNS
// the serial receive lines have 100 kohm pull-downs and the microphone and moisture
// inputs fall to 0 V when unplugged (revised board). without them the unplugged checks and
// the receive-pin pull-up change would be wrong, so they are skipped when this is 0.
#define HAS_INPUT_PULLDOWNS     0
#endif

// ─── v2 board ─────────────────────────────────────────────────────────────────
// everything below matches the v2 hardware: four nodes with eleven or more sensors.

// Wi-Fi timeout
// cap the connection wait at 10 s so the node doesn't hang indefinitely on boot.
#define WIFI_TIMEOUT_MS         10000


// ─── I2C bus ──────────────────────────────────────────────────────────────────
// every I2C sensor and the display share this one bus.
#define I2C_SDA                 21
#define I2C_SCL                 22
// the carrier board is built for a 100 kHz bus with seven devices on it.
#define I2C_FREQ_HZ             100000

// ─── I2C device addresses ─────────────────────────────────────────────────────
// every I2C sensor on the bus needs a unique address. These are hardware defaults.
#define BME280_ADDR             0x76
#define MPU6050_ADDR            0x68
#define INA219_ADDR             0x40
#define MLX90614_ADDR           0x5A
#define VL53L0X_ADDR            0x29
#define AS5600_ADDR             0x36
#define OLED_ADDR               0x3C
// the revised board adds an MCP23017 port expander, a second INA219 and a push button. the
// expander has a driver (sensors/mcp23017.cpp, built only when HAS_EXPANDER is 1). the second
// INA219 has none yet, so nothing in the firmware talks to it. it only has to be tolerated on the
// bus.
#define MCP23017_ADDR           0x20
// the second INA219 measures the relay and strip rail through a 0.1 ohm shunt at up to
// 1.5 A. its driver must set the 320 mV shunt range, because the 40 mV range would clip
// at 0.4 A.
#define INA219_RAIL_ADDR        0x41
#define OLED_WIDTH              128
#define OLED_HEIGHT             64

// ─── Analog sensor pins (v2 wiring) ───────────────────────────────────────────
// the LDR sits on GPIO33 so that GPIO34 is free for the MQ-2.
#define LDR_V2_PIN              33
#define MQ2_ANALOG_PIN          34
#define MQ2_DIGITAL_PIN         35
#define MAX4466_PIN             32
#define FC28_PIN                36

// an unplugged analogue input must not be posted as a reading. on the revised board both
// the microphone and the moisture input fall to 0 V when nothing is plugged in (the
// moisture input used to float to full scale). counts are on the 12-bit scale, 0 to 4095.
// the ADC at 11 dB reaches full scale at about 3.1 V, below the 3.3 V rail.
// a working MAX4466 idles near half the supply (about 2000 counts), so a mean this low
// can only mean no module. 150 counts is about 0.12 V.
#define MIC_UNPLUGGED_MAX_COUNTS     150
// a mean this high means the output is stuck at the rail.
#define MIC_RAIL_MIN_COUNTS          4000
// a dry moisture probe reads about 3.0 V and the top of the scale is its normal state.
// without the series resistor an unplugged input reads 0 V (revised board) and a probe
// flooded with a conductive liquid can also pull the pin down to a few hundred millivolts
// (the ADC reads zero up to about 0.1 V), so the two cannot be told apart. a reading under
// MOISTURE_UNPLUGGED_MAX_COUNTS for MOISTURE_UNPLUGGED_PASSES passes in a row is then
// reported as unplugged. the water alarm is kept, because a missed leak is worse than a false one.
#define MOISTURE_UNPLUGGED_MAX_COUNTS 50
#define MOISTURE_UNPLUGGED_PASSES     3
// with the 2.2 kohm series resistor (HAS_PROBE_SERIES_R) the bands are these. an unplugged
// probe reads about 0 V and a flooded or shorted one about 0.6 V, which is about 790 counts
// at 11 dB. 200 counts is about 0.15 V, above where the ADC reads zero and well under the
// flooded level. a reading at or under it is unplugged and never an alarm. a dry probe is
// about 3.0 V, which is about 3950 counts.
#define PROBE_UNPLUGGED_MAX_COUNTS    200
#define PROBE_FLOODED_NOMINAL_MV      600
#define PROBE_DRY_NOMINAL_MV          3000
// the LDR has no fault band. it sits in a divider with 10 kohm to ground, so zero is
// darkness and cannot be told from a break. a bright LDR of 500 ohm puts 3.1 V on the pin,
// which already reads full scale, so a short to 3.3 V cannot be told from bright light.

// ─── DS18B20 OneWire ──────────────────────────────────────────────────────────
// the probe's data line is on GPIO4 with a pull-up on the board.
#define DS18B20_PIN             4
#define DS18B20_RESOLUTION      12

// ─── Output pin definitions ───────────────────────────────────────────────────
// keep outputs on high-drive GPIOs that are not shared with the I2C/ADC bus.
#define BUZZER_PIN              25
#define RGB_LED_PIN             26
#define RGB_LED_COUNT           30
// the strip rail supplies about 1.2 A, so the firmware scales any colour down to stay under this.
// a WS2812B pixel draws about 20 mA per colour channel at full level plus about 1 mA idle.
#define STRIP_CURRENT_LIMIT_MA  1200
#define STRIP_MA_PER_CHANNEL    20
#define STRIP_IDLE_MA_PER_LED   1
#define RELAY_CH1_PIN           13
#define RELAY_CH2_PIN           12
// relay 3 moved from GPIO14 to GPIO23 on the revised board.
#if HAS_SENSOR_RAIL_SWITCH
#define RELAY_CH3_PIN           23
#else
// the present board still has relay 3 on GPIO14.
#define RELAY_CH3_PIN           14
#endif
#define RELAY_CH4_PIN           27
// panel LEDs: red and amber run from 3.3 V through a resistor so LOW lights them.
// green is switched by an NPN stage so HIGH lights it.
#define LED_RED_PIN             15
#define LED_GREEN_PIN           2
#define LED_AMBER_PIN           5
// relays and buzzer sit behind NPN stages, so HIGH switches them on.

// ─── Sensor supply switch and 12 V input ──────────────────────────────────────
// GPIO14 switches the 3.3 V feed to the cable sensors. driving it HIGH turns the feed
// off. the board holds the switch on by itself, so the pin must be an input (high
// impedance) at every other time. nothing may ever drive it HIGH as a relay pin.
#define SENSOR_POWER_PIN        14
// how long the feed stays off. long enough for the sensors to lose their state.
#define SENSOR_RAIL_OFF_MS      200
// the switch gate has a 100 nF capacitor and a 100 kohm resistor, so its time constant is
// 10 ms. wait five of them before releasing the bus lines.
#define SENSOR_RAIL_SETTLE_MS   50
// the slowest part (the MPU6050) needs about 100 ms after power before it answers.
#define SENSOR_RAIL_STARTUP_MS  150

// GPIO39 reads the 12 V input through 100 kohm over 10 kohm, so the input is the pin
// voltage times 11. the pin is input only and on ADC1. 12 V at the connector reads about
// 1.05 V here after the input diode, so the 0 to about 3 V range (11 dB) has plenty of room.
#define INPUT_VOLTAGE_PIN       39
#define INPUT_DIVIDER_TOP_OHM   100000UL
#define INPUT_DIVIDER_BOTTOM_OHM 10000UL
#define INPUT_VOLTAGE_SAMPLES   8
// the supply is reported as a fault outside this window. the reading is taken after the
// input diode, so it sits a little under the voltage at the connector.
#define SUPPLY_MIN_V            9.0f
#define SUPPLY_MAX_V            15.0f

// ─── Serial ports for Nano and STM32 ─────────────────────────────────────────
// use UART1 for the Nano and UART2 for the STM32 to avoid conflicts with
// the debug serial port (UART0) used by Serial.begin(115200).
#define NANO_RX_PIN             16
#define NANO_TX_PIN             17
#define NANO_BAUD               9600
// both receive pins have a 100 kohm pull-down on the board, so an unplugged cable reads
// as a steady low. the serial driver would switch the internal pull-up on and defeat
// that, so setup() turns it off again after each port starts.
#define STM32_RX_PIN            18
#define STM32_TX_PIN            19
#define STM32_BAUD              115200

// ─── v2 timing constants ──────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS   5000
#define OLED_UPDATE_MS          1000
#define SERIAL_POLL_MS          100
// drop a Nano or STM32 reading when no good line has arrived for this long.
#define SERIAL_STALE_MS         15000
// a receive line that rests low for this long with no byte is reported as line_low. the
// loop samples the pin every SERIAL_POLL_MS. the sample count stops a long blocking
// post from faking a low stretch out of two samples seconds apart.
#define LINK_LINE_LOW_MS        5000
#define LINK_LINE_LOW_MIN_SAMPLES 20
// a line that idles high with no valid line for this long is reported as silent.
#define LINK_SILENT_MS          SERIAL_STALE_MS
// the hub pings each fitted satellite this often and expects a pong within the window.
#define LINK_PING_INTERVAL_MS   30000
#define LINK_PONG_WINDOW_MS     500
// this many pings in a row without a pong while lines still arrive is one_way.
#define LINK_ONE_WAY_PINGS      3
// repeat an alert sound this often while the condition lasts, so the loop is never held up.
#define ALERT_REPEAT_WARNING_MS  30000
#define ALERT_REPEAT_CRITICAL_MS 10000

// ─── MQ-2 heater and fault handling ───────────────────────────────────────────
// the heater needs time to settle before the digital output means anything.
#define MQ2_WARMUP_MS           180000UL
// after the warm-up an analogue reading under this (0-4095 scale) is a sensor fault whatever
// the digital line says: a dead 5 V rail or an unplugged module, not clean air. the digital
// output is pulled up to 3.3 V by the board, so an unplugged module reads high and would
// otherwise silence the alarm with a green panel. the analogue output reaches GPIO34 through
// a 2/3 divider (5 V becomes 3.33 V) with 20 kohm to ground, so an unplugged module reads
// 0 V (about 0 counts). a heated MQ-2 in clean air is a few tenths of a volt after the
// divider, about 200 to 530 counts (UNMEASURED, the bench has to confirm it). 100 counts is
// about 0.08 V by the nominal scale. the ESP32 ADC reads zero up to roughly 0.1 V at this
// attenuation, so the real figure at the pin is nearer 0.1 to 0.2 V and a healthy module in
// clean air could sit under it and show a fault for ever. the bench has to check that.
#define MQ2_FAULT_ADC_MAX       100
// a second, independent gas alarm path: the analogue level. either path raises the gas alarm.
// the digital path alone would leave a module with a dead or broken digital output and a live
// analogue output reading as clean air with a green panel. 1600 counts is the old, unused
// GAS_WARNING_LEVEL of 400 on the 0 to 1023 scale (about 1.3 V at the pin). it is a guess:
// the gas alarm's analogue path is UNPROVEN until it has been measured with a test gas and
// GAS_ALARM_PROVEN stays 0 until then. the hub says so at boot.
#define GAS_ANALOGUE_ALARM_COUNTS 1600
#define GAS_ALARM_PROVEN        0
// the top of the clean-air band (about 200 to 530 counts, unmeasured). a digital alarm with the
// analogue level at or under this (and over MQ2_FAULT_ADC_MAX) is a disagreement between the
// two paths and is reported as a fault. the alarm itself is still raised, which is the safe side.
#define MQ2_CLEAN_AIR_MAX_COUNTS 530

// ─── Network timeouts ─────────────────────────────────────────────────────────
// a dead backend must not hold the loop for long, so cap each phase of a POST.
#define HTTP_CONNECT_TIMEOUT_MS  2000
#define HTTP_RESPONSE_TIMEOUT_MS 2000
// (the post uses the connect time-out. the OTA check uses both)
// how often the serial log repeats the "Wi-Fi down" message.
#define WIFI_DOWN_LOG_MS         30000
// the whole post (resolve, connect, send and read the status line) has to finish inside this
// wall-clock time. the task enforces it itself, so a server that sends a header line every
// 1.9 s cannot hold the post past it. the one thing it cannot interrupt is the pinned core's
// DNS wait (up to 15 s with one caller and the core can wait 16 s for an earlier lookup),
// which counts against the same limit.
#define POST_WALL_CLOCK_MS       20000UL
// a TLS post spends part of that budget on the handshake. the plan gives the TCP connect at most
// HTTP_CONNECT_TIMEOUT_MS and the handshake at most HTTP_TLS_HANDSHAKE_MS. HTTP_TLS_RESERVE_MS is
// kept back for sending the request and reading the status line. the handshake on this chip is
// documented at one to three seconds and has not been measured here. the hub prints the figure
// after its first post and every 60 posts.
#define HTTP_TLS_HANDSHAKE_MS    8000UL
#define HTTP_TLS_RESERVE_MS      3000UL
// a handshake is not started with less than this (the documented time is one to three seconds) and a
// connect not with less than this.
#define HTTP_TLS_MIN_HANDSHAKE_MS 3000UL
#define HTTP_TLS_MIN_CONNECT_MS   1000UL
// the clock. the hub checks every certificate's dates against it (the core's mbedTLS does not, see
// comms/tls_checks.h), so a TLS post waits until SNTP has set it.
// a round of asking lasts TIME_SYNC_WINDOW_MS. after a round with no answer the post task waits
// TIME_RETRY_START_MS and doubles that up to TIME_RETRY_MAX_MS before asking again. while the
// clock is unset no TLS post is tried, the panel shows NET after POST_STALE_MS and the alarms and
// relays carry on. the server's Date header is not used as a source, because it arrives inside
// the connection that needs the clock.
#define TIME_SYNC_WINDOW_MS      15000UL
#define TIME_RETRY_START_MS      10000UL
#define TIME_RETRY_MAX_MS        300000UL
#define NTP_SERVER_1             "pool.ntp.org"
#define NTP_SERVER_2             "time.cloudflare.com"
#define NTP_SERVER_3             "time.google.com"
// provisioning. holding the button (GPIO0, the BOOT button of the DevKit) low for
// PROVISION_CLEAR_HOLD_MS during the first PROVISION_CLEAR_WINDOW_MS after boot clears the stored
// credentials. do not hold it while pressing reset: GPIO0 low at reset starts the bootloader.
// the revised board's own push button is on the port expander (GPB0, see sensors/mcp23017.h), so
// this pin stays the BOOT button. a long press of the expander button does the same clear in
// the same window.
#ifndef PROVISION_CLEAR_PIN
#define PROVISION_CLEAR_PIN      0
#endif
#define PROVISION_CLEAR_HOLD_MS  5000UL
#define PROVISION_CLEAR_WINDOW_MS 30000UL
// ─── Port expander (revised board) ────────────────────────────────────────────
// no interrupt line reaches the module, so the driver polls. every figure here is chosen and not
// measured on a board.
// one two-byte read of GPIOA and GPIOB per poll, about 0.5 ms of bus time at 100 kHz.
#define EXPANDER_POLL_MS          20UL
// every this often all 22 registers are read back and compared with what was written. a brown-out
// resets the chip to all inputs with pull-ups off and only this read shows it.
#define EXPANDER_CONFIG_CHECK_MS  1000UL
// the push button is debounced in firmware. it counts as pressed after reading low for this long
// and as released after reading high for this long. a poll is 20 ms, so these are 2 and 3 polls.
#define BUTTON_PRESS_MS           40UL
#define BUTTON_RELEASE_MS         60UL
// a press held this long is a long press. it is the same hold the provisioning clear asks for.
#define BUTTON_LONG_PRESS_MS      PROVISION_CLEAR_HOLD_MS
// a rail input has to read the same for this long before the rail is reported present or absent.
// a rail that sits in the band where the input is undefined cannot report in less than this.
#define RAIL_DEBOUNCE_MS          500UL
// this many changes of a raw rail reading inside the window is a rail that is flapping. it is
// reported intermittent until the window has passed with fewer.
#define RAIL_FLAP_EDGES           6
#define RAIL_FLAP_WINDOW_MS       10000UL
// which of the seven rail inputs are watched, as a bit mask in the order AUX, FEED1, FEED2, FEED3,
// SENS, STRIP, ENABLE. a hub that does not use a feed clears its bit and the rail is never reported.
#define EXPANDER_RAIL_EXPECTED_MASK 0x7F
// this many failed reads inside EXPANDER_FAIL_WINDOW_MS, in a row or not, call the chip down. one
// failed read is only counted. after any failed read the next poll waits EXPANDER_FAIL_BACKOFF_MS,
// so a bus that fails every other read cannot hold the loop. the bus is called stuck when most of the
// failures were time-outs (a missing acknowledge is a chip that does not answer).
#define EXPANDER_FAIL_LIMIT       3
#define EXPANDER_FAIL_WINDOW_MS   10000UL
#define EXPANDER_FAIL_BACKOFF_MS  1000UL
// a chip that has run this long without being called down gets the short retry again. one that keeps
// dropping out carries on from the back-off it had reached.
#define EXPANDER_STABLE_MS        30000UL
// a rail is ok only from a reading no older than this. while the chip is not running and trusted, before
// the first reading has settled or when the last good one is older, a watched rail is posted stale.
#define EXPANDER_FRESH_MS         2000UL
// the sensor rail is called present only while a cable sensor has answered within this long. a pass is
// 5 s, so this is a little over two. a note that it is not proven up is made after this long without one.
#define EXPANDER_SENSOR_FRESH_MS  12000UL
#define EXPANDER_SENS_PROOF_MS    15000UL
// a chip that stopped answering is tried again after this long, doubling up to the cap.
#define EXPANDER_RETRY_START_MS   1000UL
#define EXPANDER_RETRY_MAX_MS     30000UL
// the time between two samples that a debounce is credited for. a pass that holds the loop longer
// than this is credited only this much, so a long block never makes a short glitch look long.
#define EXPANDER_MAX_CREDIT_MS    100UL
// a lone failed read is written to the serial monitor at most this often. it is always counted.
#define EXPANDER_LONE_LOG_MS      60000UL
// after the sensor rail is switched back on, SENS_OK has to read high on two polls in a row within this
// long of the bus coming back or the rail is reported missing. nothing waits for it: it is judged on
// the polls the loop makes anyway. the switch gate settles in about 10 ms.
#define SENSOR_RAIL_RETURN_LIMIT_MS 300UL

// a resolved address is kept this long, so a healthy network costs no lookups
#define DNS_CACHE_MS             600000UL

// ─── OTA ──────────────────────────────────────────────────────────────────────
// the update path in ota.ino fetches over plain HTTP, compares only a version number and checks
// no signature, so anyone who can answer the hub's request can have it flash any image. it is off
// and it stays off. it cannot even be switched on without the bench flag below. before it is ever
// turned on all of this has to exist: TLS with the pinned roots for the version and the image,
// images signed offline with the public key compiled in, the signature and the hash checked
// before the image is activated, the version inside the signed data and rollback confirmed only
// after the first good post. see "Firmware updates over the air" in README.md.
#ifndef OTA_ENABLED
#define OTA_ENABLED             0
#endif
#if OTA_ENABLED
// the update code cannot be part of a release build in any form
#if PHAEMOS_RELEASE
#error "PHAEMOS_RELEASE and OTA_ENABLED together: a release build never carries the unsigned update path"
#endif
#ifndef OTA_UNSIGNED_BENCH_ONLY
#error "OTA_ENABLED is 1 but nothing verifies an image. add -DOTA_UNSIGNED_BENCH_ONLY=1 only on an isolated bench network and read the OTA section of README.md first"
#endif
#if !USE_COMPILED_SECRETS
#error "OTA_ENABLED needs USE_COMPILED_SECRETS (the update code reads API_BASE_URL and DEVICE_API_KEY at build time)"
#endif
// the update code uses the core's HTTPClient, which for an https:// address calls setInsecure()
// when it is given no certificate (HTTPClient.cpp in the pinned core). an https:// base address
// there would look safe and verify nothing, so the update path is allowed on a bench with plain HTTP
// only and is honest about it. the hub's own post path never calls setInsecure().
#if !ALLOW_PLAIN_HTTP
#error "OTA_ENABLED needs ALLOW_PLAIN_HTTP: the update code does no certificate checking, so it is a plain HTTP path whatever the address says"
#endif
#ifndef API_BASE_URL
#error "OTA_ENABLED needs API_BASE_URL in secrets.h"
#endif
static_assert(cfgStarts(API_BASE_URL, "http://") || cfgStarts(API_BASE_URL, "https://"),
              "API_BASE_URL must start with http:// or https://");
static_assert(!cfgStarts(API_BASE_URL, "http://your-backend-url") && !cfgStarts(API_BASE_URL, "https://your-backend-url"),
              "secrets.h still has the placeholder API_BASE_URL");
#endif
// the one place the firmware version lives. OTA compares it with the backend's.
#define FIRMWARE_VERSION        "1.0.0"

// ─── Fault reporting and watchdog ─────────────────────────────────────────────
// an I2C or 1-wire sensor is reported missing only after this many failed probes in a row.
#define HEALTH_MISSING_CONFIRM  3
// three failed probes inside this window that never reach three in a row are reported as
// intermittent, so readings that come and go always come with a reason.
#define HEALTH_FLAP_WINDOW_MS   60000UL
// a set-up that has to run again is tried at most this often per sensor, so a part that
// flaps cannot hold the loop with repeated set-up calls.
#define REINIT_MIN_INTERVAL_MS  10000
// the hub's own BME280 or BMP280 is called stuck when its raw data words repeat this many reads
// in a row (24 reads of 5 s is 2 minutes). the part is read at oversampling x16 for temperature and
// pressure (the Adafruit defaults, 20 bit words), so its own noise always moves the low bits and a
// repeat of 24 is not credible from a working part. the same reasoning as the Nano's test.
#define BME_STUCK_READS         24
// a BME280 or MLX90614 that keeps returning an impossible reading is set up again after this many passes.
#define CONTENT_REINIT_PASSES       3
// the post runs in its own task, so the main loop never waits on the network. the main loop
// reads, judges, drives the display and relays and feeds its watchdog on a fixed
// TELEMETRY_INTERVAL_MS timer. its worst legitimate pass is about 3 s: the I2C reads
// (VL53L0X ranging, the 20 ms microphone window) plus a burst of set-ups after a power dip
// (each up to about a second) or a stuck bus (about 50 ms per Wire transaction). 10 s is
// more than three times that.
#define WDT_TIMEOUT_S           10
// the watchdog is armed in the hub core's boot, straight after the relay pins are driven low,
// with this longer timeout and fed between the stages, so a library call that never returns
// during sensor set-up ends in a reset. most stages take a few seconds. the VL53L0X's bounded
// polls can take about 10 s on a bus where every transaction times out. the post task does the Wi-Fi connect and OTA.
// the sensor whose set-up was running is written to RTC memory first, so after that reset
// it is skipped (see SETUP_MAX_STRIKES).
#define WDT_SETUP_TIMEOUT_S     15
// the ESP-IDF task watchdog has one timeout for every task it watches, so the post task is
// supervised by the main loop instead. the main loop feeds the watchdog only while the post
// task is healthy: not busy for longer than POST_BUSY_LIMIT_MS (the whole post has a wall-clock
// limit of POST_WALL_CLOCK_MS that the task enforces itself (20 s). the pinned core's DNS wait
// of up to 15 s counts against it, so 30 s leaves 10 s for the one blocking step the limit
// cannot interrupt) and beating at least every POST_IDLE_LIMIT_MS
// while it is idle or backing off. an OTA download suspends this supervision for at most
// POST_OTA_PAUSE_LIMIT_MS, so a download that hangs cannot leave the hub silent for ever.
#define POST_BUSY_LIMIT_MS      30000UL
#define POST_IDLE_LIMIT_MS      10000UL
#define POST_OTA_PAUSE_LIMIT_MS 300000UL
// the panel shows a fault when no post has succeeded for this long (and since boot).
#define POST_STALE_MS           300000UL
// after a failed post the task waits this long, doubling on each further failure up to the
// cap and starting again after a success. newer bodies replace the unsent one meanwhile.
#define POST_BACKOFF_START_MS   5000UL
#define POST_BACKOFF_MAX_MS     60000UL
// a 401 or 403 means the key is wrong and retrying will not fix it, so the next attempt waits
// this long and not the back-off. the panel shows NET meanwhile.
#define POST_AUTH_RETRY_MS      600000UL
// a 429 waits at least as long as the server's Retry-After, capped at one hour.
#define POST_RETRY_AFTER_MAX_MS 3600000UL
// the post task runs on core 0 beside the Wi-Fi and TCP/IP tasks, so core 1 stays with the
// main loop. its stack must hold the socket client and the OTA updater. the high-water mark is
// printed on the serial monitor after the first post and every 60 posts.
#define POST_TASK_CORE          0
#define POST_TASK_PRIORITY      1
// 12,288 bytes. the core's own HTTPS examples run the mbedTLS handshake on the Arduino loop task,
// whose stack is CONFIG_ARDUINO_LOOP_STACK_SIZE = 8192 in the pinned core's sdkconfig and our
// client adds a request header buffer and the String copies on top of that.
#define POST_TASK_STACK_BYTES   12288
// the serial receive buffers hold several lines, so a long pass never drops bytes. the
// pinned core's default is 256 bytes, which is two Black Pill lines.
#define UART_RX_BUFFER_BYTES    2048
// serialised telemetry must fit this many bytes. a body that would not fit is counted as
// a failed post and never sent cut short.
// the revised board's faults map can hold eight more entries (the expander and seven rails), about 190
// bytes with every one set, so its limit is 256 bytes higher. the present board's is unchanged.
#if HAS_EXPANDER
#define TELEMETRY_BODY_MAX_BYTES 2304
#else
#define TELEMETRY_BODY_MAX_BYTES 2048
#endif
// ArduinoJson pool for the document. it holds every field, the full faults map and the
// links object. test_host/worst_json.cpp measures the worst case against both limits.
// the revised board can also fault the expander and the seven rails, which are eight more entries in
// the faults map (about 20 bytes each), so its pool is 256 bytes larger. the present board's is unchanged.
#if HAS_EXPANDER
#define TELEMETRY_DOC_BYTES     3328
#else
#define TELEMETRY_DOC_BYTES     3072
#endif

// ─── Safety against bad temperature readings ──────────────────────────────────
// the BME280 is specified from -40 to 85 degC. a failed read can come back as
// about 180 degC, so anything outside the range is rejected.
#define BME_TEMP_MIN_C          -40.0
#define BME_TEMP_MAX_C          85.0
// a part that passes its register checks and reads between BME_TEMP_MAX_C and this is hot, not
// dead, so the reading counts as over-temperature for the cooling relay. anything above is junk.
#define BME_TEMP_OVERRANGE_MAX_C 125.0
// what the other two temperature parts can report. a reading outside is a fault.
#define MLX_TEMP_MIN_C          -70.0
#define MLX_TEMP_MAX_C          380.0
#define DS18_TEMP_MIN_C         -55.0
#define DS18_TEMP_MAX_C         125.0
// a DS18B20 that has reset holds 85.0 degC until its first conversion ends. an exact 85.0
// that is not within DS18_POWER_ON_NEAR_C of the previous reading is that value, not a
// temperature.
#define DS18_POWER_ON_C         85.0f
#define DS18_POWER_ON_NEAR_C    5.0f
// switch the cooling relay on only after this many critical readings in a row.
#define CRITICAL_CONFIRM_READINGS 3
// a reading has to fall this far below a threshold before its status clears.
#define TEMP_HYSTERESIS_C       2.0

// ─── Link quality ─────────────────────────────────────────────────────────────
// a link is reported as intermittent when more than a fifth of the lines expected in the
// last LINK_RATE_WINDOW_MS were lost (a sequence gap) or failed a check, once at least
// LINK_RATE_MIN_LINES were expected so one glitch on a quiet link is not enough.
#define LINK_RATE_WINDOW_MS     60000UL
#define LINK_RATE_MIN_LINES     8

// ─── Reset recovery ───────────────────────────────────────────────────────────
// after a warm reset (watchdog, panic or software) the cooling relay is put back as it was,
// with the per-source critical counts and latches. the restored relay is dropped again unless a
// trusted temperature reading confirms the state within this time.
#define RELAY_RESTORE_CONFIRM_MS 10000UL
// every warm reset that follows a run in which no trusted temperature reading arrived is
// counted, whatever the relay was doing. after this many in a row (a reset loop) the hub stops
// restoring and puts the cooling relay in its state for no information instead. the count is
// cleared by the first trusted reading.
#define RESTORE_MAX_UNCONFIRMED  2
// the cooling relay's state when the hub has no information: a reset loop or no trusted
// temperature source after a restore was refused. 1 is on, which is the safe side for a cooling
// output (the fan or valve runs when it was not needed). set it to 0 only where the cooling
// load must not run unattended or the hardware does not tolerate it running continuously.
#define COOLING_RELAY_NO_INFO_ON 1
// a sensor whose set-up was running at the moment of a warm reset is skipped for that boot.
// after this many such resets it stays out until the next power-up.
#define SETUP_MAX_STRIKES        2
// a strike is forgiven once the sensor has completed a set-up and given good readings for this
// long, so two unrelated resets far apart cannot lock a healthy sensor out until power-up. a
// strike is only given for a task watchdog reset, which is what a stalled set-up ends in.
#define SETUP_FORGIVE_MS         600000UL
// the board check at boot: the revised board is recognised by its MCP23017. it is probed this
// many times, this far apart, after the sensor rail has had time to settle and only a bus that
// is known to work can say the expander is absent. any doubt means GPIO14 is not driven.
#define BOARD_PROBE_TRIES        5
#define BOARD_PROBE_GAP_MS       20

// ─── Shaft sampling ───────────────────────────────────────────────────────────
// 20 ms keeps a 1500 RPM shaft under half a turn per sample, so RPM does not alias.
#define AS5600_SAMPLE_MS        20
// a gap between two samples longer than this is not trusted, because a fast shaft could have
// turned more than half a turn in it. the movement and the time of that gap are both left out
// of the rpm, so a blocked loop cannot make the rpm read low.
#define AS5600_MAX_GAP_MS       40
// a window with samples covering less than this share of its length gives no rpm.
#define AS5600_MIN_COVERAGE_PCT 50

// ─── Alert thresholds ─────────────────────────────────────────────────────────
// set conservative thresholds here; real-world calibration should tighten them.
#define TEMP_WARNING_C          40.0
#define TEMP_CRITICAL_C         60.0
// the DS18B20 contact probe and the MLX90614 object temperature back the BME280 up for the
// critical state. each counts when it is trusted and over its own threshold. they start at the
// BME280's value. a contact probe or an infrared spot on a hot part of a machine may need a
// higher value, so tune them on the machine.
#define TEMP_CRITICAL_DS18_C    60.0
#define TEMP_CRITICAL_MLX_C     60.0

// ─── Water alarm ──────────────────────────────────────────────────────────────
// the alarm is raised when the probe reads under this many counts (12 bit, 11 dB, 0 to 4095).
// it is worked out and NOT measured, so the water alarm is UNPROVEN until it has been
// measured on a real probe. the arithmetic, from hardware/wiring/esp32_pinout.md and the
// Nano's wiring note:
//   the Nano wiring note puts a probe in water at 300 to 400 of 1023 on its 5 V circuit, which
//   is 29 to 39 per cent of the supply. the Nano alarms under 500 of 1023 (49 per cent).
//   the probe and its pull-up form a divider, so the ratios carry over to the hub's 3.3 V.
//   in water   0.29 to 0.39 x 3.3 V = 0.96 to 1.29 V, about 1270 to 1700 counts
//   Nano equivalent threshold 0.49 x 3.3 V = 1.61 V, about 2130 counts
//   damp       about 1.65 to 2.3 V, about 2180 to 3040 counts
//   dry        about 3.0 V, about 3950 counts
//   unplugged  present board: floating, anything. revised board: 0 V, about 0 counts
//   (the counts use about 1320 counts per volt, the ADC's full scale of 4095 at about 3.1 V)
// 2000 sits under the Nano's equivalent, about 300 counts above the top of the in-water band
// and below the damp band. the old value of 500 (0.4 V) was on the wrong scale.
#define WATER_THRESHOLD         2000
// 0 until the threshold has been measured on a real probe. while it is 0 the hub says at boot,
// on the display and on the serial monitor, that the water alarm is unproven.
#define WATER_ALARM_PROVEN      0
