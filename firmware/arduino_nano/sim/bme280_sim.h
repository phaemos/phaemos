/* bme280_sim.h - register level model of a Bosch BME280 or BMP280 on the simavr TWI bus.
 *
 * the part is written the same way as simavr's own i2c_eeprom: it listens on the
 * TWI output irq of the AVR and answers on the TWI input irq.
 */
#ifndef BME280_SIM_H
#define BME280_SIM_H

#include <stdint.h>
#include "sim_avr.h"
#include "sim_irq.h"

/* what the part does on the wire.  the register contents are independent of this. */
typedef enum {
    BUS_NORMAL = 0,  /* acknowledges its address and serves registers */
    BUS_SILENT,      /* dead part: never acknowledges, the master sees a NACK */
    BUS_HUNG         /* data line held low: the master never gets an interrupt at all */
} bme_bus_t;

/* how the raw words are noisy.  all of them return 16 bit words (the low four bits of the 20 bit value zero). */
enum { NOISE_NONE = 0, NOISE_DITHER = 1, NOISE_GAUSS = 2 };

typedef struct bme280_sim {
    avr_t     *avr;
    avr_irq_t *irq;

    /* wire level state */
    uint8_t   addr7;        /* 0x76 or 0x77 */
    bme_bus_t bus;

    /* chip identity: 0x60 is a BME280 and 0x58 a BMP280 */
    uint8_t   chip_id;

    /* registers the firmware can write */
    uint8_t   ctrl_hum;       /* 0xF2, latched into effect by a write to 0xF4 */
    uint8_t   ctrl_hum_shadow;
    uint8_t   ctrl_meas;      /* 0xF4 */
    uint8_t   config;         /* 0xF5 */

    /* measurement model */
    uint8_t   data[8];        /* 0xF7..0xFE as last latched */
    avr_cycle_count_t mode_since;  /* cycle at which the part entered its present mode */
    int       measuring_done; /* a first conversion has completed since the mode was set */

    /* raw ADC values the "environment" produces */
    int32_t   raw_t, raw_p, raw_h;
    int32_t   drift_t, drift_p;      /* raw counts added per simulated second while drift is on */
    int       drift_on;
    double    drift_t0_ms;           /* when the drift started, for a stable value */
    int       noise_mode;            /* NOISE_NONE, NOISE_DITHER or NOISE_GAUSS */
    double    noise_scale;           /* with NOISE_GAUSS: 1.0 is the data sheet noise, 0.1 a tenth of it */
    uint32_t  jitter_state;          /* fixed seed so a run repeats exactly */
    int       calib_set;             /* which module's calibration the registers show: 0 or 1 (BME_CALIB_ALT) */
    unsigned  sleep_every;           /* the part falls asleep after every Nth data read (0 for never) */
    unsigned  data_reads;
    int       pending_sleep;
    int32_t  *replay;                /* raw words from a logged file, see bme_load_replay */
    int       replay_n, replay_pos;
    int       frozen_until_reset;    /* the data registers stop updating until a soft reset (0xB6 to 0xE0) */

    /* transaction state */
    int       selected;
    int       index;
    uint8_t   reg_ptr;
    int       write_phase;     /* 0 expects a register address and 1 expects data */

    /* statistics for the scenarios */
    unsigned  n_starts_acked, n_starts_ignored, n_starts_other, n_reads, n_writes;
    unsigned  n_ctrl_meas_writes;
    unsigned  n_soft_resets;
    unsigned  n_raw_packs, n_raw_changes, longest_same_run, same_run;   /* conversions, how many changed the raw bytes and the longest unchanged run */
} bme280_sim_t;

void bme_init(bme280_sim_t *b, avr_t *avr, uint8_t addr7, uint8_t chip_id);
void bme_attach(bme280_sim_t *b);
/* stop the drift and keep the value it had reached, as a frozen converter would */
void bme_freeze(bme280_sim_t *b);
/* brown-out: every register returns to its power-on value, calibration survives (NVM). */
void bme_power_on_reset(bme280_sim_t *b);
/* the control registers only go back to their power-on values.  the last data stay. */
void bme_reset_control_only(bme280_sim_t *b);
void bme_set_raw(bme280_sim_t *b, int32_t t, int32_t p, int32_t h);
double bme_now_ms(const bme280_sim_t *b);
double bme_conversion_ms(const bme280_sim_t *b);

/* calibration words, one source of truth for the register bytes and the host reference maths */
typedef struct {
    uint16_t T1; int16_t T2, T3;
    uint16_t P1; int16_t P2, P3, P4, P5, P6, P7, P8, P9;
    uint8_t  H1; int16_t H2; uint8_t H3; int16_t H4, H5; int8_t H6;
} bme_calib_t;
extern const bme_calib_t BME_CALIB;

/* the data sheet example set, exposed so the harness can compute reference values */
extern const int32_t BME_EXAMPLE_RAW_T, BME_EXAMPLE_RAW_P, BME_EXAMPLE_RAW_H;
extern const int32_t BME_NOMINAL_RAW_P;
extern const bme_calib_t BME_CALIB_ALT;
void bme_swap(bme280_sim_t *b, uint8_t chip_id, int calib_set);
int bme_load_replay(bme280_sim_t *b, const char *path);

#endif
