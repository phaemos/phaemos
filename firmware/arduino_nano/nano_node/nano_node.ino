// nano_node.ino - Arduino Nano secondary node main sketch
//
// reads a BME280 or BMP280, LDR and FC-28 moisture sensor.
// outputs one line every 2 seconds over Serial at 9600 baud and answers a ping from the hub.
//
// the line is KEY:value pairs joined by commas, then *CCCC (CRC-16/CCITT-FALSE of everything
// before the star) and CR LF.  CSV over Serial is used rather than JSON or a binary protocol because:
//   - It needs no library on either end: Serial.print() on the Nano and a small
//     hand-written parser on the ESP32.
//   - Each field has a named prefix (TEMP:, HUM:, etc.) so the ESP32 can
//     parse individual fields without caring about field order, making the
//     format resilient to future additions.
//   - Baud rate 9600 keeps the signal clean over long duplex wires (>10 cm)
//     to the ESP32, where higher baud rates can introduce framing errors
//     without proper shielding.
//
// example output:
//   TEMP:25.1,HUM:50.7,PRES:1006.6,LIGHT:300,MOIST:700,WATER:0,ST:0,SEQ:12,UP:26,VCC:4980*F6B1
//   TEMP:-1,HUM:-1,PRES:-1,LIGHT:512,MOIST:301,WATER:1,ST:1,SEQ:13,UP:28,VCC:4979*AFBC   <- no sensor
//   TEMP:28.5,HUM:-1,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0,ST:0,SEQ:14,UP:30,VCC:4980*8157   <- BMP280
// the ping PING:1234 is answered with PONG:1234*EBBB.

#include <Wire.h>
#include <avr/io.h>
#include <avr/wdt.h>
#include "linkframe.h"
#include "sensors.h"

// use a named constant for the interval rather than a magic number so it
// is easy to adjust during testing without hunting through the loop() body.
static const unsigned long REPORT_INTERVAL_MS = 2000UL;

// a line is at most 160 bytes with its CR LF, set by the link contract.  the same buffer builds
// the data line and the pong so the RAM cost is paid once.
static const size_t LINE_MAX = 160;

// the supply window that sets SUPPLY_RANGE.  a Nano on USB or a regulator sits near 5 V.  the band
// gap behind VCC varies by about 10 per cent between chips, which is as wide as the 4500 to 5500 window,
// so until a board is calibrated (BANDGAP_CALIBRATED set to 1 at build time) the window is wider and
// only a rail that has really gone sets the bit.  VCC itself is always printed as measured.
#ifndef BANDGAP_CALIBRATED
#define BANDGAP_CALIBRATED 0
#endif
#if BANDGAP_CALIBRATED
static const uint16_t VCC_MIN_MV = 4500;
static const uint16_t VCC_MAX_MV = 5500;
#else
static const uint16_t VCC_MIN_MV = 4000;
static const uint16_t VCC_MAX_MV = 6000;
#endif

// the longest ping the hub sends is "PING:65535" plus a CR.  anything that fills the buffer is
// not a ping, so the buffer is cleared and the rest of that line is skipped.
static const uint8_t RX_MAX = 12;

// the reset cause is read before main() so that nothing, not even the Arduino start-up code,
// can disturb it.  .init3 runs after the stack is set up and before main().  the variables sit
// in .noinit so the C start-up code does not zero them.  the function is naked because there is no
// stack frame to build this early.  MCUSR is cleared afterwards because a watchdog reset flag
// that is left set keeps the watchdog enabled on this chip family.
//
// the new bootloader (Optiboot 4.4) reads MCUSR, writes zero to it and starts the sketch without
// passing the value on, so the sketch reads 0 on every start there.  to tell a restart that kept
// power from a power-up in that case the sketch writes a marker into .noinit once it is running
// and this function checks and clears it.  RAM that still holds the marker means the node was
// restarted without losing power.  the marker is a 32 bit magic number and its complement, 8 bytes
// that a RAM full of noise, zeros or ones after a power loss will not match by chance.  a power dip
// short enough not to clear RAM looks the same as a restart that kept power.
uint8_t  reset_flags    __attribute__((section(".noinit")));
uint8_t  warm_start     __attribute__((section(".noinit")));
uint32_t run_magic      __attribute__((section(".noinit")));
uint32_t run_magic_inv  __attribute__((section(".noinit")));
static const uint32_t RUN_MAGIC = 0x5A17C0DEUL;
void early_init(void) __attribute__((naked, used, section(".init3")));
void early_init(void) {
    reset_flags = MCUSR;
    MCUSR = 0;
    warm_start = (run_magic == RUN_MAGIC && run_magic_inv == ~RUN_MAGIC) ? 1 : 0;
    run_magic = 0;
    run_magic_inv = 0;
#ifdef NANO_WATCHDOG
    // the watchdog survives a reset with its old settings, so it is stopped before anything
    // slow runs.  setup() turns it on again once start-up is done.
    wdt_disable();
#endif
}

