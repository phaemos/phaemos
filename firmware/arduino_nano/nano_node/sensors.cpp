// sensors.cpp - Sensor driver implementations for the Arduino Nano node
//
// return a struct from readBME280Nano rather than output params because the
// Nano has enough SRAM for small structs and it makes the main sketch more
// readable - one named return value beats three pointer arguments at the
// call site.

#include "sensors.h"
#include <Wire.h>
#include <string.h>

// pin that powers the FC-28 through the board's solder jumper.
// the probe is only powered while it is read because a continuous DC bias
// electrolyses the electrodes and corrodes them.  driving the pin is
// harmless when the jumper selects the fixed 5 V rail instead.
static const uint8_t MOISTURE_POWER_PIN = 7;

// time for the probe and the 100 k pull-up to settle after power is applied
// and before the ADC samples, found by allowing several RC time constants.
static const unsigned long MOISTURE_SETTLE_MS = 50UL;

// how long to wait before probing again after a failed start.  a slow retry
// picks up a sensor that is plugged in late without flooding the I2C bus.
static const unsigned long BME_RETRY_INTERVAL_MS = 30000UL;

// consecutive failed or not-ready reads before the sensor is treated as gone.
// a short run is tolerated so one noisy transfer does not force a re-probe.
static const uint8_t BME_MAX_FAILED_READS = 3;

// reads in a row with every raw value byte-identical before the sensor is called stuck.
// 60 reads is 120 s.  pressure is read at oversampling x16, which gives the raw pressure word its full
// 20 bit resolution (0.16 Pa a count) and about 8 counts of the converter's own noise at the data sheet
// figure of 1.3 Pa, so a working part breaks a run of identical words on nearly every read.  at
// oversampling x1 the word has only 16 bits and a quiet part can repeat it.  the emulation sweeps the
// noise down to a twentieth of the data sheet figure and reports the longest identical run it sees
// against this limit (see sim/README.md).  120 s is still short enough to flag a frozen converter
// within a couple of minutes.  all values are compared together
// because one channel alone can sit on a value for minutes in steady conditions (temperature in a
// room with the heating off) while a frozen converter freezes every channel at once.
static const uint8_t BME_STUCK_READS = 60;

// after the part falls asleep twice within this many reads it is flapping and the bit is held for
// the next BME_ASLEEP_HOLD_READS lines.  one repaired sleep shows on one line only, which the hub
// treats as a glitch, but a part that keeps resetting must show on consecutive lines to be seen.
static const uint8_t BME_ASLEEP_REPEAT_READS = 10;
static const uint8_t BME_ASLEEP_HOLD_READS   = 5;

// the set-up the firmware writes and reads back each cycle.  temperature and pressure
// pressure oversampling x16 and temperature oversampling x2 (the data sheet's ultra high resolution
// setting) in normal mode, humidity oversampling x1 and the filter off with 0.5 ms standby.
// ctrl_meas is 010 (T x2), 101 (P x16) and 11 (normal) = 0x57.  the longest conversion from the data
// sheet is 43.2 ms on a BMP280 and 1.25 + 2.3 * 2 + (2.3 * 16 + 0.575) + (2.3 * 1 + 0.575) = 46.1 ms on a
// BME280.  with 0.5 ms of standby the part converts about 21 times a second, so the 2 second
// report always finds a fresh result and nothing waits on the part except the first read after set-up.
static const uint8_t CTRL_HUM_VALUE  = 0x01;
static const uint8_t CTRL_MEAS_VALUE = 0x57;
static const unsigned long FIRST_CONVERSION_WAIT_MS = 50UL;   // above the 46.1 ms longest conversion
static const uint8_t CONFIG_VALUE    = 0x00;

// soft reset of the sensor: writing 0xB6 to register 0xE0.  the data sheet gives a 2 ms start-up
// time, so 3 ms is waited before the set-up is written again.
static const uint8_t  REG_RESET_CMD   = 0xB6;
static const unsigned long RESET_STARTUP_MS = 3UL;

