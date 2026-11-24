/* bme280_sim.c - register level model of a Bosch BME280 or BMP280 on the simavr TWI bus.
 *
 * calibration and raw values:
 *   the temperature and pressure calibration words (dig_T1..T3 and dig_P1..P9) and the raw
 *   readings adc_T = 519888 and adc_P = 415148 are the worked example in Bosch's BMP280 data
 *   sheet (BST-BMP280-DS001, section 3.12 "Calculating pressure and temperature").  with the
 *   data sheet's compensation formulae they give 25.08 degrees C and 100653 Pa.  the BME280
 *   uses the same compensation for temperature and pressure (BST-BME280-DS002, section 4.2.3).
 *   the data sheets publish no worked humidity example, so the humidity words below
 *   (dig_H1..H6) are values chosen for the model, not measured from any part and adc_H is a mid-range raw
 *   value.  the harness derives the expected humidity from the data sheet formula.
 *
 * register behaviour follows BST-BME280-DS002 section 5.3 (memory map) and 6.2 (I2C).
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "avr_twi.h"
#include "bme280_sim.h"

const int32_t BME_EXAMPLE_RAW_T = 519888;
const int32_t BME_EXAMPLE_RAW_P = 415148;
const int32_t BME_EXAMPLE_RAW_H = 29000;
/* the pressure word the model starts from: the nearest 16 bit word to the data sheet example that puts
 * the printed pressure (1006.6 hPa) in the middle of its rounding band, so one count of noise either way
 * does not change the printed digit.  the data sheet example itself is still used to check the maths. */
const int32_t BME_NOMINAL_RAW_P = 415120;

/* the longest conversion time follows the oversampling the part is set to (data sheet formula, BST-BME280-DS001 9.1):
 * 1.25 + 2.3 * T_os + (2.3 * P_os + 0.575) + (2.3 * H_os + 0.575) ms, with the humidity term only on a BME280.  at pressure x16
 * and temperature x2 that is 43.2 ms without humidity (the BMP280 data sheet's table 13) and 46.1 ms with humidity x1.
 * data before this read as "not measured yet". */
static int os_from_code(int code) { return code == 0 ? 0 : code >= 5 ? 16 : 1 << (code - 1); }
static double conversion_ms(const bme280_sim_t *b)
{
    int ot = os_from_code((b->ctrl_meas >> 5) & 7), op = os_from_code((b->ctrl_meas >> 2) & 7);
    double ms = 1.25;
    if (ot) ms += 2.3 * ot;
    if (op) ms += 2.3 * op + 0.575;
    if (b->chip_id == 0x60 && (b->ctrl_hum & 7)) ms += 2.3 * os_from_code(b->ctrl_hum & 7) + 0.575;
    return ms;
}
#define CONVERSION_MS conversion_ms(b)

#define REG_ID        0xD0
#define REG_RESET     0xE0
#define REG_CTRL_HUM  0xF2
#define REG_STATUS    0xF3
#define REG_CTRL_MEAS 0xF4
#define REG_CONFIG    0xF5
#define REG_DATA      0xF7

const bme_calib_t BME_CALIB = {
    .T1 = 27504, .T2 = 26435, .T3 = -1000,
    .P1 = 36477, .P2 = -10685, .P3 = 3024, .P4 = 2855, .P5 = 140,
    .P6 = -7, .P7 = 15500, .P8 = -14600, .P9 = 6000,
    /* humidity words are chosen for the model: they are not from the data sheet and not measured from any part */
    .H1 = 75, .H2 = 366, .H3 = 0, .H4 = 311, .H5 = 50, .H6 = 30,
};