// fixed buffer that builds one line.  it derives from Print so the numbers are formatted by the
// same code as before and the output is byte for byte what Serial.print gave.  nothing here
// allocates.  a line that would not fit is marked and never sent.
class LineBuffer : public Print {
public:
    void reset() { len_ = 0; overflow_ = false; }
    size_t write(uint8_t c) override {
        if (len_ >= LINE_MAX - 8) {   // room is kept for *CCCC and CR LF
            overflow_ = true;
            return 0;
        }
        buf_[len_++] = (char)c;
        return 1;
    }
    // add the checksum of everything so far, then CR LF.
    void seal() {
        uint16_t crc = link_crc16((const uint8_t *)buf_, len_);
        buf_[len_++] = '*';
        link_hex4(crc, &buf_[len_]);
        len_ += 4;
        buf_[len_++] = '\r';
        buf_[len_++] = '\n';
    }
    // sends the line unless it overflowed.
    void send() {
        if (!overflow_) {
            Serial.write((const uint8_t *)buf_, len_);
        }
    }
private:
    char    buf_[LINE_MAX];
    size_t  len_ = 0;
    bool    overflow_ = false;
};
static LineBuffer line;

// track the last report time with millis() rather than delay() so the
// Nano's CPU is not blocked during the 2-second window - useful when adding
// interrupt-driven sensor features later.
static unsigned long last_report_ms = 0;

// data lines sent since boot.  it wraps at 65535 and a pong does not move it.
static uint16_t seq = 0;

// whole seconds since boot.  millis() wraps after 49 days, so the seconds are accumulated
// from the elapsed time on every pass of loop() and keep counting.  each pass is far shorter
// than the wrap, so the unsigned subtraction is always right.
static unsigned long uptime_s = 0;
static unsigned long uptime_rem_ms = 0;
static unsigned long uptime_last_ms = 0;

// status bits that hold for the whole boot, from the reset cause.
static uint8_t boot_status = 0;

static char    rx_buf[RX_MAX];
static uint8_t rx_len = 0;
static bool    rx_skip = false;

static void updateUptime() {
    unsigned long now = millis();
    uptime_rem_ms += now - uptime_last_ms;
    uptime_last_ms = now;
    while (uptime_rem_ms >= 1000UL) {
        uptime_rem_ms -= 1000UL;
        uptime_s++;
    }
}

// answer PING:<n> with PONG:<n>*CCCC.  the line must be exactly the word, a colon and one to
// five digits that make a number up to 65535.  anything else is ignored without a word.
static void handleLine(const char *s, uint8_t len) {
    static const char word[] = "PING:";
    if (len > 0 && s[len - 1] == '\r') {
        len--;
    }
    if (len < 6 || len > 10) {
        return;
    }
    for (uint8_t i = 0; i < 5; i++) {
        if (s[i] != word[i]) {
            return;
        }
    }
    unsigned long n = 0;
    for (uint8_t i = 5; i < len; i++) {
        if (s[i] < '0' || s[i] > '9') {
            return;
        }
        n = n * 10 + (unsigned long)(s[i] - '0');
    }
    if (n > 65535UL) {
        return;
    }
    line.reset();
    line.print(F("PONG:"));
    line.print((unsigned int)n);
    line.seal();
    line.send();
}

// read whatever has arrived without waiting for more.  Serial.available() is zero when nothing
// is waiting, so this returns at once on a quiet link.
static void pollSerial() {
    while (Serial.available() > 0) {
        int c = Serial.read();
        if (c < 0) {
            return;
        }
        if (c == '\n') {
            if (!rx_skip) {
                handleLine(rx_buf, rx_len);
            }
            rx_len = 0;
            rx_skip = false;
        } else if (rx_skip) {
            // the rest of an over-long line is thrown away up to its end.
        } else if (rx_len < RX_MAX) {
            rx_buf[rx_len++] = (char)c;
        } else {
            rx_len = 0;     // buffer full: clear it and skip to the end of the line
            rx_skip = true;
        }
    }
}