// data sheet range of the compensated values, used for the BME_RANGE bit.  temperature is in
// hundredths of a degree and pressure in pascals, the units the integer compensation returns.
static const int32_t RANGE_T_MIN_CENTI = -4000;
static const int32_t RANGE_T_MAX_CENTI = 8500;
static const int32_t RANGE_P_MIN_PA    = 30000L;
static const int32_t RANGE_P_MAX_PA    = 110000L;
static const int32_t RANGE_H_MAX_Q22   = 419430400L;  // 100 %RH as the Q22.10 value, where the output is clamped
// a working part in condensing air can compute a little over 100 per cent, so the bit is only set
// when the value before the clamp is under -5 or over 105 per cent (1 per cent is 4194304).
static const int32_t RANGE_H_MIN_Q22_BAD = -20971520L;
static const int32_t RANGE_H_MAX_Q22_BAD = 440401920L;

// nominal value of the internal band gap reference.  it varies by about 10 per cent between
// chips (1.0 V to 1.2 V in the data sheet) so VCC is only as good as this number.  measure
// one board against a meter and replace it to calibrate.
static const uint32_t BANDGAP_MV_NOMINAL = 1100UL;

// the band gap needs a short time to settle after it is selected as the ADC input.
static const unsigned long BANDGAP_SETTLE_MS = 2UL;

// chip IDs from the Bosch datasheets, read from register 0xD0.
static const uint8_t CHIP_ID_BMP280 = 0x58;
static const uint8_t CHIP_ID_BME280 = 0x60;

// register map shared by both parts.
static const uint8_t REG_CALIB_TP   = 0x88;  // 24 bytes of T and P calibration
static const uint8_t REG_CALIB_H1   = 0xA1;
static const uint8_t REG_ID         = 0xD0;
static const uint8_t REG_CALIB_H2   = 0xE1;  // 7 bytes of H2..H6 calibration
static const uint8_t REG_RESET      = 0xE0;
static const uint8_t REG_CTRL_HUM   = 0xF2;  // BME280 only
static const uint8_t REG_CTRL_MEAS  = 0xF4;
static const uint8_t REG_CONFIG     = 0xF5;
static const uint8_t REG_DATA       = 0xF7;

// a raw sample of 0x80000 means the part has not produced a result yet.
static const int32_t RAW_NOT_READY = 0x80000;

// a small direct driver is used instead of the Adafruit libraries because
// the BME280 library rejects the BMP280 chip ID and shipping both libraries
// would cost several kilobytes of the Nano's 30 kB flash.
static uint8_t  i2c_addr      = 0;
static bool     bme_initialised = false;
static bool     is_bme280     = false;
static unsigned long last_probe_ms = 0;
static uint8_t  failed_reads  = 0;

// stuck-data detection: the last raw bytes, how many reads in a row matched them and whether
// the one soft reset allowed in this stuck episode has been spent.
static uint8_t  prev_raw[8];
static bool     have_prev_raw = false;
static uint8_t  identical_reads = 0;
static bool     soft_reset_tried = false;

// flapping detection for BME_ASLEEP: reads since the last sleep and lines still to hold.
static uint8_t  reads_since_asleep = 255;
static uint8_t  asleep_hold = 0;

static uint16_t dig_T1, dig_P1;
static int16_t  dig_T2, dig_T3;
static int16_t  dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;
static uint8_t  dig_H1, dig_H3;
static int16_t  dig_H2, dig_H4, dig_H5;
static int8_t   dig_H6;

// a stuck bus makes the Wire timeout fire (see setup in nano_node.ino).
// report it as a failure and clear the flag so the next transfer can try again.
static bool busTimedOut() {
    if (Wire.getWireTimeoutFlag()) {
        Wire.clearWireTimeoutFlag();
        return true;
    }
    return false;
}

static bool readRegs(uint8_t reg, uint8_t *buf, uint8_t len) {
    Wire.beginTransmission(i2c_addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) {
        busTimedOut();
        return false;
    }
    if (Wire.requestFrom(i2c_addr, len) != len) {
        busTimedOut();
        return false;
    }
    for (uint8_t i = 0; i < len; i++) {
        buf[i] = Wire.read();
    }
    return !busTimedOut();
}