/* a second set of calibration words for the swapped-part scenario: a different module has its own */
const bme_calib_t BME_CALIB_ALT = {
    .T1 = 27300, .T2 = 26000, .T3 = -1050,
    .P1 = 36477, .P2 = -10600, .P3 = 3024, .P4 = 2855, .P5 = 140,
    .P6 = -7, .P7 = 15500, .P8 = -14600, .P9 = 6000,
    .H1 = 75, .H2 = 366, .H3 = 0, .H4 = 311, .H5 = 50, .H6 = 30,
};

static uint8_t calib_tp[2][24];  /* 0x88..0x9F, one set per module */
static uint8_t calib_h1[2];      /* 0xA1 */
static uint8_t calib_h[2][7];    /* 0xE1..0xE7 */

static void put16(uint8_t *p, uint16_t v) { p[0] = v & 0xFF; p[1] = v >> 8; }

static void build_set(int k, const bme_calib_t *c)
{
    put16(&calib_tp[k][0], c->T1);
    put16(&calib_tp[k][2], (uint16_t)c->T2);
    put16(&calib_tp[k][4], (uint16_t)c->T3);
    put16(&calib_tp[k][6], c->P1);
    put16(&calib_tp[k][8], (uint16_t)c->P2);
    put16(&calib_tp[k][10], (uint16_t)c->P3);
    put16(&calib_tp[k][12], (uint16_t)c->P4);
    put16(&calib_tp[k][14], (uint16_t)c->P5);
    put16(&calib_tp[k][16], (uint16_t)c->P6);
    put16(&calib_tp[k][18], (uint16_t)c->P7);
    put16(&calib_tp[k][20], (uint16_t)c->P8);
    put16(&calib_tp[k][22], (uint16_t)c->P9);
    calib_h1[k] = c->H1;
    put16(&calib_h[k][0], (uint16_t)c->H2);
    calib_h[k][2] = c->H3;
    /* dig_H4 and dig_H5 are 12 bit values that share register 0xE5 (data sheet table 16) */
    calib_h[k][3] = (uint8_t)((c->H4 >> 4) & 0xFF);                             /* 0xE4 */
    calib_h[k][4] = (uint8_t)((c->H4 & 0x0F) | ((c->H5 & 0x0F) << 4));          /* 0xE5 */
    calib_h[k][5] = (uint8_t)((c->H5 >> 4) & 0xFF);                             /* 0xE6 */
    calib_h[k][6] = (uint8_t)c->H6;                                             /* 0xE7 */
}

static void build_calibration(void)
{
    build_set(0, &BME_CALIB);
    build_set(1, &BME_CALIB_ALT);
}

double bme_now_ms(const bme280_sim_t *b)
{
    return (double)b->avr->cycle * 1000.0 / (double)b->avr->frequency;
}

/* a number from a bell curve (sum of twelve uniform values minus six), from the model's fixed seed */
static double gauss(bme280_sim_t *b)
{
    double a = 0;
    for (int i = 0; i < 12; i++) {
        b->jitter_state = b->jitter_state * 1664525u + 1013904223u;
        a += (double)(b->jitter_state >> 8) / 16777216.0;
    }
    return a - 6.0;
}

/* what the part returns for the oversampling it is set to, from the data sheets (BST-BMP280-DS001-26 tables 4, 5, 8 and 9 and
 * BST-BME280-DS001-23 tables 11 and 12, filter off).  the figures were read from those PDFs and are not guesses, but they are
 * typical values: a particular part may be quieter or noisier.
 *   osrs code             1 (x1)   2 (x2)   3 (x4)   4 (x8)   5 (x16)
 *   pressure resolution   2.62 Pa  1.31 Pa  0.66 Pa  0.33 Pa  0.16 Pa     16 + (code - 1) bits, 20 at most
 *   pressure noise rms    3.3 Pa   2.6 Pa   2.1 Pa   1.6 Pa   1.3 Pa
 *   temperature resolution 0.0050  0.0025   0.0012   0.0006   0.0003 C   16 + (code - 1) bits
 *   temperature noise rms 0.005    0.004    0.003    0.003    0.002 C     (BMP280 table 9. the BME280 sheet gives only the x1 figure)
 *   humidity (x1)         16 bit, 0.008 %RH a count, noise 0.07 %RH rms (BME280 table 11)
 * the noise in counts is the noise figure divided by the resolution. */