void setup() {
    // initialise Serial before Wire so any I2C errors during initBME280Nano
    // can be observed on the serial monitor during bring-up.
    Serial.begin(9600);
    Wire.begin();
    // without a timeout Wire blocks for ever when SDA or SCL is stuck low,
    // which would also stop the light and moisture readings.  25 ms is far
    // longer than any normal transfer at 100 kHz.
    Wire.setWireTimeout(25000, true);
    initBME280Nano();

    // a watchdog flag wins.  a brown-out is the brown-out flag with the power-on flag clear, because a
    // normal power-up sets both.  where the bootloader cleared the flags the marker decides and only
    // the watchdog build reports it: there a restart that kept its RAM is a watchdog reset, the
    // reset line or a brown-out that kept RAM and the node has no way to tell which.
    if (reset_flags & _BV(WDRF)) {
        boot_status |= ST_RESET_WATCHDOG;
    } else if ((reset_flags & _BV(BORF)) && !(reset_flags & _BV(PORF))) {
        boot_status |= ST_RESET_BROWNOUT;
    }
#ifdef NANO_WATCHDOG
    else if (reset_flags == 0 && warm_start) {
        boot_status |= ST_RESET_WATCHDOG;
    }
#endif
    uptime_last_ms = millis();

#ifdef NANO_WATCHDOG
    // longest legitimate pass of loop() is about 0.35 s (see the README), so 8 s leaves a wide
    // margin and only a real hang trips it.
    wdt_enable(WDTO_8S);
#endif
    // from here a reset that keeps power finds this marker.  it is written last so a start that
    // never gets this far is not mistaken for a warm one.
    run_magic = RUN_MAGIC;
    run_magic_inv = ~RUN_MAGIC;
}

void loop() {
#ifdef NANO_WATCHDOG
    wdt_reset();    // once per pass: a pass that never ends lets the watchdog bite
#endif
    updateUptime();
    pollSerial();

    unsigned long now = millis();

    // use (now - last_report_ms) rather than comparing to a target time
    // to handle millis() overflow gracefully - unsigned subtraction wraps
    // correctly at the 49-day rollover boundary.
    if (now - last_report_ms >= REPORT_INTERVAL_MS) {
        last_report_ms = now;

        BME280Data bme   = readBME280Nano();
        int        light = readLDRNano();
        int        moist = readMoisture();
        int        water = isWaterDetected(moist) ? 1 : 0;
        uint16_t   vcc   = readSupplyMv();
        updateUptime();

        uint8_t st = bme.status | boot_status;
        if (vcc < VCC_MIN_MV || vcc > VCC_MAX_MV) {
            st |= ST_SUPPLY_RANGE;
        }

        line.reset();
        if (bme.ok) {
            // normal path: all sensors healthy
            line.print(F("TEMP:"));
            line.print(bme.temperature, 1);
            // a BMP280 has no humidity element so report the sentinel.
            line.print(F(",HUM:"));
            if (bme.has_humidity) {
                line.print(bme.humidity, 1);
            } else {
                line.print(-1);
            }
            line.print(F(",PRES:"));
            line.print(bme.pressure, 1);
        } else {
            // sensor missing, asleep, stuck or out of range - send sentinel values so the
            // upstream ESP32 parser can flag a sensor fault without crashing.  ST says which.
            // use -1 rather than 0 because 0 is a plausible real temperature
            // and would be harder to distinguish from a valid reading.
            line.print(F("TEMP:-1,HUM:-1,PRES:-1"));
        }
        line.print(F(",LIGHT:"));
        line.print(light);
        line.print(F(",MOIST:"));
        line.print(moist);
        line.print(F(",WATER:"));
        line.print(water);
        line.print(F(",ST:"));
        line.print((unsigned int)st);
        line.print(F(",SEQ:"));
        line.print(seq);
        line.print(F(",UP:"));
        line.print(uptime_s);
        line.print(F(",VCC:"));
        line.print(vcc);
        line.seal();    // adds *CCCC and the CR LF the ESP32 uses as a line delimiter
        line.send();
        seq++;
    }
}