// returns true only when the sensor acknowledged the write.
static bool writeReg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(i2c_addr);
    Wire.write(reg);
    Wire.write(value);
    uint8_t status = Wire.endTransmission();
    return status == 0 && !busTimedOut();
}

static uint16_t le16(const uint8_t *b) {
    return (uint16_t)b[0] | ((uint16_t)b[1] << 8);
}

// forget the stuck-data history, used whenever the sensor has been re-set or re-found so that
// a stale comparison can never count towards a stuck verdict.
static void clearStuckHistory() {
    have_prev_raw = false;
    identical_reads = 0;
    soft_reset_tried = false;
}

// write the set-up the firmware depends on.  humidity oversampling must be written before
// ctrl_meas because ctrl_hum only takes effect after a write to ctrl_meas.
static bool configureSensor() {
    if (is_bme280 && !writeReg(REG_CTRL_HUM, CTRL_HUM_VALUE)) {
        return false;
    }
    return writeReg(REG_CONFIG, CONFIG_VALUE) && writeReg(REG_CTRL_MEAS, CTRL_MEAS_VALUE);
}

static bool identifyAndLoad(uint8_t addr);

// probe one address and, when a known chip answers, load its calibration and
// start continuous measurement.
static bool beginAt(uint8_t addr) {
    clearStuckHistory();
    reads_since_asleep = 255;
    asleep_hold = 0;
    return identifyAndLoad(addr) && configureSensor();
}

// read the chip id and the calibration from the part at addr.  this is run again whenever the
// set-up is rewritten, so a part that was swapped for another one never keeps the old calibration
// or the old chip type.
static bool identifyAndLoad(uint8_t addr) {
    i2c_addr = addr;

    uint8_t id;
    if (!readRegs(REG_ID, &id, 1)) {
        return false;
    }
    if (id != CHIP_ID_BME280 && id != CHIP_ID_BMP280) {
        return false;
    }
    is_bme280 = (id == CHIP_ID_BME280);

    uint8_t c[24];
    if (!readRegs(REG_CALIB_TP, c, 24)) {
        return false;
    }
    dig_T1 = le16(&c[0]);
    dig_T2 = (int16_t)le16(&c[2]);
    dig_T3 = (int16_t)le16(&c[4]);
    dig_P1 = le16(&c[6]);
    dig_P2 = (int16_t)le16(&c[8]);
    dig_P3 = (int16_t)le16(&c[10]);
    dig_P4 = (int16_t)le16(&c[12]);
    dig_P5 = (int16_t)le16(&c[14]);
    dig_P6 = (int16_t)le16(&c[16]);
    dig_P7 = (int16_t)le16(&c[18]);
    dig_P8 = (int16_t)le16(&c[20]);
    dig_P9 = (int16_t)le16(&c[22]);

    if (is_bme280) {
        uint8_t h[7];
        if (!readRegs(REG_CALIB_H1, &dig_H1, 1) || !readRegs(REG_CALIB_H2, h, 7)) {
            return false;
        }
        dig_H2 = (int16_t)le16(&h[0]);
        dig_H3 = h[2];
        // H4 and H5 share the nibbles of register 0xE5.
        dig_H4 = (int16_t)(((int8_t)h[3] << 4) | (h[4] & 0x0F));
        dig_H5 = (int16_t)(((int8_t)h[5] << 4) | (h[4] >> 4));
        dig_H6 = (int8_t)h[6];
    }

    return true;
}

// initBME280Nano - Probe 0x76, fall back to 0x77.
// try 0x76 first because it is the more common default (SDO=GND on most
// Chinese breakout boards).  Falling back to 0x77 means the firmware works
// without modification on boards where SDO is pulled high.
void initBME280Nano() {
    // keep the moisture probe unpowered between reads.
    pinMode(MOISTURE_POWER_PIN, OUTPUT);
    digitalWrite(MOISTURE_POWER_PIN, LOW);

    last_probe_ms = millis();
    failed_reads = 0;
    bme_initialised = beginAt(0x76) || beginAt(0x77);
    if (bme_initialised) {
        // allow the first conversion to finish so the first report is real.
        delay(FIRST_CONVERSION_WAIT_MS);
    }
}