static const double P_RES_PA[6]  = {0, 2.62, 1.31, 0.66, 0.33, 0.16};
static const double P_NOISE_PA[6] = {0, 3.3, 2.6, 2.1, 1.6, 1.3};
static const double T_RES_C[6]   = {0, 0.0050, 0.0025, 0.0012, 0.0006, 0.0003};
static const double T_NOISE_C[6] = {0, 0.005, 0.004, 0.003, 0.003, 0.002};
#define H_RES_PCT   0.008
#define H_NOISE_PCT 0.07

/* the code (1 to 5) a field of ctrl_meas holds, with every value from 5 up meaning x16 */
static int code_of(int field) { return field == 0 ? 1 : field > 5 ? 5 : field; }

static void pack_raw(bme280_sim_t *b)
{
    int32_t t = b->raw_t, p = b->raw_p, h = b->raw_h;
    if (b->drift_on) {
        double s = (bme_now_ms(b) - b->drift_t0_ms) / 1000.0;
        t += (int32_t)(s * b->drift_t);
        p += (int32_t)(s * b->drift_p);
    }
    /* the resolution the oversampling gives: the words are 20 bit values whose low bits are zero below 20 bit resolution */
    int cp = code_of((b->ctrl_meas >> 2) & 7), ct = code_of((b->ctrl_meas >> 5) & 7);
    int shift_p = 5 - cp, shift_t = 5 - ct;   /* zero low bits: 4 at x1 (16 bit), 0 at x16 (20 bit) */
    int32_t step_p = 1 << shift_p, step_t = 1 << shift_t;
    if (b->replay_n > 0) {
        /* raw words logged from a real part, one line per conversion: P T H, 20 bit and 20 bit and 16 bit */
        const int32_t *w = &b->replay[3 * (b->replay_pos % b->replay_n)];
        p = w[0]; t = w[1]; h = w[2];
        b->replay_pos++;
    } else if (b->noise_mode == NOISE_GAUSS) {
        double sp = P_NOISE_PA[cp] / P_RES_PA[cp], st = T_NOISE_C[ct] / T_RES_C[ct], sh = H_NOISE_PCT / H_RES_PCT;   /* counts of each word */
        p = (int32_t)lrint((double)p / step_p + gauss(b) * sp * b->noise_scale) * step_p;
        t = (int32_t)lrint((double)t / step_t + gauss(b) * st * b->noise_scale) * step_t;
        if (b->chip_id == 0x60) h = (int32_t)lrint((double)h + gauss(b) * sh * b->noise_scale);   /* a BMP280 has no humidity */
    } else {
        p = ((p + step_p / 2) >> shift_p) << shift_p;
        t = ((t + step_t / 2) >> shift_t) << shift_t;
        if (b->noise_mode == NOISE_DITHER) {
            /* a count of noise either way (at least 8 counts of the 20 bit word, a bit over 1 Pa), small enough to leave the
             * printed digits of the nominal reading alone so the exact-text checks of the other scenarios hold */
            static const int d[4] = {-1, 0, 0, 1};
            b->jitter_state = b->jitter_state * 1664525u + 1013904223u;
            p += (step_p > 8 ? step_p : 8) * d[(b->jitter_state >> 16) & 3];
            b->jitter_state = b->jitter_state * 1664525u + 1013904223u;
            t += (step_t > 8 ? step_t : 8) * d[(b->jitter_state >> 16) & 3];
        }
    }
    uint8_t old[8];
    int nbytes = b->chip_id == 0x60 ? 8 : 6;   /* a BMP280 firmware reads six bytes, so only those can count as a change */
    memcpy(old, b->data, 8);
    b->data[0] = (p >> 12) & 0xFF;
    b->data[1] = (p >> 4) & 0xFF;
    b->data[2] = (p & 0x0F) << 4;
    b->data[3] = (t >> 12) & 0xFF;
    b->data[4] = (t >> 4) & 0xFF;
    b->data[5] = (t & 0x0F) << 4;
    b->data[6] = (h >> 8) & 0xFF;
    b->data[7] = h & 0xFF;
    /* statistics for the still room scenarios: how often the raw bytes changed and the longest unchanged run */
    b->n_raw_packs++;
    if (memcmp(old, b->data, (size_t)nbytes) != 0) { b->n_raw_changes++; b->same_run = 1; } else { b->same_run++; }
    if (b->same_run > b->longest_same_run) b->longest_same_run = b->same_run;
}

/* power-on values of the data registers: 0x80000 for pressure and temperature and 0x8000
 * for humidity (data sheet 5.3 memory map, "skipped" output). */
static void data_not_measured(bme280_sim_t *b)
{
    static const uint8_t sk[8] = {0x80, 0x00, 0x00, 0x80, 0x00, 0x00, 0x80, 0x00};
    memcpy(b->data, sk, 8);
}

/* a mode change restarts the conversion clock.  mode bits are ctrl_meas [1:0]:
 * 00 sleep, 01 or 10 forced and 11 normal. */
static void update_measurement(bme280_sim_t *b)
{
    uint8_t mode = b->ctrl_meas & 0x03;
    double since = (double)(b->avr->cycle - b->mode_since) * 1000.0 / (double)b->avr->frequency;
    if (b->frozen_until_reset) return;   /* a frozen converter: the registers keep their last values */
    if (mode == 0x03) {
        if (since >= CONVERSION_MS) pack_raw(b);   /* normal mode keeps refreshing */
    } else if (mode != 0x00 && !b->measuring_done && since >= CONVERSION_MS) {
        pack_raw(b);                               /* forced: one conversion, then sleep */
        b->measuring_done = 1;
        b->ctrl_meas &= ~0x03;
    }
    /* sleep mode: the data registers hold whatever they held */
}

static int is_bme280(const bme280_sim_t *b) { return b->chip_id == 0x60; }

static uint8_t reg_read(bme280_sim_t *b, uint8_t reg)
{
    if (b->pending_sleep && (reg == REG_CTRL_HUM || reg == REG_CTRL_MEAS)) {
        b->pending_sleep = 0;
        bme_reset_control_only(b);   /* the part fell asleep since the last read: its set-up is gone */
    }
    if (reg == REG_DATA) {
        update_measurement(b);   /* refresh once per burst so the bytes match */
        if (b->sleep_every && ++b->data_reads % b->sleep_every == 0) b->pending_sleep = 1;
    }
    if (reg >= 0x88 && reg <= 0x9F) return calib_tp[b->calib_set][reg - 0x88];
    if (reg == REG_ID) return b->chip_id;
    if (is_bme280(b)) {
        if (reg == 0xA1) return calib_h1[b->calib_set];
        if (reg >= 0xE1 && reg <= 0xE7) return calib_h[b->calib_set][reg - 0xE1];
        if (reg == REG_CTRL_HUM) return b->ctrl_hum;
        if (reg == 0xFD || reg == 0xFE) return b->data[6 + (reg - 0xFD)];
    }
    if (reg == REG_STATUS) {
        uint8_t mode = b->ctrl_meas & 0x03;
        double since = (double)(b->avr->cycle - b->mode_since) * 1000.0 / (double)b->avr->frequency;
        return (mode != 0 && since < CONVERSION_MS) ? 0x08 : 0x00;  /* bit 3 is "measuring" */
    }
    if (reg == REG_CTRL_MEAS) return b->ctrl_meas;
    if (reg == REG_CONFIG) return b->config;
    if (reg >= REG_DATA && reg <= 0xFC) return b->data[reg - REG_DATA];
    return 0x00;
}