// readBME280Nano - Read temperature, pressure and (BME280 only) humidity.
// a sensor that resets or is re-plugged mid-session loses its configuration,
// so after BME_MAX_FAILED_READS failed or not-ready reads in a row the sensor
// is marked absent and the slow probe in this function picks it up again.
static void noteFailedRead() {
    if (++failed_reads >= BME_MAX_FAILED_READS) {
        bme_initialised = false;
        last_probe_ms = millis();
        failed_reads = 0;
    }
}

// give the part a soft reset and write the set-up again.  this is the only repair the node can
// attempt on a converter that has frozen.  the calibration lives in non-volatile memory on the
// part and survives the reset, but the identity and calibration are read again anyway so that a
// part swapped for another one is never used with the old numbers.
static void softResetSensor() {
    writeReg(REG_RESET, REG_RESET_CMD);
    delay(RESET_STARTUP_MS);
    identifyAndLoad(i2c_addr);
    configureSensor();
}

// read the control registers back and say whether they hold what the firmware wrote.  a part
// whose registers fell back to their power-on values keeps answering in sleep mode and never
// converts again, which the data registers alone cannot show.  *ok is false when the transfer
// itself failed.
static bool controlRegistersGood(bool *ok) {
    uint8_t ctrl_hum = CTRL_HUM_VALUE;
    uint8_t ctrl_meas;
    *ok = false;
    if (is_bme280) {
        uint8_t c[3];   // 0xF2 ctrl_hum, 0xF3 status and 0xF4 ctrl_meas
        if (!readRegs(REG_CTRL_HUM, c, 3)) {
            return false;
        }
        ctrl_hum = c[0];
        ctrl_meas = c[2];
    } else if (!readRegs(REG_CTRL_MEAS, &ctrl_meas, 1)) {
        return false;
    }
    *ok = true;
    return ctrl_meas == CTRL_MEAS_VALUE && ctrl_hum == CTRL_HUM_VALUE;
}