void bme_power_on_reset(bme280_sim_t *b)
{
    b->ctrl_hum = b->ctrl_hum_shadow = 0;
    b->ctrl_meas = 0;
    b->config = 0;
    b->mode_since = b->avr->cycle;
    b->measuring_done = 0;
    data_not_measured(b);
}

void bme_reset_control_only(bme280_sim_t *b)
{
    b->ctrl_hum = b->ctrl_hum_shadow = 0;
    b->ctrl_meas = 0;      /* sleep mode: the part stops converting and keeps its last data */
    b->config = 0;
    b->mode_since = b->avr->cycle;
    b->measuring_done = 1;
}

static void reg_write(bme280_sim_t *b, uint8_t reg, uint8_t v)
{
    switch (reg) {
    case REG_RESET:
        if (v == 0xB6) {
            b->n_soft_resets++;
            b->frozen_until_reset = 0;
            bme_power_on_reset(b);
        }
        break;
    case REG_CTRL_HUM:
        if (is_bme280(b)) b->ctrl_hum_shadow = v;   /* takes effect after a ctrl_meas write */
        break;
    case REG_CTRL_MEAS:
        b->n_ctrl_meas_writes++;
        b->ctrl_hum = b->ctrl_hum_shadow;
        b->mode_since = b->avr->cycle;   /* every write restarts the conversion clock */
        b->measuring_done = 0;
        b->ctrl_meas = v;
        break;
    case REG_CONFIG:
        b->config = v;
        break;
    default:
        break;  /* read-only or reserved: ignored, as on the part */
    }
}

static void answer(bme280_sim_t *b, uint8_t msg, uint8_t addr, uint8_t data)
{
    avr_raise_irq(b->irq + TWI_IRQ_INPUT, avr_twi_irq_msg(msg, addr, data));
}

static void bme_hook(struct avr_irq_t *irq, uint32_t value, void *param)
{
    (void)irq;
    bme280_sim_t *b = param;
    avr_twi_msg_irq_t v;
    v.u.v = value;

    if (b->bus != BUS_NORMAL) {
        /* a silent or hung part says nothing, so the AVR sees no acknowledge */
        if (v.u.twi.msg & TWI_COND_START) b->n_starts_ignored++;
        return;
    }

    if (v.u.twi.msg & TWI_COND_STOP) {
        b->selected = 0;
        b->index = 0;
        b->write_phase = 0;
    }
    if (v.u.twi.msg & TWI_COND_START) {
        b->selected = 0;
        b->index = 0;
        b->write_phase = 0;
        /* the simavr address byte carries the read or write bit in bit 0 */
        if ((v.u.twi.addr >> 1) == b->addr7) {
            b->selected = v.u.twi.addr;
            b->n_starts_acked++;
            answer(b, TWI_COND_ACK, b->selected, 1);
        } else {
            b->n_starts_other++;   /* a probe of the other address: nothing answers */
        }
    }
    if (!b->selected) return;

    if (v.u.twi.msg & TWI_COND_WRITE) {
        answer(b, TWI_COND_ACK, b->selected, 1);
        /* bytes arrive as register address then data, repeated (data sheet 6.2.1) */
        if (!b->write_phase) {
            b->reg_ptr = v.u.twi.data;
            b->write_phase = 1;
        } else {
            reg_write(b, b->reg_ptr, v.u.twi.data);
            b->n_writes++;
            b->write_phase = 0;
        }
        b->index++;
    }
    if (v.u.twi.msg & TWI_COND_READ) {
        /* reads auto-increment the register pointer and wrap at 0xFF */
        uint8_t d = reg_read(b, b->reg_ptr++);
        b->n_reads++;
        answer(b, TWI_COND_READ, b->selected, d);
        b->index++;
    }
}