BME280Data readBME280Nano() {
    BME280Data result;
    result.temperature  = -1.0f;
    result.humidity     = -1.0f;
    result.pressure     = -1.0f;
    result.ok           = false;
    result.has_humidity = false;
    result.status       = ST_BME_MISSING;

    if (!bme_initialised) {
        // unsigned subtraction stays correct across the millis() rollover.
        if (millis() - last_probe_ms >= BME_RETRY_INTERVAL_MS) {
            initBME280Nano();
        }
        if (!bme_initialised) {
            return result;
        }
    }

    // the control registers are read in their own transfer and not in one burst with the data.
    // the data registers are only guaranteed to be consistent when a burst starts at 0xF7.
    bool transfer_ok;
    if (!controlRegistersGood(&transfer_ok)) {
        if (!transfer_ok) {
            noteFailedRead();
            return result;
        }
        // the part answers but is not converting.  read its identity and calibration again and
        // write the set-up at once, then discard this cycle.  the part may have been swapped for
        // another one, which resets the same registers.  this is not a failed read: the sensor is
        // there, so it is not dropped.  the old data and the comparison history are stale, so both
        // are forgotten.
        bool back = identifyAndLoad(i2c_addr) && configureSensor();
        clearStuckHistory();
        if (!back) {
            noteFailedRead();
            return result;
        }
        if (reads_since_asleep < BME_ASLEEP_REPEAT_READS) {
            asleep_hold = BME_ASLEEP_HOLD_READS;   // second sleep in a short time: flapping
        }
        reads_since_asleep = 0;
        result.status = ST_BME_ASLEEP;
        return result;
    }
    if (reads_since_asleep < 255) {
        reads_since_asleep++;
    }
    if (asleep_hold > 0) {
        // keep reporting the flapping part for a few lines, with no values, so the bit shows on
        // consecutive lines.
        asleep_hold--;
        clearStuckHistory();
        result.status = ST_BME_ASLEEP;
        return result;
    }

    uint8_t d[8];
    uint8_t len = is_bme280 ? 8 : 6;
    if (!readRegs(REG_DATA, d, len)) {
        noteFailedRead();
        return result;
    }

    int32_t adc_P = ((int32_t)d[0] << 12) | ((int32_t)d[1] << 4) | (d[2] >> 4);
    int32_t adc_T = ((int32_t)d[3] << 12) | ((int32_t)d[4] << 4) | (d[5] >> 4);
    if (adc_P == RAW_NOT_READY || adc_T == RAW_NOT_READY) {
        noteFailedRead();
        return result;
    }

    // from here the sensor is answering and converting, so the missing bit is not set.
    result.status = 0;

    // count the reads whose raw bytes (temperature, pressure and humidity together) match the
    // read before.  see BME_STUCK_READS for why 60 and why every value is compared.
    if (have_prev_raw && memcmp(prev_raw, d, len) == 0) {
        if (identical_reads < 255) {
            identical_reads++;
        }
    } else {
        memcpy(prev_raw, d, len);
        have_prev_raw = true;
        identical_reads = 1;
        soft_reset_tried = false;   // the data moved, so the next episode may try a reset again
    }
    if (identical_reads >= BME_STUCK_READS) {
        result.status |= ST_BME_STUCK;
        if (!soft_reset_tried) {
            soft_reset_tried = true;   // once per stuck episode, then only report
            softResetSensor();
        }
        failed_reads = 0;
        return result;
    }

    // integer compensation from the Bosch datasheets.  it avoids pulling in
    // 64-bit maths that the 8-bit AVR core handles slowly and in more flash.
    int32_t var1 = (((adc_T >> 3) - ((int32_t)dig_T1 << 1)) * (int32_t)dig_T2) >> 11;
    int32_t var2 = (((((adc_T >> 4) - (int32_t)dig_T1) * ((adc_T >> 4) - (int32_t)dig_T1)) >> 12)
                    * (int32_t)dig_T3) >> 14;
    int32_t t_fine = var1 + var2;
    int32_t t_centi = (t_fine * 5 + 128) >> 8;

    var1 = (t_fine >> 1) - 64000;
    var2 = (((var1 >> 2) * (var1 >> 2)) >> 11) * (int32_t)dig_P6;
    var2 = var2 + ((var1 * (int32_t)dig_P5) << 1);
    var2 = (var2 >> 2) + ((int32_t)dig_P4 << 16);
    var1 = ((((int32_t)dig_P3 * (((var1 >> 2) * (var1 >> 2)) >> 13)) >> 3)
            + (((int32_t)dig_P2 * var1) >> 1)) >> 18;
    var1 = ((32768 + var1) * (int32_t)dig_P1) >> 15;
    if (var1 == 0) {
        result.status = ST_BME_RANGE;   // a zero divisor means the raw word cannot be a real pressure
        return result;
    }
    uint32_t p = (((uint32_t)(((int32_t)1048576) - adc_P) - (uint32_t)(var2 >> 12))) * 3125;
    if (p < 0x80000000UL) {
        p = (p << 1) / (uint32_t)var1;
    } else {
        p = (p / (uint32_t)var1) * 2;
    }
    var1 = ((int32_t)dig_P9 * ((int32_t)(((p >> 3) * (p >> 3)) >> 13))) >> 12;
    var2 = ((int32_t)(p >> 2) * (int32_t)dig_P8) >> 13;
    p = (uint32_t)((int32_t)p + ((var1 + var2 + (int32_t)dig_P7) >> 4));

    bool in_range = t_centi >= RANGE_T_MIN_CENTI && t_centi <= RANGE_T_MAX_CENTI
                    && p >= (uint32_t)RANGE_P_MIN_PA && p <= (uint32_t)RANGE_P_MAX_PA;

    float humidity = -1.0f;
    if (is_bme280) {
        int32_t adc_H = ((int32_t)d[6] << 8) | d[7];
        int32_t v = t_fine - 76800;
        v = (((((adc_H << 14) - ((int32_t)dig_H4 << 20) - ((int32_t)dig_H5 * v)) + 16384) >> 15)
             * (((((((v * (int32_t)dig_H6) >> 10) * (((v * (int32_t)dig_H3) >> 11) + 32768)) >> 10)
                  + 2097152) * (int32_t)dig_H2 + 8192) >> 14));
        v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)dig_H1) >> 4);
        // the data sheet clamps here.  the range check looks before the clamp, because a
        // clamped value always passes it and would hide an impossible reading.  the printed value is
        // still clamped to 0 to 100 inside the allowed band.
        if (v < RANGE_H_MIN_Q22_BAD || v > RANGE_H_MAX_Q22_BAD) {
            in_range = false;
        }
        if (v < 0) {
            v = 0;
        }
        if (v > RANGE_H_MAX_Q22) {
            v = RANGE_H_MAX_Q22;
        }
        humidity = (v >> 12) / 1024.0f;  // Q22.10 -> %RH
    }

    failed_reads = 0;
    if (!in_range) {
        // impossible values never leave the node as readings.
        result.status = ST_BME_RANGE;
        return result;
    }

    result.temperature = t_centi / 100.0f;
    result.pressure    = p / 100.0f;  // Pa -> hPa
    if (is_bme280) {
        result.humidity     = humidity;
        result.has_humidity = true;
    }
    result.ok = true;
    return result;
}

// one ADC conversion, started and waited for directly.
static uint16_t adcConvert() {
    ADCSRA |= _BV(ADSC);
    while (ADCSRA & _BV(ADSC)) {
    }
    return ADC;
}

// read one analogue pin.  the first conversion after the multiplexer changes is thrown away
// because the sample and hold capacitor still carries the charge of the previous input,
// which matters on a high impedance source such as the LDR divider or the moisture probe.
static int readAdcChannel(uint8_t pin) {
    analogRead(pin);
    return analogRead(pin);
}

// readSupplyMv - Measure the supply against the internal band gap.
// the band gap is the ADC input and AVcc is the reference, so the result is 1.1 V * 1024 / VCC
// counts and the supply follows from it.  the reference stays AVcc, which is what analogRead
// uses, so only the multiplexer needs putting back.  the first conversion after each switch is
// discarded here after selecting the band gap. readAdcChannel does the same after the next pin
// is selected, so nothing ever reads a value taken just after a switch.
uint16_t readSupplyMv() {
    const uint8_t saved_admux = ADMUX;
    ADMUX = _BV(REFS0) | 0x0E;   // AVcc reference and the 1.1 V band gap as the input
    delay(BANDGAP_SETTLE_MS);
    adcConvert();                // discarded
    // keep converting until two results in a row agree within one count, up to five more times.  the
    // band gap may still be settling after the switch and this costs under half a millisecond.
    uint16_t counts = adcConvert();
    for (uint8_t i = 0; i < 5; i++) {
        uint16_t again = adcConvert();
        bool agree = again + 1 >= counts && counts + 1 >= again;
        counts = again;
        if (agree) {
            break;
        }
    }
    ADMUX = saved_admux;
    if (counts == 0) {
        return 0;
    }
    return (uint16_t)((BANDGAP_MV_NOMINAL * 1024UL) / counts);
}

// readLDRNano - Read LDR ADC value from pin A0.
// one discarded conversion and one used one rather than an average of many
// samples, because the main loop already runs every 2 seconds, giving the ADC input
// capacitance enough time to settle between reads.
int readLDRNano() {
    return readAdcChannel(A0);
}

// readMoisture - Read FC-28 moisture sensor ADC value from pin A1.
// the FC-28 is a resistive sensor: low ADC value = low resistance = high
// moisture.  The reading is not inverted here so the raw value is always
// available to the caller for calibration or logging purposes.  the probe is
// powered only for the duration of the read.  an unplugged sensor reads high
// (dry) because of the board's 100 k pull-up.
int readMoisture() {
    digitalWrite(MOISTURE_POWER_PIN, HIGH);
    delay(MOISTURE_SETTLE_MS);
    int value = readAdcChannel(A1);
    digitalWrite(MOISTURE_POWER_PIN, LOW);
    return value;
}

// isWaterDetected - Returns true when moisture ADC value indicates wet soil.
// use a threshold of 500 because with a 5V supply and the FC-28's typical
// resistance range, values below ~500 correspond to the sensor being partially
// submerged.  Lower threshold = more sensitive to moisture; higher = less.
bool isWaterDetected(int moisture) {
    return moisture < 500;
}