static const char *irq_names[2] = {
    [TWI_IRQ_INPUT] = "8>bme.out",
    [TWI_IRQ_OUTPUT] = "32<bme.in",
};

void bme_init(bme280_sim_t *b, avr_t *avr, uint8_t addr7, uint8_t chip_id)
{
    build_calibration();
    memset(b, 0, sizeof(*b));
    b->avr = avr;
    b->addr7 = addr7;
    b->chip_id = chip_id;
    b->bus = BUS_NORMAL;
    b->raw_t = BME_EXAMPLE_RAW_T;
    b->raw_p = BME_NOMINAL_RAW_P;
    b->raw_h = BME_EXAMPLE_RAW_H;
    /* a real part never returns exactly the same words for minutes: the noise at x1 oversampling moves
     * them by a count or two.  by default the model dithers by one count, small
     * enough to leave the printed digits alone.  a constant value would be indistinguishable from a
     * frozen converter and the firmware would rightly call it stuck.  the still room scenarios use
     * the data sheet noise instead. */
    b->noise_mode = NOISE_DITHER;
    b->noise_scale = 1.0;
    bme_power_on_reset(b);
    b->irq = avr_alloc_irq(&avr->irq_pool, 0, 2, irq_names);
    avr_irq_register_notify(b->irq + TWI_IRQ_OUTPUT, bme_hook, b);
}

void bme_attach(bme280_sim_t *b)
{
    avr_connect_irq(b->irq + TWI_IRQ_INPUT, avr_io_getirq(b->avr, AVR_IOCTL_TWI_GETIRQ(0), TWI_IRQ_INPUT));
    avr_connect_irq(avr_io_getirq(b->avr, AVR_IOCTL_TWI_GETIRQ(0), TWI_IRQ_OUTPUT), b->irq + TWI_IRQ_OUTPUT);
}

void bme_set_raw(bme280_sim_t *b, int32_t t, int32_t p, int32_t h)
{
    b->raw_t = t; b->raw_p = p; b->raw_h = h;
}

void bme_freeze(bme280_sim_t *b)
{
    if (b->drift_on) {
        double s = (bme_now_ms(b) - b->drift_t0_ms) / 1000.0;
        b->raw_t += (int32_t)(s * b->drift_t);
        b->raw_p += (int32_t)(s * b->drift_p);
        b->drift_on = 0;
    }
}

/* the part is swapped for another module (its own chip id and calibration) with its registers at power-on values */
void bme_swap(bme280_sim_t *b, uint8_t chip_id, int calib_set)
{
    b->chip_id = chip_id;
    b->calib_set = calib_set;
    b->frozen_until_reset = 0;
    bme_power_on_reset(b);
}

/* replay raw words logged from a real part: a text file with three whole numbers per line, the 20 bit
 * pressure word then the 20 bit temperature word then the 16 bit humidity word, one line per conversion.
 * the file is played in order and wraps.  returns the number of conversions loaded or -1. */
int bme_load_replay(bme280_sim_t *b, const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    int cap = 1024, n = 0;
    int32_t *w = malloc(sizeof(int32_t) * 3 * (size_t)cap);
    long p, t, h;
    while (w && fscanf(f, "%ld %ld %ld", &p, &t, &h) == 3) {
        if (n == cap) { cap *= 2; w = realloc(w, sizeof(int32_t) * 3 * (size_t)cap); if (!w) break; }
        w[3 * n] = (int32_t)p; w[3 * n + 1] = (int32_t)t; w[3 * n + 2] = (int32_t)h; n++;
    }
    fclose(f);
    if (!w || n == 0) { free(w); return -1; }
    b->replay = w; b->replay_n = n; b->replay_pos = 0;
    return n;
}

/* the longest conversion at the oversampling the part is now set to, for the harness to report */
double bme_conversion_ms(const bme280_sim_t *b) { return conversion_ms(b); }
