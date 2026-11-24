/* sim_nano.c - runs the real compiled Nano node firmware on a simulated ATmega328P.
 *
 * the harness loads firmware.elf into simavr, attaches a register level BME280 model to the
 * TWI bus, drives the ADC inputs, watches pin 7 and captures the UART.  every scenario runs in
 * simulated time, so nothing sleeps.  each scenario runs in its own child process so that a
 * runaway scenario is killed by an alarm and fails instead of hanging the run. the same split
 * lets the scenarios run side by side.
 *
 * every scenario runs against two builds of the same source: the default one and the one with
 * NANO_WATCHDOG on.  every line the firmware prints is parsed and its checksum is checked by an
 * implementation of CRC-16/CCITT-FALSE written here from the definition and kept apart from the
 * firmware's, so a mistake in one shows up as a disagreement.
 */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#define _DEFAULT_SOURCE 1
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "avr_adc.h"
#include "avr_watchdog.h"
#include "avr_ioport.h"
#include "avr_twi.h"
#include "avr_uart.h"
#include "sim_interrupts.h"
#include "sim_avr.h"
#include "bme280_sim.h"
#include "../nano_node/linkframe.h"   /* the firmware's own checksum code, compiled here on the host */

/* ---- numbers taken from the firmware source (nano_node.ino and sensors.cpp) ------------ */
#define REPORT_INTERVAL_MS   2000.0   /* REPORT_INTERVAL_MS */
#define RETRY_INTERVAL_MS    30000.0  /* BME_RETRY_INTERVAL_MS */
#define MAX_FAILED_READS     3        /* BME_MAX_FAILED_READS */
#define MOISTURE_SETTLE_MS   50.0     /* MOISTURE_SETTLE_MS */
#define WIRE_TIMEOUT_MS      25.0     /* Wire.setWireTimeout(25000, true) */

/* ---- status bits, typed in from the link contract (not taken from the firmware source) ---- */
#define ST_BME_MISSING     1
#define ST_BME_STUCK       2
#define ST_BME_ASLEEP      4
#define ST_SUPPLY_RANGE    8
#define ST_RESET_WATCHDOG  16
#define ST_RESET_BROWNOUT  32
#define ST_BME_RANGE       64
#define STUCK_READS        60      /* the contract: 60 identical reads in a row (120 s) */

/* the calibration of the module on the bus, which the reference maths must use (the swap scenario changes it) */
static const bme_calib_t *g_calib = &BME_CALIB;

/* ---- harness limits ----------------------------------------------------------------- */
#define CPU_HZ        16000000u
#define SOAK_MS_DEF   300000.0        /* every scenario is run on to five minutes for the timing check */
#define GAP_TOL_MS    100.0           /* allowed deviation of a line gap from 2000 ms (see README) */
#define WALL_LIMIT_S  1800            /* a scenario that takes longer than this in real time fails */
#define MAX_LINES     600
#define MAX_PONGS     600
#define MAX_RESETS    16
#define PING_LIMIT_MS 500.0           /* the contract: a pong within 500 ms */
#define BAUD_BYTE_MS  1.0417          /* one byte at 9600 baud, 8N1: ten bits */
#define MAX_EVENTS    4096

static const char *g_elf_default = "../nano_node/.pio/build/nanoatmega328/firmware.elf";
static const char *g_elf_wdt     = "../nano_node/.pio/build/nanoatmega328new_wdt/firmware.elf";
static const char *g_elf = NULL;      /* the build the present scenario process runs */
static const char *g_elf_cal = "../nano_node/.pio/build/nanoatmega328new_cal/firmware.elf";
static int g_is_cal = 0;              /* 1 when that build has BANDGAP_CALIBRATED on: supply limits 4500 and 5500 */
/* the bootloader the chip starts in: 0 none (the sketch starts at once), 1 the new one (Optiboot 4.4 from the pinned
 * core, at 0x7E00) and 2 the old one (ATmegaBOOT_168, at 0x7800).  the hex files come from the core's own folder. */
enum { BL_NONE = 0, BL_NEW = 1, BL_OLD = 2 };
static const char *g_hex_new = NULL, *g_hex_old = NULL;
static int g_bl = BL_NONE;
static const char *g_replay = NULL;   /* a file of raw words logged from a real part, see bme_load_replay */
static int g_is_wdt = 0;              /* 1 when that build has NANO_WATCHDOG on */
static double g_soak_ms = SOAK_MS_DEF;

/* text is the front of the line (everything before ",ST:") so the scenarios can compare the original
 * keys on their own.  full is the whole line as sent, without CR LF. */
typedef struct {
    double t_first, t_end; char text[200]; char full[200]; int crlf; int nbytes;
    int has_tail, tail_exact, crc_ok; unsigned st, seq, vcc; unsigned long up;
} line_t;
typedef struct { double t_first, t_end; unsigned n; int crc_ok; int shape_ok; } pong_t;
typedef struct { double t; int ch; int kind; int pin7; double pin7_since; unsigned mv; unsigned admux; } conv_t;
typedef struct { double t; int level; } pinev_t;

/* ---- the simulated board, one per child process ------------------------------------- */
static struct {
    avr_t *avr;
    bme280_sim_t bme;
    avr_io_t *twi;

    line_t lines[MAX_LINES]; int nlines;
    pong_t pongs[MAX_PONGS]; int npongs;
    char cur[200]; int curlen; double cur_first; int cur_cr; int cur_bytes;
    unsigned vcc_mv;                  /* the supply the harness applies: AVcc, AREF and VCC */
    int adc_hung;                     /* conversions never complete: a forced hang */
    int nresets; int boot_at[MAX_RESETS]; double reset_t[MAX_RESETS];
    double base_ms;                   /* time before the last reset, see now_ms() */
    int expected_resets;              /* resets the scenario itself causes or expects */
    unsigned long long uart_bytes;

    unsigned adc_mv[8];
    unsigned moist_unpowered_mv;      /* what the pin reads when pin 7 is low: the probe is off */
    conv_t conv[MAX_EVENTS]; int nconv;
    pinev_t pin[MAX_EVENTS]; int npin;
    int pin7; double pin7_since;

    double stall_t[MAX_EVENTS]; int nstall;   /* bus-hang model: transfers that never completed */
    int crashed;
    time_t wall_start;
} W;

/* simavr sets its cycle counter back to 0 whenever the chip resets.  the harness keeps one time line that
 * runs straight through every reset: base_ms is the simulated time at which the present cycle count began. */
static double now_ms(void) { return W.base_ms + (double)W.avr->cycle * 1000.0 / (double)W.avr->frequency; }

/* ---- the independent checksum -------------------------------------------------------- */
/* CRC-16/CCITT-FALSE written from its definition: the message is fed one bit at a time, most
 * significant bit first, into a 16 bit register that starts at 0xFFFF.  each bit is XORed with the
 * bit shifted out of the top of the register and, when that is one, the polynomial 0x1021 is XORed
 * in after the shift.  there is no reflection and no final XOR.  this is a different arrangement
 * from the byte oriented one in the firmware on purpose. */
static uint16_t ref_crc16(const uint8_t *p, size_t n)
{
    uint16_t reg = 0xFFFF;
    for (size_t i = 0; i < n; i++)
        for (int b = 7; b >= 0; b--) {
            unsigned in = (p[i] >> b) & 1u;
            unsigned top = (reg >> 15) & 1u;
            reg = (uint16_t)(reg << 1);
            if (in ^ top) reg ^= 0x1021;
        }
    return reg;
}

/* "*CCCC" at the end of a line: four upper-case hex digits that match the body.  returns 1 when
 * they do and puts the body length in *body_len. */
static int check_star_crc(const char *full, size_t *body_len)
{
    const char *star = strrchr(full, '*');
    if (!star || strlen(star) != 5) return 0;
    unsigned got = 0;
    for (int i = 1; i <= 4; i++) {
        char c = star[i]; unsigned d;
        if (c >= '0' && c <= '9') d = (unsigned)(c - '0');
        else if (c >= 'A' && c <= 'F') d = (unsigned)(c - 'A') + 10u;
        else return 0;
        got = got * 16u + d;
    }
    *body_len = (size_t)(star - full);
    return ref_crc16((const uint8_t *)full, *body_len) == got;
}

/* ---- UART capture ------------------------------------------------------------------- */
static void finish_uart_line(void)
{
    char full[200];
    memcpy(full, W.cur, (size_t)W.curlen); full[W.curlen] = 0;
    size_t body = 0;
    int crc_ok = check_star_crc(full, &body);
    if (!strncmp(full, "PONG:", 5)) {
        if (W.npongs < MAX_PONGS) {
            pong_t *p = &W.pongs[W.npongs++];
            unsigned n = 0; char tail[8] = "";
            int shape = sscanf(full, "PONG:%u*%7s", &n, tail) == 2;
            char again[40]; snprintf(again, sizeof again, "PONG:%u*%s", n, tail);
            p->n = n; p->crc_ok = crc_ok; p->shape_ok = shape && !strcmp(again, full) && W.cur_cr;
            p->t_first = W.cur_first; p->t_end = now_ms();
        }
        return;
    }
    if (W.nlines >= MAX_LINES) return;
    line_t *l = &W.lines[W.nlines++];
    memset(l, 0, sizeof *l);
    l->t_first = W.cur_first; l->t_end = now_ms(); l->crlf = W.cur_cr; l->nbytes = W.cur_bytes;
    strncpy(l->full, full, sizeof l->full - 1);
    l->crc_ok = crc_ok;
    char *tailp = strstr(full, ",ST:");
    if (tailp) {
        size_t flen = (size_t)(tailp - full);
        memcpy(l->text, full, flen); l->text[flen] = 0;
        unsigned st, seq, vcc; unsigned long up;
        if (sscanf(tailp, ",ST:%u,SEQ:%u,UP:%lu,VCC:%u*", &st, &seq, &up, &vcc) == 4) {
            char again[100];
            snprintf(again, sizeof again, ",ST:%u,SEQ:%u,UP:%lu,VCC:%u", st, seq, up, vcc);
            /* the tail must be exactly that text up to the star: no spaces and no leading zeros */
            l->has_tail = 1;
            l->tail_exact = (strlen(tailp) > strlen(again)) && !strncmp(tailp, again, strlen(again)) && tailp[strlen(again)] == '*';
            l->st = st; l->seq = seq; l->up = up; l->vcc = vcc;
        }
    } else {
        strncpy(l->text, full, sizeof l->text - 1);
    }
}

static void uart_hook(struct avr_irq_t *irq, uint32_t value, void *param)
{
    (void)irq; (void)param;
    char c = (char)(value & 0xFF);
    W.uart_bytes++;
    if (W.curlen == 0) { W.cur_first = now_ms(); W.cur_cr = 0; W.cur_bytes = 0; }
    W.cur_bytes++;
    if (c == '\n') {
        finish_uart_line();
        W.curlen = 0;
    } else if (c == '\r') {
        W.cur_cr = 1;
    } else if (W.curlen < (int)sizeof(W.cur) - 1) {
        W.cur[W.curlen++] = c;
    }
}

/* ---- ADC: the harness answers every conversion with the voltage it has been given ---- */
static void adc_trigger_hook(struct avr_irq_t *irq, uint32_t value, void *param)
{
    (void)irq; (void)param;
    union { uint32_t v; avr_adc_mux_t m; } u;
    u.v = value;
    avr_adc_mux_t mux = u.m;
    unsigned mv = 0;
    int single = (mux.kind == ADC_MUX_SINGLE && mux.src <= 7);
    if (single) {
        mv = W.adc_mv[mux.src];
        if (mux.src == 1 && !W.pin7) mv = W.moist_unpowered_mv;   /* probe unpowered: pin 7 low */
    }
    /* every conversion is logged, the band gap ones too, with the ADMUX value the firmware set */
    if (W.nconv < MAX_EVENTS) {
        conv_t *c = &W.conv[W.nconv++];
        c->t = now_ms(); c->ch = single ? mux.src : -1; c->kind = (int)mux.kind; c->pin7 = W.pin7;
        c->pin7_since = W.pin7_since; c->mv = mv; c->admux = W.avr->data[0x7C];
    }
    /* simavr answers the band gap input itself (1100 mV against the chosen reference) */
    if (single) avr_raise_irq(avr_io_getirq(W.avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + mux.src), mv);
}

static void pin7_hook(struct avr_irq_t *irq, uint32_t value, void *param)
{
    (void)irq; (void)param;
    W.pin7 = value & 1;
    W.pin7_since = now_ms();
    if (W.npin < MAX_EVENTS) { W.pin[W.npin].t = W.pin7_since; W.pin[W.npin].level = W.pin7; W.npin++; }
}

/* simavr turns millivolts into counts as mv * 1023 / vref, so full scale is 1023 counts at
 * exactly vref.  vref is AVcc, which the supply scenarios move.  a real ADC divides by 1024.  this returns the lowest voltage that makes simavr
 * convert to the wanted count, so the applied count and the converted count agree. */
static unsigned mv_for_count(int count)
{
    double vref = (double)W.avr->avcc;   /* the reference is AVcc, so it follows the supply */
    if (count <= 0) return 0;
    if (count >= 1023) return (unsigned)vref;
    return (unsigned)ceil((double)count * vref / 1023.0);
}
static void set_adc_count(int ch, int count) { W.adc_mv[ch] = mv_for_count(count); }

/* ---- running ------------------------------------------------------------------------ */
/* a hung data line.  simavr has no SDA and SCL wires to hold low, so the harness stands in for
 * the stuck bus at the TWCR register: when the firmware asks for a START while the bus is
 * marked hung, the request is accepted (TWINT is cleared, as the hardware does) and the
 * transfer never completes.  the TWI interrupt flag never comes back, which is what a real master
 * sees when SDA is held low.  every other write goes through to simavr's own TWI model. */
static avr_io_write_t twcr_orig;
static void *twcr_orig_param;

static void twcr_hook(avr_t *avr, avr_io_addr_t addr, uint8_t v, void *param)
{
    (void)param;
    const uint8_t TWSTA = 1 << 5, TWEN = 1 << 2, TWINT = 1 << 7;
    if (W.bme.bus == BUS_HUNG && (v & TWSTA) && (v & TWEN)) {
        avr->data[addr] = (uint8_t)(v & ~TWINT);
        avr_clear_interrupt(avr, &((avr_twi_t *)W.twi)->twi);   /* the flag is cleared and stays clear */
        if (W.nstall < MAX_EVENTS) W.stall_t[W.nstall++] = now_ms();
        return;
    }
    if (twcr_orig) twcr_orig(avr, addr, v, twcr_orig_param);
}

/* a conversion that never finishes.  the ADC start request is accepted (ADSC stays set, as it does
 * while a conversion runs) and nothing ever completes it, so any wait on the ADC lasts for ever.
 * this is the forced hang the watchdog scenarios use: it is a place where the firmware waits with
 * no timeout of its own.  the hang is released when the chip resets. */
static avr_io_write_t adcsra_orig;
static void *adcsra_orig_param;
static avr_io_addr_t adcsra_addr;

static void adcsra_hook(avr_t *avr, avr_io_addr_t addr, uint8_t v, void *param)
{
    (void)param;
    if (W.adc_hung && (v & (1 << 6))) {   /* ADSC */
        avr->data[addr] = v;
        return;
    }
    if (adcsra_orig) adcsra_orig(avr, addr, v, adcsra_orig_param);
}

/* every reset of the chip, whoever causes it (the firmware's own watchdog or the harness), is
 * counted and timed here so the scenarios can see it.  simavr calls this hook inside avr_reset. */
static void (*reset_orig)(avr_t *avr);
static void reset_hook(avr_t *avr)
{
    if (reset_orig) reset_orig(avr);
    if (W.nresets < MAX_RESETS) { W.boot_at[W.nresets] = W.nlines; W.reset_t[W.nresets] = now_ms(); }
    W.nresets++;
    W.base_ms = now_ms();   /* avr_reset zeroes the cycle count right after this hook returns */
    W.curlen = 0;       /* a half sent line is lost with the reset */
    W.adc_hung = 0;     /* the forced hang does not survive a reset */
}

static void run_until(double ms)
{
    uint64_t guard = 0;
    while (now_ms() < ms) {
        /* the end is worked out again after a reset, which restarts simavr's cycle count */
        uint64_t end = (uint64_t)((ms - W.base_ms) * (double)W.avr->frequency / 1000.0);
        int resets = W.nresets;
        while (W.avr->cycle < end && W.nresets == resets) {
            int st = avr_run(W.avr);
            if (st == cpu_Done || st == cpu_Crashed) { W.crashed = 1; return; }
            if ((++guard & 0xFFFFF) == 0 && time(NULL) - W.wall_start > WALL_LIMIT_S) return;
        }
        if (W.nresets == resets && W.avr->cycle >= end) break;
    }
}

/* the installed simavr library needs libelf for its own ELF reader and libelf is not
 * installed here, so the harness reads the program headers itself.  every PT_LOAD segment
 * goes to flash at its load address, which is where the AVR startup code finds .text and the
 * initial values of .data. */
/* simavr's gdb stub drags in its ELF reader through sim_hex.o.  nothing here calls these, so stubs
 * (and the default mcu name it looks for) keep the link free of libelf. */
int elf_read_firmware(const char *file, void *firmware)
{
    (void)file; (void)firmware;
    return -1;
}

const char *sim_default_mcu = "atmega328p";

void avr_load_firmware(avr_t *avr, void *firmware)
{
    (void)avr; (void)firmware;
}

static uint32_t rd32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

/* an Intel hex file (the bootloaders ship as hex) loaded at the addresses it names */
static int load_hex_into_flash(avr_t *avr, const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    char ln[600]; int n = 0;
    while (fgets(ln, sizeof ln, f)) {
        unsigned len, addr, type;
        if (ln[0] != ':' || sscanf(ln + 1, "%2x%4x%2x", &len, &addr, &type) != 3 || type != 0) continue;
        uint8_t b[256];
        for (unsigned i = 0; i < len; i++) { unsigned v = 0; sscanf(ln + 9 + 2 * i, "%2x", &v); b[i] = (uint8_t)v; }
        avr_loadcode(avr, b, len, addr);
        n++;
    }
    fclose(f);
    return n ? 0 : -1;
}

static int load_elf_into_flash(avr_t *avr, const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *img = malloc((size_t)len);
    if (!img || fread(img, 1, (size_t)len, f) != (size_t)len) { fclose(f); free(img); return -1; }
    fclose(f);
    if (len < 52 || memcmp(img, "\177ELF", 4) != 0 || img[4] != 1 || img[5] != 1) { free(img); return -1; }
    uint32_t phoff = rd32(img + 0x1C);
    uint16_t phentsize = rd16(img + 0x2A), phnum = rd16(img + 0x2C);
    int loaded = 0;
    for (int i = 0; i < phnum; i++) {
        const uint8_t *ph = img + phoff + (size_t)i * phentsize;
        uint32_t type = rd32(ph), off = rd32(ph + 4), paddr = rd32(ph + 12), filesz = rd32(ph + 16);
        if (type != 1 || filesz == 0 || paddr >= 0x800000u) continue;
        if ((long)off + (long)filesz > len) { free(img); return -1; }
        avr_loadcode(avr, img + off, filesz, paddr);
        loaded++;
    }
    free(img);
    avr->codeend = avr->flashend;
    return loaded ? 0 : -1;
}

static void boot_vcc(uint8_t chip, uint8_t addr7, bme_bus_t bus, unsigned vcc_mv)
{
    memset(&W, 0, sizeof(W));
    W.vcc_mv = vcc_mv;
    W.wall_start = time(NULL);
    W.avr = avr_make_mcu_by_name("atmega328p");
    if (!W.avr) { fprintf(stderr, "no atmega328p core\n"); exit(2); }
    avr_init(W.avr);
    W.avr->log = LOG_ERROR;
    W.avr->frequency = CPU_HZ;
    W.avr->vcc = W.avr->avcc = W.avr->aref = (uint16_t)vcc_mv;
    if (load_elf_into_flash(W.avr, g_elf) != 0) { fprintf(stderr, "cannot load %s\n", g_elf); exit(2); }

    if (g_bl != BL_NONE) {
        /* the fuse BOOTRST starts the chip in the bootloader.  the bootloader decides whether the sketch runs */
        const char *hex = g_bl == BL_NEW ? g_hex_new : g_hex_old;
        if (!hex || load_hex_into_flash(W.avr, hex) != 0) { fprintf(stderr, "cannot load bootloader %s\n", hex ? hex : "(none given)"); exit(2); }
        W.avr->codeend = W.avr->flashend;
        W.avr->reset_pc = g_bl == BL_NEW ? 0x7E00 : 0x7800;
        W.avr->pc = W.avr->reset_pc;
    }
    for (avr_io_t *io = W.avr->io_port; io; io = io->next)
        if (io->kind && !strcmp(io->kind, "twi")) W.twi = io;

    if (!W.twi) { fprintf(stderr, "no TWI in this core\n"); exit(2); }
    {
        avr_io_addr_t twcr = ((avr_twi_t *)W.twi)->r_twcr;
        /* avr_register_io_write would chain the new hook after simavr's own, so the slot is
         * replaced directly and the original is called from the hook instead. */
        twcr_orig = W.avr->io[AVR_DATA_TO_IO(twcr)].w.c;
        twcr_orig_param = W.avr->io[AVR_DATA_TO_IO(twcr)].w.param;
        W.avr->io[AVR_DATA_TO_IO(twcr)].w.c = twcr_hook;
        W.avr->io[AVR_DATA_TO_IO(twcr)].w.param = NULL;
        if (!twcr_orig) { fprintf(stderr, "TWCR write hook not found\n"); exit(2); }
    }
    for (avr_io_t *io = W.avr->io_port; io; io = io->next)
        if (io->kind && !strcmp(io->kind, "adc")) {
            adcsra_addr = ((avr_adc_t *)io)->r_adcsra;
            adcsra_orig = W.avr->io[AVR_DATA_TO_IO(adcsra_addr)].w.c;
            adcsra_orig_param = W.avr->io[AVR_DATA_TO_IO(adcsra_addr)].w.param;
            W.avr->io[AVR_DATA_TO_IO(adcsra_addr)].w.c = adcsra_hook;
            W.avr->io[AVR_DATA_TO_IO(adcsra_addr)].w.param = NULL;
        }
    reset_orig = W.avr->reset;
    W.avr->reset = reset_hook;
    bme_init(&W.bme, W.avr, addr7, chip);
    W.bme.bus = bus;
    bme_attach(&W.bme);

    {   /* simavr echoes UART bytes to the console by default, which would bury the report */
        uint32_t flags = 0;
        avr_ioctl(W.avr, AVR_IOCTL_UART_SET_FLAGS('0'), &flags);
    }
    avr_irq_register_notify(avr_io_getirq(W.avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT), uart_hook, NULL);
    avr_irq_register_notify(avr_io_getirq(W.avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_OUT_TRIGGER), adc_trigger_hook, NULL);
    avr_irq_register_notify(avr_io_getirq(W.avr, AVR_IOCTL_IOPORT_GETIRQ('D'), 7), pin7_hook, NULL);

    set_adc_count(0, 300);   /* LDR */
    set_adc_count(1, 700);   /* moisture, dry */
    W.moist_unpowered_mv = 0;
}

static void boot(uint8_t chip, uint8_t addr7, bme_bus_t bus) { boot_vcc(chip, addr7, bus, 5000); }

/* ---- input to the firmware ---------------------------------------------------------- */
static void uart_send_byte(uint8_t b)
{
    avr_raise_irq(avr_io_getirq(W.avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_INPUT), b);
}

/* send text at 9600 baud, one byte time apart, while the firmware keeps running.  byte_ms can be
 * raised to send slowly.  returns the time at which the last byte arrived. */
static double uart_send(const char *s, size_t n, double byte_ms)
{
    double t_last = now_ms();
    for (size_t i = 0; i < n; i++) {
        t_last = now_ms();
        uart_send_byte((uint8_t)s[i]);
        run_until(now_ms() + byte_ms);
    }
    return t_last;
}
static double uart_text(const char *s) { return uart_send(s, strlen(s), BAUD_BYTE_MS); }

/* wait (in 0.5 ms steps) until a data line is part way through being sent */
static int wait_mid_line(double limit_ms)
{
    double end = now_ms() + limit_ms;
    while (now_ms() < end) {
        run_until(now_ms() + 0.5);
        if (W.curlen >= 30) return 1;
    }
    return 0;
}

/* ---- host reference maths: Bosch data sheet formulae -------------------------------- */
/* pres_hpa is the data sheet 64 bit result.  pres32_hpa is the data sheet 32 bit result, which is
 * what the firmware implements and so what it must print. */
typedef struct { double temp, pres_hpa, pres32_hpa, hum; int32_t t_fine; } ref_t;

static int32_t ref_t_int32(int32_t adc_T, int32_t *t_fine)
{
    const bme_calib_t *c = g_calib;
    int32_t v1 = ((((adc_T >> 3) - ((int32_t)c->T1 << 1))) * (int32_t)c->T2) >> 11;
    int32_t v2 = (((((adc_T >> 4) - (int32_t)c->T1) * ((adc_T >> 4) - (int32_t)c->T1)) >> 12) * (int32_t)c->T3) >> 14;
    *t_fine = v1 + v2;
    return (*t_fine * 5 + 128) >> 8;
}

/* 64 bit pressure formula, output in Pa as Q24.8 (data sheet 4.2.3).  deliberately not the
 * 32 bit variant the firmware uses, so the check does not just repeat the firmware's maths. */
static double ref_p_pa(int32_t adc_P, int32_t t_fine)
{
    const bme_calib_t *c = g_calib;
    int64_t var1 = (int64_t)t_fine - 128000;
    int64_t var2 = var1 * var1 * (int64_t)c->P6;
    var2 = var2 + ((var1 * (int64_t)c->P5) << 17);
    var2 = var2 + (((int64_t)c->P4) << 35);
    var1 = ((var1 * var1 * (int64_t)c->P3) >> 8) + ((var1 * (int64_t)c->P2) << 12);
    var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)c->P1) >> 33;
    if (var1 == 0) return 0;
    int64_t p = 1048576 - adc_P;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = (((int64_t)c->P9) * (p >> 13) * (p >> 13)) >> 25;
    var2 = (((int64_t)c->P8) * p) >> 19;
    p = ((p + var1 + var2) >> 8) + (((int64_t)c->P7) << 4);
    return (double)p / 256.0;
}

/* 32 bit pressure formula from the same data sheet section.  it differs from the 64 bit one by
 * a few pascals because of its integer rounding, which is why the two are kept apart. */
static double ref_p_pa32(int32_t adc_P, int32_t t_fine)
{
    const bme_calib_t *c = g_calib;
    int32_t var1 = (t_fine >> 1) - 64000;
    int32_t var2 = (((var1 >> 2) * (var1 >> 2)) >> 11) * (int32_t)c->P6;
    var2 = var2 + ((var1 * (int32_t)c->P5) << 1);
    var2 = (var2 >> 2) + ((int32_t)c->P4 << 16);
    var1 = ((((int32_t)c->P3 * (((var1 >> 2) * (var1 >> 2)) >> 13)) >> 3) + (((int32_t)c->P2 * var1) >> 1)) >> 18;
    var1 = ((32768 + var1) * (int32_t)c->P1) >> 15;
    if (var1 == 0) return 0;
    uint32_t p = (((uint32_t)(((int32_t)1048576) - adc_P) - (uint32_t)(var2 >> 12))) * 3125;
    if (p < 0x80000000UL) p = (p << 1) / (uint32_t)var1; else p = (p / (uint32_t)var1) * 2;
    var1 = ((int32_t)c->P9 * ((int32_t)(((p >> 3) * (p >> 3)) >> 13))) >> 12;
    var2 = ((int32_t)(p >> 2) * (int32_t)c->P8) >> 13;
    p = (uint32_t)((int32_t)p + ((var1 + var2 + (int32_t)c->P7) >> 4));
    return (double)p;
}

static double ref_h_pct(int32_t adc_H, int32_t t_fine)
{
    const bme_calib_t *c = g_calib;
    int32_t v = t_fine - 76800;
    v = (((((adc_H << 14) - (((int32_t)c->H4) << 20) - (((int32_t)c->H5) * v)) + 16384) >> 15)
         * (((((((v * (int32_t)c->H6) >> 10) * (((v * (int32_t)c->H3) >> 11) + 32768)) >> 10) + 2097152)
              * (int32_t)c->H2 + 8192) >> 14));
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)c->H1) >> 4);
    v = v < 0 ? 0 : v;
    v = v > 419430400 ? 419430400 : v;
    return (double)(v >> 12) / 1024.0;
}

static ref_t reference(int32_t raw_t, int32_t raw_p, int32_t raw_h)
{
    ref_t r;
    r.temp = ref_t_int32(raw_t, &r.t_fine) / 100.0;
    r.pres_hpa = ref_p_pa(raw_p, r.t_fine) / 100.0;
    r.pres32_hpa = ref_p_pa32(raw_p, r.t_fine) / 100.0;
    r.hum = ref_h_pct(raw_h, r.t_fine);
    return r;
}

/* Arduino's Print::print(float, 1) rounds half up to one decimal. */
static void fmt1(char *out, size_t n, double v)
{
    /* sign and magnitude, as Print does: the magnitude is rounded half up and then the minus is put in front */
    double m = floor(fabs(v) * 10.0 + 0.5) / 10.0;
    snprintf(out, n, "%s%.1f", (v < 0 && m > 0) ? "-" : "", m);
}

static void expect_line(char *out, size_t n, const char *t, const char *h, const char *p,
                        int light, int moist, int water)
{
    snprintf(out, n, "TEMP:%s,HUM:%s,PRES:%s,LIGHT:%d,MOIST:%d,WATER:%d", t, h, p, light, moist, water);
}

/* expected line for the model's present raw values and the applied ADC counts */
static void expect_good(char *out, size_t n, int light, int moist, int has_hum)
{
    ref_t r = reference(W.bme.raw_t, W.bme.raw_p, W.bme.raw_h);
    char t[24], h[24], p[24];
    fmt1(t, sizeof t, r.temp); fmt1(p, sizeof p, r.pres32_hpa);
    if (has_hum) fmt1(h, sizeof h, r.hum); else strcpy(h, "-1");
    expect_line(out, n, t, h, p, light, moist, moist < 500 ? 1 : 0);
}
static void expect_lost(char *out, size_t n, int light, int moist)
{
    expect_line(out, n, "-1", "-1", "-1", light, moist, moist < 500 ? 1 : 0);
}

/* ---- scenario bookkeeping ------------------------------------------------------------- */
/* an OBSERVED scenario reports what the model did and has no check that its claim could fail: it is an observation and not a test */
enum { ST_PASS = 0, ST_FAIL = 1, ST_FINDING = 2, ST_OBSERVED = 3 };
static const char *tag_of(int status) { return status == ST_PASS ? "PASS" : status == ST_FAIL ? "FAIL" : status == ST_FINDING ? "FINDING" : "OBSERVED"; }

typedef struct {
    int status;
    int gaps; double gap_min, gap_max, gap_worst_dev;
    double sim_ms, wall_s;
    int fails;
    char detail[30000];
} result_t;

/* which builds a scenario runs against: both, only the default one or only the watchdog one */
enum { B_BOTH = 0, B_DEFAULT = 1, B_WDT = 2, B_ALL = 3 };   /* B_ALL adds the calibrated build */
/* bl is a mask of the bootloaders the scenario starts the chip in: 1 the new one, 2 the old one, 0 none (the sketch starts at once) */
typedef struct { const char *id; const char *name; void (*run)(result_t *r); int builds; int bl; } scenario_t;
static result_t *R;   /* result of the scenario this process runs */
static int g_finding;
static int g_observation;

static void note(const char *fmt, ...)
{
    size_t used = strlen(R->detail);
    va_list ap; va_start(ap, fmt);
    vsnprintf(R->detail + used, sizeof(R->detail) - used, fmt, ap);
    va_end(ap);
}

static void check(int ok, const char *fmt, ...)
{
    if (ok) return;
    R->fails++;
    size_t used = strlen(R->detail);
    va_list ap; va_start(ap, fmt);
    snprintf(R->detail + used, sizeof(R->detail) - used, "  FAIL: ");
    used = strlen(R->detail);
    vsnprintf(R->detail + used, sizeof(R->detail) - used, fmt, ap);
    va_end(ap);
    used = strlen(R->detail);
    snprintf(R->detail + used, sizeof(R->detail) - used, "\n");
}

static void dump_lines(int from, int to)
{
    for (int i = from; i < to && i < W.nlines; i++)
        note("    [%3d] t=%9.1f ms  %s\n", i, W.lines[i].t_first, W.lines[i].text);
}

static void dump_all_lines(void)
{
    int n = W.nlines;
    if (n <= 40) { dump_lines(0, n); return; }
    dump_lines(0, 20);
    note("    ... %d lines omitted ...\n", n - 40);
    dump_lines(n - 20, n);
}

/* index of the first line that starts at or after t */
static int first_line_after(double t)
{
    for (int i = 0; i < W.nlines; i++) if (W.lines[i].t_first >= t) return i;
    return W.nlines;
}

static int is_lost(const char *s) { return !strncmp(s, "TEMP:-1,HUM:-1,PRES:-1,", 23); }

/* every line in [from,to) carries exactly this status */
static int all_st(int from, int to, unsigned want, int *bad)
{
    for (int i = from; i < to; i++)
        if (W.lines[i].st != want) { *bad = i; return 0; }
    return 1;
}

/* every line in [from,to) equals want */
static int all_equal(int from, int to, const char *want, int *bad)
{
    for (int i = from; i < to; i++)
        if (strcmp(W.lines[i].text, want)) { *bad = i; return 0; }
    return 1;
}

static int is_boot_start(int i)
{
    if (i == 0) return 1;
    for (int k = 0; k < W.nresets && k < MAX_RESETS; k++) if (W.boot_at[k] == i) return 1;
    return 0;
}

/* gap statistics over the whole run, from the first byte of each line */
static void compute_gaps(void)
{
    R->gaps = 0; R->gap_min = 1e9; R->gap_max = 0; R->gap_worst_dev = 0;
    for (int i = 1; i < W.nlines; i++) {
        if (is_boot_start(i)) continue;   /* a reset restarts the rhythm, the gap across it is not a gap */
        double g = W.lines[i].t_first - W.lines[i - 1].t_first;
        R->gaps++;
        if (g < R->gap_min) R->gap_min = g;
        if (g > R->gap_max) R->gap_max = g;
        double dev = fabs(g - REPORT_INTERVAL_MS);
        if (dev > R->gap_worst_dev) R->gap_worst_dev = dev;
    }
    if (!R->gaps) R->gap_min = 0;
}

/* checks that apply to every scenario and every line the firmware sent:
 * the shape of the tail, the checksum (by the independent implementation), the length, SEQ without
 * gaps, UP advancing by 2 within a second, the status bits consistent with the line, the reset
 * bits held for the whole boot and every pong well formed. */
static void check_link_lines(void)
{
    int bad_crc = -1, bad_tail = -1, bad_len = -1, bad_crlf = -1, bad_seq = -1, bad_up = -1, bad_form = -1,
        bad_sup = -1, bad_held = -1, bad_res = -1;
    int n_crc = 0, n_seq = 0, n_up = 0;
    for (int i = 0; i < W.nlines; i++) {
        line_t *l = &W.lines[i];
        if (!l->crc_ok) { if (bad_crc < 0) bad_crc = i; n_crc++; }
        if (!l->has_tail || !l->tail_exact) { if (bad_tail < 0) bad_tail = i; continue; }
        if (l->nbytes > 160 || l->nbytes < 20) { if (bad_len < 0) bad_len = i; }
        if (!l->crlf) { if (bad_crlf < 0) bad_crlf = i; }
        if (l->st > 127) { if (bad_res < 0) bad_res = i; }
        int sensor_bits = (int)(l->st & (ST_BME_MISSING | ST_BME_STUCK | ST_BME_ASLEEP | ST_BME_RANGE));
        if (is_lost(l->text) != (sensor_bits != 0)) { if (bad_form < 0) bad_form = i; }
        if (((l->vcc < (g_is_cal ? 4500u : 4000u) || l->vcc > (g_is_cal ? 5500u : 6000u)) ? 1 : 0) != ((l->st & ST_SUPPLY_RANGE) ? 1 : 0)) { if (bad_sup < 0) bad_sup = i; }
        if (is_boot_start(i)) {
            if (l->seq != 0) { if (bad_seq < 0) bad_seq = i; n_seq++; }
            if (l->up < 1 || l->up > 3) { if (bad_up < 0) bad_up = i; n_up++; }
        } else {
            line_t *p = &W.lines[i - 1];
            if (l->seq != ((p->seq + 1u) & 0xFFFFu)) { if (bad_seq < 0) bad_seq = i; n_seq++; }
            long d = (long)l->up - (long)p->up;
            if (d < 1 || d > 3) { if (bad_up < 0) bad_up = i; n_up++; }   /* 2 s per line, one second of tolerance */
            if ((l->st & 48u) != (p->st & 48u)) { if (bad_held < 0) bad_held = i; }
        }
    }
    check(bad_crc < 0, "%d line(s) failed the independent CRC-16 check, the first is line %d: %s", n_crc, bad_crc, bad_crc < 0 ? "" : W.lines[bad_crc].full);
    check(bad_tail < 0, "line %d does not end in exactly ,ST:n,SEQ:n,UP:n,VCC:n*CCCC: %s", bad_tail, bad_tail < 0 ? "" : W.lines[bad_tail].full);
    check(bad_len < 0, "line %d is %d bytes with CR LF, want 20 to 160", bad_len, bad_len < 0 ? 0 : W.lines[bad_len].nbytes);
    check(bad_crlf < 0, "line %d is not ended by CR LF", bad_crlf);
    check(bad_res < 0, "line %d has a status bit above 64", bad_res);
    check(bad_seq < 0, "SEQ did not count 0,1,2,... without gaps (%d breaks, the first at line %d)", n_seq, bad_seq);
    check(bad_up < 0, "UP did not advance by 2 (+/- 1 s) per line (%d breaks, the first at line %d)", n_up, bad_up);
    check(bad_form < 0, "line %d: the -1 form and the sensor status bits disagree: %s", bad_form, bad_form < 0 ? "" : W.lines[bad_form].full);
    check(bad_sup < 0, "line %d: SUPPLY_RANGE disagrees with VCC: %s", bad_sup, bad_sup < 0 ? "" : W.lines[bad_sup].full);
    check(bad_held < 0, "line %d: a reset-cause bit changed inside one boot", bad_held);
    int bad_pong = 0;
    for (int i = 0; i < W.npongs; i++) if (!W.pongs[i].crc_ok || !W.pongs[i].shape_ok) bad_pong++;
    check(bad_pong == 0, "%d pong(s) are not exactly PONG:<n>*CCCC with a good checksum", bad_pong);
    check(W.nresets == W.expected_resets, "the chip reset %d time(s), the scenario expects %d (a reset the scenario did not cause is a firmware restart)", W.nresets, W.expected_resets);
    note("  link check: %d lines, every one with a good CRC from the independent implementation, SEQ without gaps and UP stepping by 2\n", W.nlines);
}

/* run on to the soak time, then check the process stayed alive and the line rhythm held */
static void soak_and_finish(int expect_lines_to_end)
{
    run_until(g_soak_ms);
    compute_gaps();
    R->sim_ms = now_ms();
    check_link_lines();
    check(!W.crashed, "the simulated CPU stopped or crashed at %.1f ms", now_ms());
    check(now_ms() >= g_soak_ms - 1.0, "the run stopped at %.1f ms, short of %.0f ms (wall limit hit)", now_ms(), g_soak_ms);
    if (expect_lines_to_end) {
        /* the last line must be recent: a hung firmware stops printing */
        double since = now_ms() - (W.nlines ? W.lines[W.nlines - 1].t_first : 0);
        check(W.nlines > 0 && since < REPORT_INTERVAL_MS + GAP_TOL_MS + 100,
              "no new line for %.0f ms at the end of the run (firmware stopped printing)", since);
    }
    if (R->gaps && R->gap_worst_dev > GAP_TOL_MS)
        check(0, "line gap outside 2000 +/- %.0f ms: min %.1f, max %.1f", GAP_TOL_MS, R->gap_min, R->gap_max);
}

static void finish(void)
{
    R->wall_s = (double)(time(NULL) - W.wall_start);
    if (R->fails) {
        R->status = ST_FAIL;
        note("  captured UART output:\n");
        dump_all_lines();
    } else if (g_finding) {
        R->status = ST_FINDING;
    } else if (g_observation) {
        R->status = ST_OBSERVED;
    } else {
        R->status = ST_PASS;
    }
}

/* ======================================================================================
 * scenarios
 * ==================================================================================== */

/* 1. healthy BME280 at 0x76 */
static void sc_healthy(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    run_until(12000);
    char want[200]; expect_good(want, sizeof want, 300, 700, 1);
    ref_t ref = reference(BME_EXAMPLE_RAW_T, BME_EXAMPLE_RAW_P, BME_EXAMPLE_RAW_H);
    /* the data sheet example: 25.08 degrees C and 100653 Pa.  checks the reference maths itself */
    check(fabs(ref.temp - 25.08) < 0.005, "reference temperature %.3f is not the data sheet 25.08", ref.temp);
    check(fabs(ref.pres_hpa * 100.0 - 100653.0) < 1.0, "reference pressure %.2f Pa is not the data sheet 100653", ref.pres_hpa * 100.0);
    check(fabs(ref.pres32_hpa - ref.pres_hpa) <= 0.05, "32 bit and 64 bit pressure maths differ by %.3f hPa", ref.pres32_hpa - ref.pres_hpa);
    note("  expected line: %s\n  reference: %.2f C, %.2f hPa by the 64 bit data sheet formula (data sheet example 100653 Pa), %.2f hPa by the 32 bit formula the firmware uses, %.2f %%RH\n",
         want, ref.temp, ref.pres_hpa, ref.pres32_hpa, ref.hum);
    check(W.nlines >= 5, "only %d lines in 12 s, want at least 5", W.nlines);
    if (W.nlines) {
        double t0 = W.lines[0].t_first;
        check(t0 >= REPORT_INTERVAL_MS && t0 <= REPORT_INTERVAL_MS + 200.0,
              "first line starts at %.1f ms, want between 2000 and 2200 ms (the interval plus the sensor reads)", t0);
        note("  first line starts at %.1f ms and ends at %.1f ms\n", t0, W.lines[0].t_end);
    }
    int bad = -1;
    check(all_equal(0, W.nlines, want, &bad), "line %d differs from the expected text", bad);
    for (int i = 0; i < W.nlines; i++) check(W.lines[i].crlf, "line %d is not ended by CR LF", i);
    {   /* the tail of a healthy line: ST 0 and VCC close to the 5000 mV applied */
        int b2 = -1, vbad = -1; unsigned vmin = 99999, vmax = 0;
        check(all_st(0, W.nlines, 0, &b2), "line %d has ST:%u, want 0 on a healthy node", b2, b2 < 0 ? 0 : W.lines[b2].st);
        for (int i = 0; i < W.nlines; i++) {
            if (W.lines[i].vcc < vmin) vmin = W.lines[i].vcc;
            if (W.lines[i].vcc > vmax) vmax = W.lines[i].vcc;
            if (fabs((double)W.lines[i].vcc - 5000.0) > 50.0 && vbad < 0) vbad = i;
        }
        check(vbad < 0, "line %d: VCC %u is not within 1 per cent of the 5000 mV applied", vbad, vbad < 0 ? 0 : W.lines[vbad].vcc);
        note("  tail of a healthy line: %s\n  VCC read %u to %u mV for 5000 mV applied (simavr divides by 1023 and a real ADC by 1024, so the sim reads about 0.1 per cent high)\n",
             W.nlines ? W.lines[W.nlines - 1].full + strlen(W.lines[W.nlines - 1].text) : "", vmin, vmax);
    }
    {   /* the set-up the firmware wrote, decoded: temperature x2 (010), pressure x16 (101), normal mode (11) and humidity x1 */
        double conv = bme_conversion_ms(&W.bme);
        note("  set-up written: ctrl_meas 0x%02X (osrs_t %d, osrs_p %d, mode %d), ctrl_hum 0x%02X, config 0x%02X. longest conversion %.1f ms by the data sheet formula (standby 0.5 ms), against a 2000 ms report interval\n",
             W.bme.ctrl_meas, W.bme.ctrl_meas >> 5, (W.bme.ctrl_meas >> 2) & 7, W.bme.ctrl_meas & 3, W.bme.ctrl_hum, W.bme.config, conv);
        check(fabs(conv - 46.1) < 0.05, "longest conversion %.2f ms, the data sheet formula gives 46.1 ms for T x2, P x16 and H x1", conv);
    }
    check(W.bme.ctrl_meas == 0x57 && W.bme.ctrl_hum == 0x01 && W.bme.config == 0x00,
          "firmware left ctrl_meas=0x%02X ctrl_hum=0x%02X config=0x%02X, want 0x57 0x01 0x00",
          W.bme.ctrl_meas, W.bme.ctrl_hum, W.bme.config);
    soak_and_finish(1);
    finish();
}

/* 2. BME280 at 0x77 only */
static void sc_addr77(result_t *r)
{
    (void)r;
    boot(0x60, 0x77, BUS_NORMAL);
    run_until(12000);
    char want[200]; expect_good(want, sizeof want, 300, 700, 1);
    int bad = -1;
    check(W.nlines >= 5, "only %d lines in 12 s", W.nlines);
    check(all_equal(0, W.nlines, want, &bad), "line %d differs from the expected text: %s", bad, want);
    check(W.bme.n_starts_other >= 1, "the firmware never probed 0x76 first (other-address starts: %u)", W.bme.n_starts_other);
    check(W.bme.n_starts_acked > 0, "0x77 never acknowledged");
    note("  probes of 0x76 seen by the bus: %u; transfers to 0x77: %u\n", W.bme.n_starts_other, W.bme.n_starts_acked);
    soak_and_finish(1);
    finish();
}

/* 3. BMP280 (id 0x58): humidity -1 and the rest right */
static void sc_bmp280(result_t *r)
{
    (void)r;
    boot(0x58, 0x76, BUS_NORMAL);
    run_until(12000);
    char want[200]; expect_good(want, sizeof want, 300, 700, 0);
    int bad = -1;
    check(W.nlines >= 5, "only %d lines in 12 s", W.nlines);
    check(all_equal(0, W.nlines, want, &bad), "line %d differs from the expected text: %s", bad, want);
    check(W.bme.ctrl_hum == 0 && W.bme.ctrl_meas == 0x57, "BMP280 control registers 0x%02X 0x%02X, want ctrl_hum untouched and ctrl_meas 0x57",
          W.bme.ctrl_hum, W.bme.ctrl_meas);
    check(all_st(0, W.nlines, 0, &bad), "line %d has ST:%u, want 0", bad, bad < 0 ? 0 : W.lines[bad].st);
    note("  expected line: %s\n", want);
    soak_and_finish(1);
    finish();
}

/* 4. nothing on the bus */
static void sc_no_sensor(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_SILENT);
    run_until(25000);
    char want[200]; expect_lost(want, sizeof want, 300, 700);
    int bad = -1;
    check(W.nlines >= 11, "only %d lines in 25 s, want at least 11", W.nlines);
    check(all_equal(0, W.nlines, want, &bad), "line %d differs from: %s", bad, want);
    check(all_st(0, W.nlines, ST_BME_MISSING, &bad), "line %d has ST:%u, want 1 (BME_MISSING)", bad, bad < 0 ? 0 : W.lines[bad].st);
    unsigned before = W.bme.n_starts_ignored;
    run_until(40000);
    check(W.bme.n_starts_ignored > before, "no probe seen between 25 s and 40 s: the 30 s retry did not happen (%u)", before);
    note("  bus starts seen with no sensor: %u at 25 s, %u at 40 s (probes at boot and again after 30 s)\n", before, W.bme.n_starts_ignored);
    note("  note: a missing part is answered with a NACK, so this scenario does not reach the I2C timeout. scenario 8 does.\n");
    soak_and_finish(1);
    finish();
}

/* 5. sensor answers, then stops answering mid-run */
static void sc_goes_silent(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    char good[200], lost[200];
    expect_good(good, sizeof good, 300, 700, 1);
    expect_lost(lost, sizeof lost, 300, 700);
    run_until(10500);
    int n_before = W.nlines;
    check(n_before >= 4, "only %d good lines before the fault", n_before);
    int bad = -1;
    check(all_equal(0, n_before, good, &bad), "pre-fault line %d is wrong", bad);
    W.bme.bus = BUS_SILENT;
    unsigned ign0 = W.bme.n_starts_ignored;
    run_until(17500);
    unsigned ign_a = W.bme.n_starts_ignored;
    run_until(44000);
    unsigned ign_b = W.bme.n_starts_ignored;
    run_until(52000);
    unsigned ign_c = W.bme.n_starts_ignored;
    int i0 = n_before;
    check(W.nlines >= i0 + 19, "lines stopped after the fault: %d lines at 52 s", W.nlines);
    check(all_equal(i0, W.nlines, lost, &bad), "line %d after the fault is not the lost-sensor line: %s", bad, lost);
    check(all_st(i0, W.nlines, ST_BME_MISSING, &bad), "line %d after the fault has ST:%u, want 1 (BME_MISSING)", bad, bad < 0 ? 0 : W.lines[bad].st);
    note("  the first line after the fault (at %.1f ms) already shows -1: the firmware does not wait for the third failure to show it\n",
         W.lines[i0].t_first);
    check(ign_a - ign0 == MAX_FAILED_READS, "failed transfers 10.5 s to 17.5 s: %u, want exactly %d before the sensor is marked lost",
          ign_a - ign0, MAX_FAILED_READS);
    check(ign_b == ign_a, "the firmware kept polling a lost sensor (%u more transfers up to 44 s)", ign_b - ign_a);
    check(ign_c > ign_b, "no retry probe seen by 52 s");
    note("  failed transfers: %u by 17.5 s (the limit is %d), %u more by 44 s, %u more by 52 s (the 30 s retry)\n",
         ign_a - ign0, MAX_FAILED_READS, ign_b - ign_a, ign_c - ign_b);
    soak_and_finish(1);
    finish();
}

/* 5b. one missed read only: tolerated, one -1 line and then good again */
static void sc_glitch(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    char good[200], lost[200];
    expect_good(good, sizeof good, 300, 700, 1);
    expect_lost(lost, sizeof lost, 300, 700);
    run_until(10500);
    W.bme.bus = BUS_SILENT;
    run_until(11500);   /* the read at about 12 s will fall after this, so silence it again at 11.5 s */
    W.bme.bus = BUS_SILENT;
    run_until(12500);   /* covers the 12 s read */
    W.bme.bus = BUS_NORMAL;
    run_until(30000);
    int bad = -1;
    int nlost = 0;
    for (int i = 0; i < W.nlines; i++) if (!strcmp(W.lines[i].text, lost)) nlost++;
    check(nlost == 1, "%d lost-sensor lines for one missed read, want 1", nlost);
    for (int i = 0; i < W.nlines; i++)
        if (!strcmp(W.lines[i].text, lost)) check(W.lines[i].st == ST_BME_MISSING, "the lost line has ST:%u, want 1", W.lines[i].st);
    int after = first_line_after(14000);
    check(all_equal(after, W.nlines, good, &bad), "line %d after the glitch is not a good line", bad);
    note("  a single failed read costs one -1 line and no retry delay\n");
    soak_and_finish(1);
    finish();
}

/* helper: first index at or after `from_line` whose text is the good line (-1 when none is) */
static int first_good(int from_line, const char *good)
{
    for (int i = from_line; i < W.nlines; i++) if (!strcmp(W.lines[i].text, good)) return i;
    return -1;
}

/* 6. sensor returns 40 s after it stopped */
static void sc_returns(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    char good[200], lost[200];
    expect_good(good, sizeof good, 300, 700, 1);
    expect_lost(lost, sizeof lost, 300, 700);
    run_until(10500);
    int n_before = W.nlines;
    W.bme.bus = BUS_SILENT;
    run_until(50500);   /* 40 s of silence */
    W.bme.bus = BUS_NORMAL;
    double t_back = now_ms();
    run_until(130000);
    int gi = first_good(n_before, good);
    check(gi >= 0, "readings never returned after the sensor came back");
    if (gi >= 0) {
        double delay = W.lines[gi].t_first - t_back;
        note("  sensor back at %.1f ms; first good line at %.1f ms, %.1f s later\n", t_back, W.lines[gi].t_first, delay / 1000.0);
        check(delay >= 0, "a good line appeared before the sensor returned");
        check(delay <= RETRY_INTERVAL_MS + 2 * REPORT_INTERVAL_MS + 500, "recovery took %.1f s, longer than the 30 s retry plus two intervals", delay / 1000.0);
        int bad = -1;
        check(all_equal(gi, W.nlines, good, &bad), "line %d after recovery is wrong", bad);
        int stale = 0;
        for (int i = n_before; i < gi; i++) if (strcmp(W.lines[i].text, lost)) stale++;
        check(stale == 0, "%d lines between the fault and the recovery were not the -1 line", stale);
    }
    soak_and_finish(1);
    finish();
}

/* 6b. no sensor at start and one plugged in at 40 s */
static void sc_plugged_late(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_SILENT);
    char good[200];
    expect_good(good, sizeof good, 300, 700, 1);
    run_until(40500);
    W.bme.bus = BUS_NORMAL;
    double t_back = now_ms();
    run_until(110000);
    int gi = first_good(0, good);
    check(gi >= 0, "readings never appeared after the sensor was plugged in");
    if (gi >= 0) {
        double delay = W.lines[gi].t_first - t_back;
        note("  plugged in at %.1f ms; first good line at %.1f ms, %.1f s later\n", t_back, W.lines[gi].t_first, delay / 1000.0);
        check(delay <= RETRY_INTERVAL_MS + 2 * REPORT_INTERVAL_MS + 500, "pick-up took %.1f s", delay / 1000.0);
        int bad = -1;
        check(all_equal(gi, W.nlines, good, &bad), "line %d after pick-up is wrong", bad);
    }
    soak_and_finish(1);
    finish();
}

/* 7a. brown-out: every register returns to its power-on value while the part still answers */
static void sc_reset_full(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    char good[200], lost[200];
    expect_good(good, sizeof good, 300, 700, 1);
    expect_lost(lost, sizeof lost, 300, 700);
    run_until(10500);
    int n_before = W.nlines;
    unsigned writes_before = W.bme.n_ctrl_meas_writes;
    bme_power_on_reset(&W.bme);
    double t_reset = now_ms();
    run_until(110000);
    int bad = -1;
    check(all_equal(0, n_before, good, &bad), "pre-reset line %d is wrong", bad);
    int gi = first_good(n_before, good);
    int nbad = 0, nlost = 0;
    int end = gi < 0 ? W.nlines : gi;
    for (int i = n_before; i < end; i++) { if (!strcmp(W.lines[i].text, lost)) nlost++; else nbad++; }
    check(nbad == 0, "%d lines after the reset were neither good nor -1 (stale or wrong values)", nbad);
    check(gi >= 0, "the firmware never re-initialised the part and readings never returned");
    check(W.bme.n_ctrl_meas_writes > writes_before, "the firmware never re-wrote ctrl_meas after the reset");
    /* the control registers read back as zero, so the first read after the reset sees an asleep part,
     * rewrites the set-up at once and the next line is good: one -1 line and no 30 s wait. */
    check(nlost == 1, "%d -1 lines after the reset, want 1", nlost);
    check(gi == n_before + 1, "good values came back at line %d, want line %d (one line after the reset)", gi, n_before + 1);
    check(W.lines[n_before].st == ST_BME_ASLEEP, "the first line after the reset has ST:%u, want 4 (BME_ASLEEP)", W.lines[n_before].st);
    check(all_st(n_before + 1, W.nlines, 0, &bad), "line %d after recovery has ST:%u, want 0", bad, bad < 0 ? 0 : W.lines[bad].st);
    if (gi >= 0)
        note("  reset at %.1f ms. %d line of -1 with ST:4, then good again from %.1f ms (%.1f s after the reset).\n"
             "  the control registers read back as 0 so the firmware sees an asleep part, rewrites the set-up at once and does not wait for the 30 s retry.\n",
             t_reset, nlost, W.lines[gi].t_first, (W.lines[gi].t_first - t_reset) / 1000.0);
    soak_and_finish(1);
    finish();
}

/* 7b and 7c. only the control registers reset: the part falls to sleep mode and keeps its last data.
 * a BME280 (7b) and a BMP280 (7c, which has no ctrl_hum). */
static void ctrl_reset_common(uint8_t chip)
{
    boot(chip, 0x76, BUS_NORMAL);
    /* let the readings move so a frozen value is visible */
    W.bme.drift_t = 300; W.bme.drift_p = 200; W.bme.drift_t0_ms = 0; W.bme.drift_on = 1;
    run_until(10500);
    int n_before = W.nlines;
    unsigned writes_before = W.bme.n_ctrl_meas_writes;
    bme_reset_control_only(&W.bme);
    run_until(130000);
    int distinct_before = 0;
    for (int i = 1; i < n_before; i++) if (strcmp(W.lines[i].text, W.lines[i - 1].text)) distinct_before++;
    check(distinct_before >= 3, "readings did not move before the reset (%d changes), the test cannot see a freeze", distinct_before);
    note("  before the reset the readings moved on %d of %d lines.\n", distinct_before, n_before - 1);
    note("  control registers reset to sleep mode at 10.5 s: ctrl_meas was 0x%02X, now 0x%02X after the firmware's repair, %u ctrl_meas write(s) by the firmware.\n",
         0x00, W.bme.ctrl_meas, W.bme.n_ctrl_meas_writes - writes_before);
    check(W.nlines > n_before + 2, "too few lines after the reset");
    int n_asleep = 0, bad = -1;
    for (int i = n_before; i < W.nlines; i++) if (W.lines[i].st & ST_BME_ASLEEP) n_asleep++;
    /* the stated bound: BME_ASLEEP on the first line after the reset only, good values on the next one */
    check(n_asleep == 1, "%d lines carry BME_ASLEEP, want exactly 1", n_asleep);
    check(W.lines[n_before].st == ST_BME_ASLEEP && is_lost(W.lines[n_before].text),
          "the first line after the reset is '%s', want -1 values with ST:4", W.lines[n_before].full);
    check(!is_lost(W.lines[n_before + 1].text) && W.lines[n_before + 1].st == 0,
          "the second line after the reset is '%s', want good values with ST:0", W.lines[n_before + 1].full);
    check(all_st(n_before + 1, W.nlines, 0, &bad), "line %d after recovery has ST:%u, want 0", bad, bad < 0 ? 0 : W.lines[bad].st);
    check(strcmp(W.lines[n_before + 1].text, W.lines[n_before - 1].text) != 0, "the value after recovery is the stale value from before the reset");
    check(W.bme.n_ctrl_meas_writes > writes_before, "the firmware never rewrote ctrl_meas");
    check(W.bme.ctrl_meas == 0x57, "ctrl_meas is 0x%02X at the end, want 0x57", W.bme.ctrl_meas);
    int moved = 0;
    for (int i = n_before + 2; i < W.nlines; i++) if (strcmp(W.lines[i].text, W.lines[i - 1].text)) moved++;
    check(moved >= 10, "readings moved on only %d lines after recovery", moved);
    if (!R->fails)
        note("  line %d (ST:4, -1 values) is the only asleep line. line %d is good again, 2 lines or 4 s after the reset. last line before: %s\n",
             n_before, n_before + 1, W.lines[n_before - 1].text);
    soak_and_finish(1);
    finish();
}
static void sc_reset_ctrl(result_t *r) { (void)r; ctrl_reset_common(0x60); }
static void sc_reset_ctrl_bmp(result_t *r) { (void)r; ctrl_reset_common(0x58); }

/* 8. data line held low: the TWI never completes a transfer */
static void sc_hung_bus(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    char good[200], lost[200];
    expect_good(good, sizeof good, 300, 700, 1);
    expect_lost(lost, sizeof lost, 300, 700);
    run_until(20500);
    int n_before = W.nlines;
    W.bme.bus = BUS_HUNG;
    int s0 = W.nstall;
    run_until(80500);
    int s1 = W.nstall;
    int lines_hung = W.nlines - n_before;
    check(lines_hung >= 28, "only %d lines in 60 s with a hung bus, want about 30: the firmware stopped", lines_hung);
    check(s1 > s0, "the bus-hang model never stalled a transfer, so the timeout was not exercised");
    int bad = -1;
    check(all_equal(n_before, W.nlines, lost, &bad), "line %d during the hang is not the -1 line", bad);
    check(all_st(n_before, W.nlines, ST_BME_MISSING, &bad), "line %d during the hang has ST:%u, want 1", bad, bad < 0 ? 0 : W.lines[bad].st);
    /* a transfer that never completes must be abandoned after the 25 ms Wire timeout and the
     * next transfer must start straight away.  inside one burst the stalls are this far apart. */
    double mn = 1e9, mx = 0; int in = 0;
    for (int i = s0 + 1; i < s1; i++) {
        double d = W.stall_t[i] - W.stall_t[i - 1];
        if (d < 200.0) { in++; if (d < mn) mn = d; if (d > mx) mx = d; }
    }
    note("  %d transfers stalled in 60 s. back-to-back stalls were %.1f to %.1f ms apart (the Wire timeout is %.0f ms).\n",
         s1 - s0, in ? mn : 0.0, in ? mx : 0.0, WIRE_TIMEOUT_MS);
    if (in) check(mn >= WIRE_TIMEOUT_MS - 2.0 && mx <= WIRE_TIMEOUT_MS + 15.0,
                  "stalled transfers were abandoned %.1f to %.1f ms after starting, want about %.0f ms", mn, mx, WIRE_TIMEOUT_MS);
    /* release the line: readings must come back after the retry interval */
    W.bme.bus = BUS_NORMAL;
    double t_back = now_ms();
    run_until(130000);
    int gi = first_good(n_before, good);
    check(gi >= 0, "readings never returned after the bus was released");
    if (gi >= 0) {
        double delay = W.lines[gi].t_first - t_back;
        note("  bus released at %.1f ms; first good line %.1f s later\n", t_back, delay / 1000.0);
        check(delay <= RETRY_INTERVAL_MS + 2 * REPORT_INTERVAL_MS + 500, "recovery took %.1f s", delay / 1000.0);
    }
    soak_and_finish(1);
    finish();
}

/* 8b. the bus is already hung at power-up */
static void sc_hung_boot(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_HUNG);
    run_until(40000);
    char lost[200]; expect_lost(lost, sizeof lost, 300, 700);
    int bad = -1;
    check(W.nlines >= 18, "only %d lines in 40 s with the bus hung from power-up", W.nlines);
    check(all_equal(0, W.nlines, lost, &bad), "line %d is not the -1 line", bad);
    check(all_st(0, W.nlines, ST_BME_MISSING, &bad), "line %d has ST:%u, want 1", bad, bad < 0 ? 0 : W.lines[bad].st);
    check(W.nstall > 0, "no transfer stalled");
    W.bme.bus = BUS_NORMAL;
    double t_back = now_ms();
    run_until(110000);
    char good[200]; expect_good(good, sizeof good, 300, 700, 1);
    int gi = first_good(0, good);
    check(gi >= 0, "readings never appeared after the line was released");
    if (gi >= 0) note("  released at %.1f ms; first good line %.1f s later; %d stalled transfers in total before release\n",
                      t_back, (W.lines[gi].t_first - t_back) / 1000.0, W.nstall);
    soak_and_finish(1);
    finish();
}

/* 9. the raw data freezes.  the readings drift for a minute, then every raw value stops.  the node must
 * report BME_STUCK on the 60th identical read and not before, print -1, try one soft reset in the
 * episode and show good values again on the first read that differs. */
static void sc_stuck(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    W.bme.drift_t = 300; W.bme.drift_p = 200; W.bme.drift_t0_ms = 0; W.bme.drift_on = 1;
    run_until(60500);
    /* freeze half way between two lines so the very next read already sees frozen data */
    run_until(W.lines[W.nlines - 1].t_first + 1000.0);
    int n_pre = W.nlines;
    W.bme.noise_mode = NOISE_NONE;   /* a frozen converter has no noise either */
    bme_freeze(&W.bme);          /* from here the converter returns the same raw data for ever */
    double t_freeze = now_ms();
    run_until(t_freeze + 300000);
    int changes = 0;
    for (int i = 1; i < n_pre; i++) if (strcmp(W.lines[i].text, W.lines[i - 1].text)) changes++;
    check(changes >= 20, "readings moved on only %d of %d lines before the freeze: the test cannot see a freeze", changes, n_pre - 1);
    int bad = -1;
    int fs = -1;
    for (int i = n_pre; i < W.nlines; i++) if (W.lines[i].st & ST_BME_STUCK) { fs = i; break; }
    check(fs >= 0, "BME_STUCK never appeared in %.0f s of frozen data", (now_ms() - t_freeze) / 1000.0);
    if (fs >= 0) {
        check(fs == n_pre + STUCK_READS - 1, "BME_STUCK first on line %d, want line %d (the 60th identical read, %d lines after the freeze)",
              fs, n_pre + STUCK_READS - 1, STUCK_READS - 1);
        check(all_equal(n_pre, fs, W.lines[n_pre].text, &bad), "line %d before the stuck verdict is not identical to its neighbours", bad);
        check(all_st(n_pre, fs, 0, &bad), "line %d before the stuck verdict has ST:%u, want 0 (59 identical reads are not yet stuck)", bad, bad < 0 ? 0 : W.lines[bad].st);
        check(all_st(fs, W.nlines, ST_BME_STUCK, &bad), "line %d after the verdict has ST:%u, want 2", bad, bad < 0 ? 0 : W.lines[bad].st);
        int nlost = 0;
        for (int i = fs; i < W.nlines; i++) if (is_lost(W.lines[i].text)) nlost++;
        check(nlost == W.nlines - fs, "only %d of %d stuck lines carry -1 values", nlost, W.nlines - fs);
        note("  frozen at %.1f ms. %d lines repeated the same good values (reads 1 to 59), line %d is the 60th identical read: '%s'\n"
             "  from there %d lines carry -1 values with ST:2 for %.0f s while the data stays frozen.\n",
             t_freeze, fs - n_pre, fs, W.lines[fs].full, W.nlines - fs, (now_ms() - t_freeze) / 1000.0);
    }
    check(W.bme.n_soft_resets == 1, "%u soft resets (0xE0 = 0xB6) in one stuck episode of %.0f s, want exactly 1", W.bme.n_soft_resets, (now_ms() - t_freeze) / 1000.0);
    note("  soft resets sent to the sensor during the episode: %u (one per episode)\n", W.bme.n_soft_resets);
    /* the data moves again: good values on the first read that differs */
    W.bme.drift_t0_ms = now_ms(); W.bme.drift_on = 1;
    W.bme.noise_mode = NOISE_DITHER;
    int n_rel = W.nlines;
    run_until(now_ms() + 30000);
    check(W.nlines > n_rel + 5, "too few lines after the data moved again");
    int gi = -1;
    for (int i = n_rel; i < W.nlines; i++) if (W.lines[i].st == 0 && !is_lost(W.lines[i].text)) { gi = i; break; }
    check(gi >= 0 && gi <= n_rel + 1, "good values came back at line %d, want within 2 lines of the data moving (line %d)", gi, n_rel);
    if (gi >= 0) check(all_st(gi, W.nlines, 0, &bad), "line %d after the recovery has ST:%u, want 0", bad, bad < 0 ? 0 : W.lines[bad].st);
    note("  data moved again at line %d: good values with ST:0 from line %d, no further reset\n", n_rel, gi);
    check(W.bme.n_soft_resets == 1, "a soft reset was sent while the data was moving (%u in total)", W.bme.n_soft_resets);
    /* a second episode may use one more reset */
    run_until(now_ms() + 1000.0);
    W.bme.noise_mode = NOISE_NONE;
    bme_freeze(&W.bme);
    run_until(now_ms() + 170000);
    check(W.bme.n_soft_resets == 2, "second stuck episode: %u soft resets in total, want 2", W.bme.n_soft_resets);
    int stuck2 = 0;
    for (int i = n_rel + 10; i < W.nlines; i++) if (W.lines[i].st & ST_BME_STUCK) stuck2++;
    check(stuck2 > 10, "BME_STUCK did not return in the second episode");
    note("  second episode: BME_STUCK again and %u soft resets in total\n", W.bme.n_soft_resets);
    soak_and_finish(1);
    finish();
}

/* 9b. a frozen converter that the soft reset cures: BME_STUCK for one line and good values after it */
static void sc_stuck_cured(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    W.bme.drift_t = 300; W.bme.drift_p = 200; W.bme.drift_t0_ms = 0; W.bme.drift_on = 1;
    run_until(30500);
    run_until(W.lines[W.nlines - 1].t_first + 1000.0);
    int n_pre = W.nlines;
    W.bme.frozen_until_reset = 1;
    run_until(now_ms() + 200000);
    int bad = -1;
    int fs = -1;
    for (int i = n_pre; i < W.nlines; i++) if (W.lines[i].st & ST_BME_STUCK) { fs = i; break; }
    /* this model holds the registers as the last read saw them, so that read is already the first of the 30
     * identical ones and the verdict falls one line earlier than in scenario 9 */
    check(fs == n_pre + STUCK_READS - 2, "BME_STUCK first on line %d, want line %d", fs, n_pre + STUCK_READS - 2);
    check(W.bme.n_soft_resets == 1, "%u soft resets, want 1", W.bme.n_soft_resets);
    if (fs >= 0 && fs + 2 < W.nlines) {
        int nstuck = 0;
        for (int i = fs; i < W.nlines; i++) if (W.lines[i].st & ST_BME_STUCK) nstuck++;
        check(nstuck == 1, "%d lines carry BME_STUCK, want 1 because the reset cures the converter", nstuck);
        check(!is_lost(W.lines[fs + 1].text) && W.lines[fs + 1].st == 0, "line %d after the reset is '%s', want good values", fs + 1, W.lines[fs + 1].full);
        check(all_st(fs + 1, W.nlines, 0, &bad), "line %d has ST:%u after the cure, want 0", bad, bad < 0 ? 0 : W.lines[bad].st);
        if (!R->fails)
            note("  the converter froze for %d reads. line %d is the last of them and carries ST:2 and -1. the one soft reset cured it and line %d is good.\n",
                 STUCK_READS, fs, fs + 1);
    }
    soak_and_finish(1);
    finish();
}

/* helpers defined further down */
typedef int (*raw_pred)(int32_t raw, double target);
static int32_t bisect_raw(raw_pred pred, int32_t lo, int32_t hi, double target);
static int p_t_ge(int32_t raw, double c);

/* 9c and 9d. a still room, swept over the noise.  the model follows the oversampling the firmware writes: at pressure x16 and
 * temperature x2 the pressure word has its full 20 bit resolution and the temperature word 17 bits and the noise is the data
 * sheet figure for those settings (pressure 1.3 Pa, temperature 0.004 C, humidity at x1 0.07 %RH, each divided by the
 * resolution to give counts of the raw word), scaled to 1, a half, a fifth, a tenth and a twentieth, for ten minutes each.  9c
 * is a BME280 and 9d a BMP280 (temperature and pressure only, the harder case).  the longest run of identical raw reads is
 * reported against the limit of 60.  at the data sheet noise and at half of it a verdict of BME_STUCK is a failure.  below that
 * a verdict is a FINDING with the numbers and the model is not tuned to hide it. */
static void still_room(uint8_t chip, double scale)
{
    boot(chip, 0x76, BUS_NORMAL);
    W.bme.noise_mode = NOISE_GAUSS;
    W.bme.noise_scale = scale;
    run_until(600000.0);
    int bad = -1;
    check(W.nlines >= 290, "only %d lines in ten minutes", W.nlines);
    int nstuck = 0, nlost = 0;
    for (int i = 0; i < W.nlines; i++) { if (W.lines[i].st & ST_BME_STUCK) nstuck++; if (is_lost(W.lines[i].text)) nlost++; }
    check(W.bme.n_raw_packs >= 290, "the model produced only %u conversions", W.bme.n_raw_packs);
    unsigned longest = W.bme.longest_same_run;
    char hum_txt[40] = "";
    if (chip == 0x60) snprintf(hum_txt, sizeof hum_txt, ", humidity %.2f", 8.75 * scale);
    note("  noise %.1f x the data sheet figure (pressure %.2f, temperature %.2f counts of the raw word, rms%s). %u reads in %.0f s,"
         " raw bytes changed on %u of them.\n"
         "  longest run of identical reads %u against the limit of %d. lines with BME_STUCK: %d. soft resets sent: %u.\n",
         scale, 8.13 * scale, 1.60 * scale, hum_txt, W.bme.n_raw_packs, now_ms() / 1000.0,
         W.bme.n_raw_changes, longest, STUCK_READS, nstuck, W.bme.n_soft_resets);
    if (nstuck > 0 && scale >= 0.5) {
        check(0, "BME_STUCK on %d lines in a still room at %.1f x the data sheet noise (longest identical run %u)", nstuck, scale, longest);
    } else if (nstuck > 0) {
        g_finding = 1;
        note("  FINDING: a healthy part at %.1f x the data sheet noise reached the limit (longest run %u of %d) and was called stuck\n"
             "  on %d line(s) with %u soft reset(s). the model is not tuned to hide it. a test that compares the run against the longest\n"
             "  run seen while healthy would not have this limit.\n", scale, longest, STUCK_READS, nstuck, W.bme.n_soft_resets);
    } else {
        check(all_st(0, W.nlines, 0, &bad), "line %d has ST:%u in a still room, want 0 on every line: %s", bad, bad < 0 ? 0 : W.lines[bad].st, bad < 0 ? "" : W.lines[bad].full);
        check(nlost == 0, "%d lines carry -1 in a still room", nlost);
        check(W.bme.n_soft_resets == 0, "the firmware soft-reset a healthy sensor %u time(s)", W.bme.n_soft_resets);
        if (scale < 0.5) g_observation = 1;   /* below half the data sheet noise a stuck verdict is only ever reported as a finding, so the sweep cannot fail on it */
    }
    soak_and_finish(1);
    finish();
}
static void sc_still_100(result_t *r)  { (void)r; still_room(0x60, 1.0); }
static void sc_still_50(result_t *r)   { (void)r; still_room(0x60, 0.5); }
static void sc_still_20(result_t *r)   { (void)r; still_room(0x60, 0.2); }
static void sc_still_10(result_t *r)   { (void)r; still_room(0x60, 0.1); }
static void sc_still_05(result_t *r)   { (void)r; still_room(0x60, 0.05); }
static void sc_still_bmp_100(result_t *r) { (void)r; still_room(0x58, 1.0); }
static void sc_still_bmp_50(result_t *r)  { (void)r; still_room(0x58, 0.5); }
static void sc_still_bmp_20(result_t *r)  { (void)r; still_room(0x58, 0.2); }
static void sc_still_bmp_10(result_t *r)  { (void)r; still_room(0x58, 0.1); }
static void sc_still_bmp_05(result_t *r)  { (void)r; still_room(0x58, 0.05); }

/* 9e. raw words replayed from a file logged from a real part.  no such file is in the repository: this only runs when the
 * harness is given one with --replay (three whole numbers per line: the 20 bit pressure word, the 20 bit temperature word
 * and the 16 bit humidity word of one conversion).  it must never set BME_STUCK. */
static void sc_replay(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    int n = bme_load_replay(&W.bme, g_replay);
    check(n > 0, "cannot read the replay file %s", g_replay ? g_replay : "(none)");
    run_until(1800000.0);
    int nstuck = 0;
    for (int i = 0; i < W.nlines; i++) if (W.lines[i].st & ST_BME_STUCK) nstuck++;
    check(nstuck == 0, "BME_STUCK on %d lines while replaying a real part", nstuck);
    note("  replayed %d logged conversions (looped) for %.0f s. longest run of identical reads %u of %d. BME_STUCK lines: %d\n",
         n, now_ms() / 1000.0, W.bme.longest_same_run, STUCK_READS, nstuck);
    soak_and_finish(1);
    finish();
}

/* 17. negative temperatures.  a real -1.0 C prints as TEMP:-1.0 and is a reading: ST says so, the text does not.  the line
 * for -0.9, -1.0, -1.1, -10.0 and -39.9 C must be exactly right with ST:0. */
static void sc_negative(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    W.bme.noise_mode = NOISE_NONE;
    static const double targets[] = {-0.9, -1.0, -1.1, -10.0, -39.9};
    run_until(5000);
    for (unsigned k = 0; k < sizeof targets / sizeof targets[0]; k++) {
        int32_t raw = bisect_raw(p_t_ge, 0, 1000000, targets[k]);
        check(raw >= 0, "no raw word for %.1f C", targets[k]);
        raw = ((raw + 4) >> 3) << 3;                       /* temperature at x2 is a 17 bit word: the low three bits are zero */
        bme_set_raw(&W.bme, raw, BME_NOMINAL_RAW_P, BME_EXAMPLE_RAW_H);
        double t0 = now_ms();
        run_until(t0 + 11000);
        int32_t tf; int32_t tc = ref_t_int32(raw, &tf);
        double pa = ref_p_pa32(BME_NOMINAL_RAW_P, tf); double hq = ref_h_pct(BME_EXAMPLE_RAW_H, tf);
        char t[24], p[24], h[24], want[200];
        fmt1(t, sizeof t, tc / 100.0); fmt1(p, sizeof p, pa / 100.0); fmt1(h, sizeof h, hq);
        expect_line(want, sizeof want, t, h, p, 300, 700, 0);
        int nl = 0;
        for (int i = 0; i < W.nlines; i++) {
            line_t *l = &W.lines[i];
            if (l->t_first < t0 + 2500.0) continue;
            nl++;
            check(l->st == 0 && !strcmp(l->text, want), "at %.2f C line %d is '%s', want '%s' with ST:0", tc / 100.0, i, l->full, want);
        }
        check(nl >= 3, "only %d lines at %.1f C", nl, targets[k]);
        note("  %6.2f C: %d lines, ST:0, exactly '%s'\n", tc / 100.0, nl, want);
    }
    soak_and_finish(1);
    finish();
}

/* 7d. a part that falls asleep after every third read.  one repaired sleep is one line with ST:4 and that is all the hub
 * will see as a glitch.  a part that keeps doing it must show on consecutive lines: the second sleep within ten reads holds
 * BME_ASLEEP, with no values, for five more lines. */
static void sc_flapping(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    W.bme.drift_t = 300; W.bme.drift_p = 200; W.bme.drift_t0_ms = 0; W.bme.drift_on = 1;
    run_until(8000);
    int n0 = W.nlines;
    W.bme.sleep_every = 3;
    run_until(8000 + 130000);
    int run = 0, longest = 0, total = 0;
    for (int i = n0; i < W.nlines; i++) {
        if (W.lines[i].st & ST_BME_ASLEEP) { run++; total++; if (run > longest) longest = run; } else run = 0;
    }
    check(longest >= 2, "BME_ASLEEP never showed on two lines in a row (longest run %d): a flapping part would never be reported", longest);
    int bad_form = 0;
    for (int i = n0; i < W.nlines; i++) if ((W.lines[i].st & ST_BME_ASLEEP) && !is_lost(W.lines[i].text)) bad_form++;
    check(bad_form == 0, "%d asleep lines carry values", bad_form);
    note("  the part fell asleep after every third read: %d of %d lines carried BME_ASLEEP, in runs of up to %d consecutive lines.\n  ST of the first lines of the pattern:", total, W.nlines - n0, longest);
    for (int i = n0; i < n0 + 16 && i < W.nlines; i++) note(" %u", W.lines[i].st);
    note("\n");
    /* stop the flapping: the bit clears within the hold time */
    W.bme.sleep_every = 0;
    int n1 = W.nlines;
    run_until(now_ms() + 40000);
    int last_asleep = -1;
    for (int i = n1; i < W.nlines; i++) if (W.lines[i].st & ST_BME_ASLEEP) last_asleep = i;
    check(last_asleep < n1 + 7, "BME_ASLEEP was still set %d lines after the flapping stopped", last_asleep - n1);
    int bad = -1;
    check(all_st(n1 + 8, W.nlines, 0, &bad), "line %d after the part settled has ST:%u, want 0", bad, bad < 0 ? 0 : W.lines[bad].st);
    soak_and_finish(1);
    finish();
}

/* 18. the sensor is swapped for another part while the node runs.  the new part is a BMP280 with a different calibration, then
 * a BME280 again.  within a few lines the values must follow the new part's own calibration, with HUM:-1 while it is the
 * BMP280.  the old calibration must not stay. */
static void sc_swap(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    W.bme.noise_mode = NOISE_NONE;
    run_until(9000);
    char good_a[200]; expect_good(good_a, sizeof good_a, 300, 700, 1);
    int bad = -1;
    check(all_equal(0, W.nlines, good_a, &bad), "line %d before the swap is wrong", bad);
    struct { const char *name; uint8_t chip; int set; } step[] = {
        {"BMP280 with calibration B", 0x58, 1}, {"BME280 with calibration A", 0x60, 0},
    };
    for (int k = 0; k < 2; k++) {
        g_calib = step[k].set ? &BME_CALIB_ALT : &BME_CALIB;
        bme_swap(&W.bme, step[k].chip, step[k].set);
        double t0 = now_ms();
        int n0 = W.nlines;
        run_until(t0 + 30000);   /* long enough that the second swap is not a flapping part */
        char want[200]; expect_good(want, sizeof want, 300, 700, step[k].chip == 0x60);
        int nasleep = 0, ngood = 0;
        for (int i = n0; i < W.nlines; i++) {
            if (W.lines[i].st & ST_BME_ASLEEP) nasleep++;
            else if (W.lines[i].st == 0) { ngood++; check(!strcmp(W.lines[i].text, want), "after the swap to the %s line %d is '%s', want '%s'", step[k].name, i, W.lines[i].text, want); }
            else check(0, "after the swap line %d has ST:%u", i, W.lines[i].st);
        }
        check(nasleep == 1, "%d asleep lines after the swap, want 1", nasleep);
        check(ngood >= 4, "only %d good lines after the swap", ngood);
        note("  swapped to the %s: 1 line of ST:4, then %d good lines equal to '%s'\n", step[k].name, ngood, want);
    }
    g_calib = &BME_CALIB;
    soak_and_finish(1);
    finish();
}

/* 10. analogue inputs and pin 7 */
static void expect_analog(int light, int moist, int wait_from_line)
{
    char t[24], p[24], h[24];
    ref_t ref = reference(W.bme.raw_t, W.bme.raw_p, W.bme.raw_h);
    fmt1(t, sizeof t, ref.temp); fmt1(p, sizeof p, ref.pres32_hpa); fmt1(h, sizeof h, ref.hum);
    char want[200];
    expect_line(want, sizeof want, t, h, p, light, moist, moist < 500 ? 1 : 0);
    int n = W.nlines;
    check(n > wait_from_line, "no line produced for LIGHT=%d MOIST=%d", light, moist);
    if (n > wait_from_line)
        check(!strcmp(W.lines[n - 1].text, want), "applied LDR %d and moisture %d: printed '%s', want '%s'",
              light, moist, W.lines[n - 1].text, want);
}

static void sc_analog(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    static const int ldr[] = {0, 511, 1023, 1};
    static const int moist[] = {0, 499, 500, 1023};
    double t = 0;
    /* LDR at 0 V, mid-scale, full scale; moisture dry so WATER is 0 */
    for (unsigned i = 0; i < sizeof ldr / sizeof ldr[0]; i++) {
        set_adc_count(0, ldr[i]); set_adc_count(1, 700);
        t += 6000; run_until(t + 3000);
        expect_analog(ldr[i], 700, 0);
        t += 3000;
    }
    /* moisture across the water threshold of 500 */
    set_adc_count(0, 300);
    for (unsigned i = 0; i < sizeof moist / sizeof moist[0]; i++) {
        set_adc_count(1, moist[i]);
        t += 6000; run_until(t + 3000);
        expect_analog(300, moist[i], 0);
        t += 3000;
    }
    run_until(t + 3000);
    /* ADC conversion check: what simavr returned for each applied voltage, taken from the log */
    int ch0 = 0, ch1 = 0;
    for (int i = 0; i < W.nconv; i++) { if (W.conv[i].ch == 0) ch0++; else if (W.conv[i].ch == 1) ch1++; }
    check(ch0 > 8 && ch1 > 8, "too few conversions logged (A0 %d, A1 %d)", ch0, ch1);
    note("  conversions logged: %d on A0 and %d on A1\n", ch0, ch1);
    /* pin 7: high before every moisture conversion for the settle time and low after it */
    int bad_high = 0, bad_settle = 0, bad_low = 0, bad_ldr = 0, bad_fall = 0;
    double min_settle = 1e9;
    for (int i = 0; i < W.nconv; i++) {
        conv_t *c = &W.conv[i];
        if (c->kind != ADC_MUX_SINGLE) continue;
        if (c->ch == 1) {
            if (!c->pin7) bad_high++;
            double settle = c->t - c->pin7_since;
            if (settle < min_settle) min_settle = settle;
            if (settle < MOISTURE_SETTLE_MS - 1.0) bad_settle++;
            /* the next pin event after the conversion must be the fall, soon after */
            double fall = -1;
            for (int k = 0; k < W.npin; k++) if (W.pin[k].t > c->t - 0.0001 && W.pin[k].level == 0) { fall = W.pin[k].t; break; }
            if (fall < 0 || fall - c->t > 2.0) bad_fall++;
        } else if (c->ch == 0) {
            if (c->pin7) bad_ldr++;
        }
    }
    for (int i = 0; i < W.nlines; i++) {
        /* at the start of every line pin 7 must be low again */
        int level = 0;
        for (int k = 0; k < W.npin; k++) if (W.pin[k].t <= W.lines[i].t_first) level = W.pin[k].level;
        if (level) bad_low++;
    }
    /* the supply measurement shares the ADC.  every pin conversion must have the multiplexer on its own
     * pin and AVcc as the reference (so the band gap measurement was undone) and every band gap
     * conversion must have selected the band gap with the same reference.  three band gap conversions
     * run per pass: the first is discarded by the firmware and the other two are the pair that must agree. */
    {
        int bad_mux = 0, n_ref = 0, bad_ref = 0, n_pin = 0;
        for (int i = 0; i < W.nconv; i++) {
            conv_t *c = &W.conv[i];
            if (c->kind == ADC_MUX_SINGLE) {
                n_pin++;
                if ((c->admux & 0xC0) != 0x40 || (c->admux & 0x0F) != (unsigned)c->ch) bad_mux++;
            } else if (c->kind == ADC_MUX_REF) {
                n_ref++;
                if (c->admux != 0x4E) bad_ref++;
            }
        }
        check(bad_mux == 0, "%d LDR or moisture conversions did not have AVcc as the reference and their own pin selected", bad_mux);
        check(bad_ref == 0, "%d band gap conversions did not have ADMUX 0x4E (AVcc reference, 1.1 V input)", bad_ref);
        check(n_ref >= 3 * W.nlines - 3 && n_ref <= 3 * W.nlines + 6, "%d band gap conversions for %d lines, want three per pass (one discarded and two that agree)", n_ref, W.nlines);
        /* every pin conversion is a pair: one discarded and one used */
        note("  ADC share: %d pin conversions (a discarded one and a used one per read) all with ADMUX = AVcc reference and their own pin,\n"
             "  %d band gap conversions all with ADMUX 0x4E. the LDR and moisture counts printed above equal the counts applied on every line,\n"
             "  so the supply measurement leaves them unchanged.\n", n_pin, n_ref);
    }
    check(bad_high == 0, "%d moisture conversions ran with pin 7 low", bad_high);
    check(bad_settle == 0, "%d moisture conversions came less than %.0f ms after pin 7 went high", bad_settle, MOISTURE_SETTLE_MS);
    check(bad_fall == 0, "%d moisture conversions were not followed by pin 7 going low within 2 ms", bad_fall);
    check(bad_ldr == 0, "%d LDR conversions ran with pin 7 high", bad_ldr);
    check(bad_low == 0, "pin 7 was still high when %d lines started", bad_low);
    note("  pin 7: %d level changes; shortest high-to-conversion settle %.1f ms (the firmware waits %.0f ms); every conversion and line checked\n",
         W.npin, min_settle, MOISTURE_SETTLE_MS);
    /* the probe is read only while powered: with pin 7 low the harness feeds 0 V, so a read
     * taken unpowered would print 0 and fail the value checks above */
    soak_and_finish(1);
    finish();
}

/* 10b. the supply at 4.2 V, 5.0 V and 5.8 V and across the 4500 and 5500 mV limits.
 *
 * how it is modelled: simavr gives the ADC its band gap input itself, as a fixed 1100 mV measured
 * against whichever reference ADMUX selects.  the firmware selects AVcc, so moving the simulated AVcc
 * moves the count the firmware sees (1100 * 1023 / AVcc) exactly as a falling or rising supply would.
 * the harness sets AVcc, AREF and VCC together and re-applies the LDR and moisture voltages in the same
 * ratio so those counts stay 300 and 700.
 *
 * what it does not prove: the simulated band gap is exactly 1100 mV where a real chip is 1.0 to 1.2 V,
 * so the calibration error is invisible here.  simavr's conversion divides by 1023 where a real ADC divides
 * by 1024, which reads the supply about 0.1 per cent high.  there is no ADC noise, no settling error and no
 * supply ripple. the BME280 model does not care about the supply. */
static void sc_supply(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    /* the limits depend on the build: 4000 and 6000 mV until the band gap is calibrated, 4500 and 5500 after */
    static const unsigned phase_def[] = {5000, 4200, 5800, 3800, 4200, 5800, 6200, 5000};
    static const unsigned phase_cal[] = {5000, 4200, 5800, 4400, 4600, 5400, 5600, 5000};
    const unsigned *phase_mv = g_is_cal ? phase_cal : phase_def;
    const unsigned lim_lo = g_is_cal ? 4500 : 4000, lim_hi = g_is_cal ? 5500 : 6000;
    const int nphase = 8;
    char good[200]; expect_good(good, sizeof good, 300, 700, 1);
    run_until(6000);
    note("  applied mV   VCC read (min..max)   error     ST   lines\n");
    for (int k = 0; k < nphase; k++) {
        unsigned v = phase_mv[k];
        W.vcc_mv = v;
        W.avr->vcc = W.avr->avcc = W.avr->aref = (uint16_t)v;
        set_adc_count(0, 300); set_adc_count(1, 700);
        double t0 = now_ms();
        run_until(t0 + 11000);
        int want_range = (v < lim_lo || v > lim_hi) ? 1 : 0;
        /* the expected VCC from the applied voltage alone, by the arithmetic of the method and not from the firmware: simavr
         * converts the 1100 mV band gap against AVcc to whole counts (rounding down) and the supply follows as 1.1 V * 1024
         * divided by those counts.  the expected status comes from the applied voltage and the limits of the build. */
        double counts = floor(1100.0 * 1023.0 / (double)v);
        unsigned want_vcc = (unsigned)(1100.0 * 1024.0 / counts);
        int nl = 0, bad = 0; unsigned vmin = 99999, vmax = 0;
        for (int i = 0; i < W.nlines; i++) {
            line_t *l = &W.lines[i];
            if (l->t_first < t0 + 4000.0 || !l->has_tail) continue;   /* skip the line that straddles the change */
            nl++;
            if (l->vcc < vmin) vmin = l->vcc;
            if (l->vcc > vmax) vmax = l->vcc;
            if (l->vcc != want_vcc) bad++;
            check(l->st == (want_range ? ST_SUPPLY_RANGE : 0u), "at %u mV line %d has ST:%u, want %u", v, i, l->st, want_range ? ST_SUPPLY_RANGE : 0u);
            check(!strcmp(l->text, good), "at %u mV line %d is '%s', want '%s': the LDR or moisture count moved", v, i, l->text, good);
        }
        check(nl >= 3, "only %d lines at %u mV", nl, v);
        check(bad == 0, "%d lines at %u mV did not read VCC %u, the value that follows from the applied voltage", bad, v, want_vcc);
        note("  %9u   %5u..%-5u          %+6.2f%%   %3d   %3d\n", v, vmin, vmax, nl ? ((double)vmax - (double)v) * 100.0 / (double)v : 0.0, want_range ? ST_SUPPLY_RANGE : 0, nl);
    }
    note("  limits of this build: SUPPLY_RANGE under %u or over %u mV. VCC is printed as measured either way. the LDR and moisture counts printed are 300 and 700 at every voltage.\n", lim_lo, lim_hi);
    W.vcc_mv = 5000;
    soak_and_finish(1);
    finish();
}

/* 12. BME_RANGE: a compensated value outside the data sheet range.  the expected status comes from the
 * harness's own data sheet maths, so a raw word is only used where that maths says it is out of range. */
static int32_t ref_h_q22(int32_t adc_H, int32_t t_fine)
{
    const bme_calib_t *c = g_calib;
    int32_t v = t_fine - 76800;
    v = (((((adc_H << 14) - (((int32_t)c->H4) << 20) - (((int32_t)c->H5) * v)) + 16384) >> 15)
         * (((((((v * (int32_t)c->H6) >> 10) * (((v * (int32_t)c->H3) >> 11) + 32768)) >> 10) + 2097152)
              * (int32_t)c->H2 + 8192) >> 14));
    return v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)c->H1) >> 4);   /* not clamped */
}

static unsigned expected_range_st(int32_t rt, int32_t rp, int32_t rh, int has_hum)
{
    int32_t tf; int32_t tc = ref_t_int32(rt, &tf);
    double pa = ref_p_pa32(rp, tf);
    int out = tc < -4000 || tc > 8500 || pa < 30000.0 || pa > 110000.0;
    if (has_hum) { int32_t v = ref_h_q22(rh, tf); if (v < -5 * 4194304 || v > 105 * 4194304) out = 1; }   /* under -5 or over 105 per cent */
    return out ? ST_BME_RANGE : 0;
}

/* the first raw value from lo up to hi where pred() is true, by bisection (pred is monotone) */
static int32_t bisect_raw(raw_pred pred, int32_t lo, int32_t hi, double target)
{
    if (!pred(hi, target) || pred(lo, target)) return -1;
    while (hi - lo > 1) { int32_t mid = lo + (hi - lo) / 2; if (pred(mid, target)) hi = mid; else lo = mid; }
    return hi;
}
static int p_t_ge(int32_t raw, double c) { int32_t tf; return ref_t_int32(raw, &tf) >= (int32_t)(c * 100.0); }
static int p_p_le(int32_t raw, double hpa) { int32_t tf; ref_t_int32(BME_EXAMPLE_RAW_T, &tf); return ref_p_pa32(raw, tf) <= hpa * 100.0; }
static int p_h_ge(int32_t raw, double pct) { int32_t tf; ref_t_int32(BME_EXAMPLE_RAW_T, &tf); return (double)ref_h_q22(raw, tf) >= pct * 4194304.0; }

static void sc_range(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    char good[200]; expect_good(good, sizeof good, 300, 700, 1);
    int32_t t_hot = bisect_raw(p_t_ge, 100000, 1000000, 95.0);
    int32_t t_cold = bisect_raw(p_t_ge, 0, 1000000, -50.0);
    /* pressure falls as the raw word rises */
    int32_t p_low = bisect_raw(p_p_le, 200000, 1000000, 200.0);
    int32_t p_hi_edge = bisect_raw(p_p_le, 200000, 1000000, 1300.0);
    int32_t h_100_5 = bisect_raw(p_h_ge, 0, 65535, 100.5);
    int32_t h_104_9 = bisect_raw(p_h_ge, 0, 65535, 104.9);
    int32_t h_105_1 = bisect_raw(p_h_ge, 0, 65535, 105.1);
    int32_t h_m5_1 = bisect_raw(p_h_ge, 0, 65535, -5.1);   /* first raw at or above -5.1 per cent */
    if (h_m5_1 > 0) h_m5_1 -= 1;                          /* the one before it is under -5.1 */
    struct { const char *name; int32_t t, p, h; unsigned want; } ph[] = {
        {"temperature above 85 C",       t_hot,  BME_NOMINAL_RAW_P, BME_EXAMPLE_RAW_H, 0},
        {"temperature below -40 C",      t_cold, BME_NOMINAL_RAW_P, BME_EXAMPLE_RAW_H, 0},
        {"pressure below 300 hPa",       BME_EXAMPLE_RAW_T, p_low,  BME_EXAMPLE_RAW_H, 0},
        {"pressure above 1100 hPa",      BME_EXAMPLE_RAW_T, p_hi_edge, BME_EXAMPLE_RAW_H, 0},
        {"humidity 100.5 per cent",      BME_EXAMPLE_RAW_T, BME_NOMINAL_RAW_P, h_100_5, 0},
        {"humidity 104.9 per cent",      BME_EXAMPLE_RAW_T, BME_NOMINAL_RAW_P, h_104_9, 0},
        {"humidity 105.1 per cent",      BME_EXAMPLE_RAW_T, BME_NOMINAL_RAW_P, h_105_1, 0},
        {"humidity -5.1 per cent",       BME_EXAMPLE_RAW_T, BME_NOMINAL_RAW_P, h_m5_1, 0},
    };
    const int nph = (int)(sizeof ph / sizeof ph[0]);
    for (int k = 0; k < nph; k++) {
        int found = ph[k].t >= 0 && ph[k].p >= 0 && ph[k].h >= 0;
        check(found, "the harness found no raw word for %s", ph[k].name);
        if (!found) { finish(); return; }
        ph[k].want = expected_range_st(ph[k].t, ph[k].p, ph[k].h, 1);
        /* cases 4 and 5 (100.5 and 104.9 per cent) are inside the band and the rest are out of range */
        unsigned intended = (k == 4 || k == 5) ? 0 : ST_BME_RANGE;
        check(ph[k].want == intended, "the harness's own data sheet maths gives status %u for raw (%d,%d,%d) (%s), want %u", ph[k].want, ph[k].t, ph[k].p, ph[k].h, ph[k].name, intended);
    }
    run_until(8000);
    note("  case                          raw T/P/H                  reference value (data sheet maths)         ST seen  lines\n");
    for (int k = 0; k < nph; k++) {
        double t0 = now_ms();
        bme_set_raw(&W.bme, ph[k].t, ph[k].p, ph[k].h);
        run_until(t0 + 11000);
        int32_t tf; int32_t tc = ref_t_int32(ph[k].t, &tf);
        double pa = ref_p_pa32(ph[k].p, tf); double hq = (double)ref_h_q22(ph[k].h, tf) / 4194304.0;
        int nl = 0; unsigned st_seen = 0;
        for (int i = 0; i < W.nlines; i++) {
            line_t *l = &W.lines[i];
            if (l->t_first < t0 + 2500.0) continue;
            nl++; st_seen = l->st;
            if (ph[k].want) {
                check(l->st == ST_BME_RANGE, "%s: line %d has ST:%u, want 64: %s", ph[k].name, i, l->st, l->full);
                check(is_lost(l->text), "%s: line %d does not carry -1 values: %s", ph[k].name, i, l->full);
            } else {
                /* inside the band: no bit, all three values present and the humidity clamped to 0 to 100 */
                char t[24], p[24], h[24], want[200];
                int32_t tf2; ref_t_int32(ph[k].t, &tf2);
                fmt1(t, sizeof t, ref_t_int32(ph[k].t, &tf2) / 100.0); fmt1(p, sizeof p, ref_p_pa32(ph[k].p, tf2) / 100.0);
                fmt1(h, sizeof h, hq < 0 ? 0 : hq > 100 ? 100 : hq);
                expect_line(want, sizeof want, t, h, p, 300, 700, 0);
                check(l->st == 0 && !strcmp(l->text, want), "%s: line %d is '%s', want '%s' with ST:0", ph[k].name, i, l->full, want);
            }
        }
        check(nl >= 3, "%s: only %d lines", ph[k].name, nl);
        note("  %-28s %7d/%7d/%5d   %7.2f C %8.2f hPa %7.2f %%RH   %3u     %d\n", ph[k].name, ph[k].t, ph[k].p, ph[k].h, tc / 100.0, pa / 100.0, hq, st_seen, nl);
        /* back to normal: good values on the next read and ST 0 */
        bme_set_raw(&W.bme, BME_EXAMPLE_RAW_T, BME_NOMINAL_RAW_P, BME_EXAMPLE_RAW_H);
        double t1 = now_ms();
        run_until(t1 + 9000);
        int ng = 0;
        for (int i = 0; i < W.nlines; i++) {
            line_t *l = &W.lines[i];
            if (l->t_first < t1 + 2500.0) continue;
            ng++;
            check(l->st == 0 && !strcmp(l->text, good), "%s: after the value came back line %d is '%s', want '%s' with ST:0", ph[k].name, i, l->full, good);
        }
        check(ng >= 2, "%s: only %d good lines after recovery", ph[k].name, ng);
    }
    note("  BME_RANGE is set from the first read of an impossible value and the three values are -1. humidity inside -5 to 105 per cent sets nothing and prints clamped to 0 to 100. the next in-range read clears the bit.\n");
    soak_and_finish(1);
    finish();
}

/* ---- ping ---------------------------------------------------------------------------- */
typedef struct { unsigned n; double t_req; } sent_t;
static sent_t g_sent[MAX_PONGS]; static int g_nsent;

static void send_ping_raw(unsigned n, const char *term)
{
    char b[40]; snprintf(b, sizeof b, "PING:%u%s", n, term);
    double t = uart_text(b);
    if (g_nsent < MAX_PONGS) { g_sent[g_nsent].n = n; g_sent[g_nsent].t_req = t; g_nsent++; }
}
static void send_ping(unsigned n) { send_ping_raw(n, "\n"); }

/* run until the firmware has sent `target` pongs in all, up to limit_ms */
static int wait_pongs(int target, double limit_ms)
{
    double end = now_ms() + limit_ms;
    while (W.npongs < target && now_ms() < end) run_until(now_ms() + 0.5);
    return W.npongs >= target;
}

/* every ping sent so far was answered once, in order, with its own number, within 500 ms of its last byte */
static void check_pongs(double *worst, double *mean)
{
    double w = 0, sum = 0;
    check(W.npongs == g_nsent, "%d ping(s) sent and %d pong(s) came back", g_nsent, W.npongs);
    int n = W.npongs < g_nsent ? W.npongs : g_nsent;
    for (int i = 0; i < n; i++) {
        double lat = W.pongs[i].t_end - g_sent[i].t_req;
        if (W.pongs[i].n != g_sent[i].n) check(0, "pong %d answers %u, want %u", i, W.pongs[i].n, g_sent[i].n);
        if (lat > PING_LIMIT_MS || lat < 0) check(0, "ping %d (PING:%u) was answered after %.1f ms, the limit is %.0f ms", i, g_sent[i].n, lat, PING_LIMIT_MS);
        if (lat > w) w = lat;
        sum += lat;
    }
    *worst = w; *mean = n ? sum / n : 0;
}

/* 13. ping: a sweep of ping times across the 2 s cycle, pings sent while a line is being sent, three in a
 * row, a slow ping, a CR LF ping and a fast stream.  every one is answered within 500 ms and the data lines
 * keep SEQ and the 2 s rhythm (the checks that every scenario runs). */
static void sc_ping(result_t *r)
{
    (void)r;
    g_nsent = 0;
    boot(0x60, 0x76, BUS_NORMAL);
    run_until(4000);
    /* sweep: a ping every 2100 ms moves its place in the 2000 ms cycle by 100 ms each time */
    for (int k = 0; k < 25; k++) {
        run_until(4000.0 + 2100.0 * k);
        unsigned n = k == 0 ? 0u : k == 1 ? 65535u : (unsigned)(k * 2617u);
        send_ping(n);
        wait_pongs(g_nsent, 700.0);
    }
    double w = 0, m = 0;
    check_pongs(&w, &m);
    note("  sweep of %d pings across the 2 s cycle (PING:0 and PING:65535 among them): worst answer %.1f ms, mean %.1f ms\n", g_nsent, w, m);

    /* sent while the firmware is part way through sending a data line */
    for (int k = 0; k < 6; k++) {
        run_until(now_ms() + 700.0 + 130.0 * k);
        int mid = wait_mid_line(3000.0);
        check(mid, "never saw a data line in progress (mid-line ping %d)", k);
        int on_wire = W.curlen;
        send_ping(1000u + (unsigned)k);
        wait_pongs(g_nsent, 700.0);
        if (k == 0) note("  mid-line: the first of 6 such pings was sent with %d characters of a data line already sent\n", on_wire);
    }
    /* three in a row, back to back */
    run_until(now_ms() + 1000.0);
    send_ping(11); send_ping(12); send_ping(13);
    wait_pongs(g_nsent, 700.0);
    /* three in a row while a line is being sent */
    run_until(now_ms() + 600.0);
    wait_mid_line(3000.0);
    send_ping(21); send_ping(22); send_ping(23);
    wait_pongs(g_nsent, 700.0);
    /* CR LF line ending */
    run_until(now_ms() + 500.0);
    send_ping_raw(31, "\r\n");
    wait_pongs(g_nsent, 700.0);
    /* a slow sender: one byte every 150 ms, so the ping spans a data line and several passes of the loop */
    run_until(now_ms() + 300.0);
    {
        const char *slow = "PING:42\n";
        double t = 0;
        for (size_t i = 0; i < strlen(slow); i++) t = uart_send(slow + i, 1, 150.0);
        g_sent[g_nsent].n = 42; g_sent[g_nsent].t_req = t; g_nsent++;
        wait_pongs(g_nsent, 700.0);
    }
    check_pongs(&w, &m);
    note("  all %d pings so far answered once and in order: worst %.1f ms, mean %.1f ms (limit %.0f ms). mid-line, three in a row (twice), CR LF and slow pings included\n", g_nsent, w, m, PING_LIMIT_MS);

    /* a fast stream: one ping every 300 ms for a minute.  the rhythm check at the end covers this stretch */
    int storm0 = g_nsent;
    double ts = now_ms();
    for (int k = 0; k < 200; k++) {
        run_until(ts + 300.0 * k);
        send_ping((unsigned)(5000 + k));
    }
    wait_pongs(g_nsent, 800.0);
    check_pongs(&w, &m);
    note("  stream of %d pings, one every 300 ms for %.0f s: all answered, worst %.1f ms over everything sent\n", g_nsent - storm0, (now_ms() - ts) / 1000.0, w);
    note("  pongs seen: %d, data lines seen: %d. every data line still has SEQ in order, so a pong never moved SEQ\n", W.npongs, W.nlines);
    soak_and_finish(1);
    finish();
}

/* 13b. the same with the bus hung, the slowest pass the firmware can have: three failed reads then the
 * 30 s probe of both addresses.  a ping every 2.1 s for 100 s */
static void sc_ping_hung(result_t *r)
{
    (void)r;
    g_nsent = 0;
    boot(0x60, 0x76, BUS_NORMAL);
    run_until(5000);
    W.bme.bus = BUS_HUNG;
    for (int k = 0; k < 48; k++) {
        run_until(6000.0 + 2100.0 * k);
        send_ping((unsigned)(100 + k));
        wait_pongs(g_nsent, 700.0);
    }
    double w = 0, m = 0;
    check_pongs(&w, &m);
    check(W.nstall > 3, "the hung bus was never exercised");
    note("  %d pings with the data line held low (%d transfers stalled, 25 ms timeout each, including the 30 s probe of both addresses): worst %.1f ms, mean %.1f ms\n",
         g_nsent, W.nstall, w, m);
    soak_and_finish(1);
    finish();
}

/* 14. garbage and over-long input is ignored: no pong for any of it, no effect on the lines. a good ping
 * afterwards is still answered. */
static void sc_garbage(result_t *r)
{
    (void)r;
    g_nsent = 0;
    boot(0x60, 0x76, BUS_NORMAL);
    run_until(3000);
    static const char *junk[] = {
        "hello\n", "PING\n", "PING:\n", "PING:abc\n", "PING:70000\n", "PING:65536\n", "PING:123456\n", "ping:1\n",
        " PING:2\n", "PING:3 \n", "PING:4x\n", "PONG:5\n", "PING::6\n", "PING:-7\n", "\n", "\r\n", "PINGPING:8\n",
        "PING:1234567\n",            /* exactly 12 characters before the newline: fills the buffer */
        "PING:12345678\n",           /* 13 characters: overflows it */
        "XPING:9\n", "PING:9;PING:9\n",
    };
    for (unsigned i = 0; i < sizeof junk / sizeof junk[0]; i++) uart_text(junk[i]);
    /* binary noise */
    { static const char bin[] = {(char)0xFF, 0x00, 0x01, (char)0xFE, (char)0x80, 0x7F, 0x03, '\n'}; uart_send(bin, sizeof bin, BAUD_BYTE_MS); }
    run_until(now_ms() + 800.0);
    check(W.npongs == 0, "%d pong(s) for junk input", W.npongs);
    /* an over-long line (299 bytes, a whole number of the 13 byte cycles of the receive buffer) that ends in a valid-looking ping:
     * the whole line is dropped.  a receive buffer that only cleared itself and kept collecting would be left with exactly
     * "PING:9" at the newline and answer it */
    {
        /* sent in the quiet gap after a data line, so that the receive interrupt buffer (64 bytes) cannot lose bytes while the loop is
         * busy with a pass and shift the alignment this relies on */
        int n0 = W.nlines;
        while (W.nlines == n0) run_until(now_ms() + 5.0);
        run_until(now_ms() + 150.0);
        char big[400]; memset(big, 'A', 299); memcpy(big + 299, "PING:9\n", 7); uart_send(big, 306, BAUD_BYTE_MS);
    }
    run_until(now_ms() + 800.0);
    check(W.npongs == 0, "%d pong(s) after an over-long line that ended in a ping", W.npongs);
    /* 70 bytes then a newline: the full buffer was cleared and the line is dropped */
    { char big[100]; memset(big, 'x', 70); big[70] = '\n'; uart_send(big, 71, BAUD_BYTE_MS); }
    run_until(now_ms() + 800.0);
    check(W.npongs == 0, "%d pong(s) after a 70 byte line", W.npongs);
    /* a flood of 2000 bytes with no newline while lines continue, then a newline */
    { char big[100]; memset(big, 'z', sizeof big); for (int k = 0; k < 20; k++) uart_send(big, sizeof big, BAUD_BYTE_MS); }
    uart_text("\n");
    run_until(now_ms() + 800.0);
    check(W.npongs == 0, "%d pong(s) after a 2000 byte flood", W.npongs);
    note("  %u junk lines, binary noise, a 299 byte line ending in a ping, a 70 byte line and a 2000 byte flood: no pong and no change to the data lines\n",
         (unsigned)(sizeof junk / sizeof junk[0]));
    /* the receive side still works afterwards */
    send_ping(77);
    wait_pongs(1, 700.0);
    send_ping(0);
    wait_pongs(2, 700.0);
    double w = 0, m = 0;
    check_pongs(&w, &m);
    note("  after all of that PING:77 and PING:0 were answered once each, worst %.1f ms\n", w);
    soak_and_finish(1);
    finish();
}

/* ---- reset causes ------------------------------------------------------------------- */
/* what each bootloader does with the reset flags, read from the pinned core's own source and proved by running the
 * real bootloader image in the emulation:
 *   new (Optiboot 4.4)  reads MCUSR, writes zero to it and starts the sketch.  the sketch always reads 0.
 *                       after a reset on the reset line it waits a second and restarts itself through its own
 *                       watchdog before it starts the sketch.
 *   old (ATmegaBOOT_168) leaves MCUSR alone, so the sketch reads the real flags.  it does not switch the watchdog off.
 * what the sketch must then report is worked out here from the rules, not from the firmware. */
enum { RAM_KEEP = 0, RAM_ZERO, RAM_ONES, RAM_RANDOM };
static const char *ram_name[] = {"RAM kept", "RAM zeroed", "RAM ones", "RAM random"};

static unsigned expect_reset_bits(uint8_t mcusr, int ram)
{
    uint8_t flags = (g_bl == BL_OLD) ? mcusr : 0;   /* the new bootloader clears the flags before the sketch starts */
    if (flags & 0x08) return ST_RESET_WATCHDOG;                              /* WDRF */
    if ((flags & 0x04) && !(flags & 0x01)) return ST_RESET_BROWNOUT;         /* BORF with PORF clear */
    if (flags == 0 && ram == RAM_KEEP && g_is_wdt) return ST_RESET_WATCHDOG; /* a restart that kept power, watchdog build only */
    return 0;
}

/* a reset of the whole chip with the given reset flags left in MCUSR and the RAM in the given state.  the harness calls
 * avr_reset and then sets the flag bits.  after a real power loss the RAM holds zeros, ones or noise, so those are
 * what the scenarios put there.  it does not lower the supply: it supplies the flags and the RAM a real event leaves. */
static void chip_reset_with(uint8_t mcusr, int ram)
{
    static uint8_t keep[4096];
    size_t top = (size_t)W.avr->ramend + 1;
    memcpy(keep, W.avr->data, top);
    avr_reset(W.avr);
    if (ram == RAM_KEEP) memcpy(W.avr->data + 0x100, keep + 0x100, top - 0x100);
    else {
        uint32_t x = 987654321u;
        for (size_t i = 0x100; i < top; i++) {
            x = x * 1664525u + 1013904223u;
            W.avr->data[i] = ram == RAM_ZERO ? 0x00 : ram == RAM_ONES ? 0xFF : (uint8_t)(x >> 24);
        }
    }
    W.avr->data[0x54] = mcusr;   /* MCUSR */
}

/* run until n_more lines of the new boot have arrived (the bootloader may take seconds before the sketch starts) */
static void run_until_lines(int n, double limit_ms)
{
    double end = now_ms() + limit_ms;
    while (W.nlines < n && now_ms() < end) run_until(now_ms() + 250.0);
}

static void reset_cause_case(uint8_t flags, int ram, const char *what)
{
    run_until(now_ms() + 3000.0);
    int n_pre = W.nlines;
    chip_reset_with(flags, ram);
    run_until_lines(n_pre + 6, 90000.0);
    int bad = -1;
    check(W.nlines >= n_pre + 6, "%s: only %d lines after the reset", what, W.nlines - n_pre);
    if (W.nlines <= n_pre + 3) return;
    unsigned want = expect_reset_bits(flags, ram);
    int first = n_pre;
    check(W.lines[first].seq == 0, "%s: the first line after the reset has SEQ:%u, want 0", what, W.lines[first].seq);
    check(W.lines[first].up >= 1 && W.lines[first].up <= 3, "%s: the first line after the reset has UP:%lu", what, W.lines[first].up);
    for (int i = first; i < W.nlines; i++) if ((W.lines[i].st & 48u) != want) { bad = i; break; }
    check(bad < 0, "%s: line %d has reset bits %u, want %u on every line of the boot: %s", what, bad, bad < 0 ? 0 : (W.lines[bad].st & 48u), want, bad < 0 ? "" : W.lines[bad].full);
    check(W.avr->data[0x54] == 0, "%s: MCUSR is 0x%02X after the boot, the firmware should have cleared it", what, W.avr->data[0x54]);
    note("  %-34s MCUSR 0x%02X, %-10s -> reset bits %2u (want %2u), first line %s\n", what, flags, ram_name[ram], W.lines[first].st & 48u, want, W.lines[first].full + strlen(W.lines[first].text));
}

static void reset_scenario_header(void)
{
    note("  bootloader: %s. build: %s.\n", g_bl == BL_NEW ? "new (Optiboot 4.4, clears MCUSR)" : "old (ATmegaBOOT_168, keeps MCUSR)", g_is_wdt ? "watchdog" : "default");
}

/* a scenario with resets expects as many as it caused plus the ones the bootloader makes itself (Optiboot restarts through
 * its own watchdog after a reset on the reset line), so the count is taken as it came */
static void reset_scenario_done(void)
{
    note("  chip resets seen: %d (the harness caused the ones it called; Optiboot adds one after a reset line)\n", W.nresets);
    W.expected_resets = W.nresets;
}

/* 15. brown-out: with the old bootloader the flag reaches the sketch and the sketch reports it.  with the new one it never does.
 * a brown-out that left the RAM alone (a dip) looks like a restart that kept power */
static void sc_reset_bor(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    reset_scenario_header();
    run_until(15000);
    reset_cause_case(0x04, RAM_RANDOM, "brown-out, power lost");
    reset_cause_case(0x04, RAM_KEEP, "brown-out dip, RAM survived");
    reset_cause_case(0x05, RAM_KEEP, "power-on and brown-out dip");
    reset_scenario_done();
    soak_and_finish(1);
    finish();
}

/* 15b. an ordinary power-up sets the power-on and brown-out flags together.  it is not a brown-out, whatever the RAM holds */
static void sc_reset_other(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    reset_scenario_header();
    run_until(15000);
    reset_cause_case(0x01, RAM_ZERO, "power-up");
    reset_cause_case(0x05, RAM_ZERO, "power-up with brown-out flag");
    reset_cause_case(0x05, RAM_ONES, "power-up with brown-out flag");
    reset_cause_case(0x05, RAM_RANDOM, "power-up with brown-out flag");
    reset_cause_case(0x02, RAM_KEEP, "reset line");
    reset_scenario_done();
    soak_and_finish(1);
    finish();
}

/* 15c. watchdog flag: the old bootloader passes it on.  the new one clears it and only the marker is left */
static void sc_reset_wdrf(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    reset_scenario_header();
    run_until(15000);
    reset_cause_case(0x08, RAM_KEEP, "watchdog flag, RAM kept");
    reset_cause_case(0x08, RAM_RANDOM, "watchdog flag, RAM lost");
    reset_scenario_done();
    soak_and_finish(1);
    finish();
}

/* 16. a forced hang with the watchdog build.  the harness makes every ADC conversion hang for ever, so the
 * firmware waits at a place with no timeout of its own.  nothing in the loop runs again, the watchdog is no
 * longer reset and after 8 s the chip resets.  the harness releases the hang at the reset, as a transient
 * fault would end. the next boot must report RESET_WATCHDOG on every line.
 *
 * the hang is not a bus hang on purpose: the Wire timeout already ends a stuck bus (scenario 8), so the
 * watchdog is for what has no timeout. */
static void sc_hang_wdt(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    reset_scenario_header();
    W.expected_resets = 1;
    run_until(20500);
    int n_pre = W.nlines;
    double last_start = W.lines[n_pre - 1].t_first;
    W.adc_hung = 1;
    double t_hang = now_ms();
    run_until(t_hang + 40000);
    check(W.nresets == 1, "the chip reset %d time(s) after the forced hang, want 1", W.nresets);
    if (W.nresets >= 1) {
        double rt = W.reset_t[0];
        /* the last wdt_reset is at the start of the pass that hung, which began 2000 ms after the last line began (less the sensor reads) */
        double since = rt - (last_start + 2000.0);
        check(since > 7.5e3 && since < 9.0e3, "the reset came %.2f s after the loop stopped, want about 8 s", since / 1000.0);
        int first = W.boot_at[0];
        check(first == n_pre, "%d lines were sent between the hang and the reset, want 0", first - n_pre);
        check(first < W.nlines, "no line after the reset: the node did not come back");
        if (first < W.nlines) {
            line_t *l = &W.lines[first];
            check((l->st & ST_RESET_WATCHDOG) != 0, "the first line after the reset has ST:%u, want RESET_WATCHDOG (16) set: %s", l->st, l->full);
            check(l->seq == 0, "the first line after the reset has SEQ:%u, want 0", l->seq);
            int bad = -1;
            for (int i = first; i < W.nlines; i++) if (!(W.lines[i].st & ST_RESET_WATCHDOG) || (W.lines[i].st & ST_RESET_BROWNOUT)) { bad = i; break; }
            check(bad < 0, "line %d of the new boot does not hold RESET_WATCHDOG alone: ST:%u", bad, bad < 0 ? 0 : W.lines[bad].st);
            check(l->t_first - rt < 3000.0, "the first line after the reset came %.0f ms later", l->t_first - rt);
            note("  hang forced at %.1f ms (last line began at %.1f ms). the loop stopped feeding the watchdog and the chip reset at %.1f ms, %.2f s after the loop stopped.\n"
                 "  no line was sent in between. the next boot's first line, %.0f ms after the reset: %s\n",
                 t_hang, last_start, rt, since / 1000.0, l->t_first - rt, l->full);
        }
        check(W.avr->data[0x54] == 0, "MCUSR is 0x%02X, the firmware should have cleared it", W.avr->data[0x54]);
    }
    run_until(t_hang + 100000);
    soak_and_finish(1);
    finish();
}

/* 16c. the watchdog build on the old bootloader.  the README says this loops for ever.  after a watchdog reset the old
 * bootloader leaves the watchdog running and the chip resets again before the sketch can switch it off.  this runs it and
 * reports what simavr's watchdog model does. */
static void sc_hang_wdt_old(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    reset_scenario_header();
    run_until(30500);
    int n_pre = W.nlines;
    W.adc_hung = 1;
    double t_hang = now_ms();
    run_until(t_hang + 90000);
    int lines_after = W.nlines - n_pre;
    note("  observed: forced hang at %.1f ms on the old bootloader with the watchdog on: %d chip resets in the next 90 s and %d new lines.\n", t_hang, W.nresets, lines_after);
    /* two outcomes are accepted and nothing else.  A: the chip resets again and again and sends no line (the loop).  B: it resets
     * once and sends lines again, the first of them carrying the watchdog flag that the old bootloader passes on.  a chip that
     * never resets (no watchdog armed) or any other pattern fails. */
    int loop = W.nresets >= 5 && lines_after == 0;
    int once = W.nresets == 1 && lines_after >= 10 && (W.lines[n_pre].st & ST_RESET_WATCHDOG);
    check(loop || once, "unexpected outcome: %d resets and %d new lines (want either 5 or more resets and no lines or one reset and lines again with RESET_WATCHDOG)", W.nresets, lines_after);
    if (loop) note("  outcome A observed: repeated resets and no line.\n");
    if (once) note("  outcome B observed: one reset, then lines again from SEQ %u with ST:%u on the first.\n", W.lines[n_pre].seq, W.lines[n_pre].st);
    W.expected_resets = W.nresets;
    g_observation = 1;   /* an observation: either of the two outcomes is accepted, so it records which one simavr gives */
    soak_and_finish(0);
    finish();
}

/* 16b. the same hang on the build without the watchdog: the node stops for ever.  this is what the flag is for.
 * it also shows that the harness hang really is a hang. */
static void sc_hang_plain(result_t *r)
{
    (void)r;
    boot(0x60, 0x76, BUS_NORMAL);
    run_until(20500);
    int n_pre = W.nlines;
    W.adc_hung = 1;
    double t_hang = now_ms();
    run_until(t_hang + 120000);
    check(W.nresets == 0, "the chip reset %d time(s) in a build with no watchdog", W.nresets);
    check(W.nlines <= n_pre, "%d lines after the forced hang, want none", W.nlines - n_pre);
    note("  without the watchdog the forced hang stopped the node for good: no line in the 120 s after it and no reset.\n");
    soak_and_finish(0);
    finish();
}

/* ======================================================================================
 * driver
 * ==================================================================================== */
/* the id is what --only takes.  every scenario runs against the default build and the watchdog build
 * unless it says otherwise. */
static const scenario_t scenarios[] = {
    {"1",   "healthy BME280 at 0x76",                       sc_healthy,       B_ALL, 0},
    {"2",   "BME280 at 0x77 only",                          sc_addr77,        B_BOTH, 0},
    {"3",   "BMP280 (id 0x58), humidity -1",                sc_bmp280,        B_BOTH, 0},
    {"4",   "no sensor on the bus",                         sc_no_sensor,     B_BOTH, 0},
    {"5",   "sensor stops answering mid-run",               sc_goes_silent,   B_BOTH, 0},
    {"5b",  "one missed read only",                         sc_glitch,        B_BOTH, 0},
    {"6",   "sensor returns after 40 s",                    sc_returns,       B_BOTH, 0},
    {"6b",  "sensor plugged in late (40 s)",                sc_plugged_late,  B_BOTH, 0},
    {"7a",  "sensor brown-out, all registers reset",        sc_reset_full,    B_BOTH, 0},
    {"7b",  "BME280 control registers reset, data kept",    sc_reset_ctrl,    B_BOTH, 0},
    {"7c",  "BMP280 control registers reset, data kept",    sc_reset_ctrl_bmp,B_BOTH, 0},
    {"8",   "data line held low mid-run (hung bus)",        sc_hung_bus,      B_BOTH, 0},
    {"8b",  "data line held low from power-up",             sc_hung_boot,     B_BOTH, 0},
    {"9",   "stuck raw data, BME_STUCK and recovery",       sc_stuck,         B_BOTH, 0},
    {"9b",  "stuck converter cured by the soft reset",      sc_stuck_cured,   B_BOTH, 0},
    {"9c1", "still room BME280, 1.0 x data sheet noise",    sc_still_100,     B_BOTH, 0},
    {"9c2", "still room BME280, 0.5 x data sheet noise",    sc_still_50,      B_BOTH, 0},
    {"9c5", "still room BME280, 0.2 x data sheet noise",    sc_still_20,      B_BOTH, 0},
    {"9c10","still room BME280, 0.1 x data sheet noise",    sc_still_10,      B_BOTH, 0},
    {"9c20","still room BME280, 0.05 x data sheet noise",   sc_still_05,      B_BOTH, 0},
    {"9d1", "still room BMP280, 1.0 x data sheet noise",    sc_still_bmp_100, B_BOTH, 0},
    {"9d2", "still room BMP280, 0.5 x data sheet noise",    sc_still_bmp_50,  B_BOTH, 0},
    {"9d5", "still room BMP280, 0.2 x data sheet noise",    sc_still_bmp_20,  B_BOTH, 0},
    {"9d10","still room BMP280, 0.1 x data sheet noise",    sc_still_bmp_10,  B_BOTH, 0},
    {"9d20","still room BMP280, 0.05 x data sheet noise",   sc_still_bmp_05,  B_BOTH, 0},
    {"9e",  "replay of raw words from a real part",         sc_replay,        B_BOTH, 0},
    {"7d",  "part falls asleep every third read",           sc_flapping,      B_BOTH, 0},
    {"17",  "negative temperatures print exactly",          sc_negative,      B_BOTH, 0},
    {"18",  "sensor swapped for another part mid-run",      sc_swap,          B_BOTH, 0},
    {"10",  "analogue inputs, pin 7, water, ADC sharing",   sc_analog,        B_BOTH, 0},
    {"10b", "supply arithmetic and limits, three builds", sc_supply,        B_ALL, 0},
    {"12",  "BME_RANGE and the humidity band",            sc_range,         B_BOTH, 0},
    {"13",  "ping: sweep, mid-line, three in a row, stream",sc_ping,          B_BOTH, 0},
    {"13b", "ping with the bus hung",                       sc_ping_hung,     B_BOTH, 0},
    {"14",  "garbage and over-long input ignored",          sc_garbage,       B_BOTH, 0},
    {"15",  "reset cause: brown-out flag",                  sc_reset_bor,     B_BOTH, 3},
    {"15b", "reset causes: power-on and external",          sc_reset_other,   B_BOTH, 3},
    {"15c", "reset cause: watchdog flag set by harness",    sc_reset_wdrf,    B_BOTH, 3},
    {"16",  "forced hang, watchdog resets, RESET_WATCHDOG", sc_hang_wdt,      B_WDT, 1},
    {"16c",  "forced hang, watchdog build, old bootloader",   sc_hang_wdt_old,  B_WDT, 2},
    {"16b", "forced hang, no watchdog: stays hung",         sc_hang_plain,    B_DEFAULT, 0},
};
#define NSCEN ((int)(sizeof scenarios / sizeof scenarios[0]))

typedef struct { int sc; int wdt; int cal; int bl; char label[96]; } job_t;

static void child_main(const job_t *job, int idx, int fd)
{
    static result_t res;
    memset(&res, 0, sizeof res);
    R = &res;
    g_is_wdt = job->wdt;
    g_is_cal = job->cal;
    g_bl = job->bl;
    g_elf = job->cal ? g_elf_cal : job->wdt ? g_elf_wdt : g_elf_default;
    alarm(WALL_LIMIT_S + 60);
    scenarios[job->sc].run(&res);
    size_t off = 0;
    while (off < sizeof res) {
        ssize_t n = pwrite(fd, (char *)&res + off, sizeof res - off, (off_t)((size_t)idx * sizeof res + off));
        if (n <= 0) _exit(3);
        off += (size_t)n;
    }
    _exit(0);
}

int main(int argc, char **argv)
{
    const char *only = NULL, *only_build = NULL;
    int jobs_max = (int)sysconf(_SC_NPROCESSORS_ONLN);
    if (jobs_max < 1) jobs_max = 1;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--elf") && i + 1 < argc) g_elf_default = argv[++i];
        else if (!strcmp(argv[i], "--elf-wdt") && i + 1 < argc) g_elf_wdt = argv[++i];
        else if (!strcmp(argv[i], "--elf-cal") && i + 1 < argc) g_elf_cal = argv[++i];
        else if (!strcmp(argv[i], "--hex-new") && i + 1 < argc) g_hex_new = argv[++i];
        else if (!strcmp(argv[i], "--hex-old") && i + 1 < argc) g_hex_old = argv[++i];
        else if (!strcmp(argv[i], "--replay") && i + 1 < argc) g_replay = argv[++i];
        else if (!strcmp(argv[i], "--soak-s") && i + 1 < argc) g_soak_ms = atof(argv[++i]) * 1000.0;
        else if (!strcmp(argv[i], "--serial")) jobs_max = 1;
        else if (!strcmp(argv[i], "--jobs") && i + 1 < argc) jobs_max = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--only") && i + 1 < argc) only = argv[++i];
        else if (!strcmp(argv[i], "--build") && i + 1 < argc) only_build = argv[++i];
        else { fprintf(stderr, "usage: %s [--elf file] [--elf-wdt file] [--soak-s seconds] [--jobs n] [--serial] [--only id] [--build default|wdt]\n", argv[0]); return 2; }
    }
    if (jobs_max < 1) jobs_max = 1;

    /* the firmware's own checksum function, compiled here, against the data sheet-style one written above:
     * the check value for "123456789" and 2000 random messages */
    {
        static const char cv[] = "123456789";
        uint16_t a = link_crc16((const uint8_t *)cv, 9), b = ref_crc16((const uint8_t *)cv, 9);
        int ok = (a == 0x29B1 && b == 0x29B1);
        uint32_t x = 12345;
        for (int k = 0; k < 2000 && ok; k++) {
            uint8_t buf[200]; size_t n = (size_t)(x % 160); 
            for (size_t j = 0; j < n; j++) { x = x * 1664525u + 1013904223u; buf[j] = (uint8_t)(x >> 24); }
            x = x * 1664525u + 1013904223u;
            if (link_crc16(buf, n) != ref_crc16(buf, n)) ok = 0;
        }
        printf("crc self-test: \"123456789\" gives %04X from the firmware's code and %04X from the independent one (want 29B1), 2000 random messages %s\n",
               a, b, ok ? "agree" : "DISAGREE");
        if (!ok) { printf("CRC self-test FAILED\n"); return 1; }
    }

    int want_default = !(only_build && !strcmp(only_build, "wdt"));
    int want_wdt     = !(only_build && !strcmp(only_build, "default"));
    if (want_default && access(g_elf_default, R_OK) != 0) { fprintf(stderr, "firmware not found: %s (run the build first)\n", g_elf_default); return 2; }
    if (want_default && access(g_elf_cal, R_OK) != 0) { fprintf(stderr, "calibrated firmware not found: %s (run the build first)\n", g_elf_cal); return 2; }
    if (want_wdt && access(g_elf_wdt, R_OK) != 0) { fprintf(stderr, "watchdog firmware not found: %s (run the build first)\n", g_elf_wdt); return 2; }

    static job_t job[8 * NSCEN];
    int njobs = 0;
    for (int i = 0; i < NSCEN; i++) {
        if (only) {   /* --only takes one id or a comma separated list */
            char pat[40], list[200];
            snprintf(pat, sizeof pat, ",%s,", scenarios[i].id);
            snprintf(list, sizeof list, ",%s,", only);
            if (!strstr(list, pat)) continue;
        }
        if (!strcmp(scenarios[i].id, "9e") && !g_replay) continue;   /* only with --replay FILE */
        for (int w = 0; w < 3; w++) {
            if (w == 0 && (!want_default || scenarios[i].builds == B_WDT)) continue;
            if (w == 1 && (!want_wdt || scenarios[i].builds == B_DEFAULT)) continue;
            if (w == 2 && (!want_default || scenarios[i].builds != B_ALL)) continue;
            for (int bl = 0; bl < 3; bl++) {
                if (bl == 0 ? scenarios[i].bl != 0 : !(scenarios[i].bl & (1 << (bl - 1)))) continue;
                if (bl && !(g_hex_new && g_hex_old)) { fprintf(stderr, "scenario %s needs --hex-new and --hex-old\n", scenarios[i].id); return 2; }
                job[njobs].sc = i; job[njobs].wdt = (w == 1); job[njobs].cal = (w == 2); job[njobs].bl = bl;
                snprintf(job[njobs].label, sizeof job[njobs].label, "%s %s%s%s", scenarios[i].id, scenarios[i].name, w == 1 ? " [wdt]" : w == 2 ? " [cal]" : "",
                         bl == 1 ? " [new bl]" : bl == 2 ? " [old bl]" : "");
                njobs++;
            }
        }
    }
    if (!njobs) { fprintf(stderr, "no scenario matches\n"); return 2; }

    static result_t results[8 * NSCEN];
    pid_t pids[8 * NSCEN];
    int rfd = open("sim_results.tmp", O_RDWR | O_CREAT | O_TRUNC, 0600);
    if (rfd < 0) { perror("results file"); return 2; }
    unlink("sim_results.tmp");
    time_t t0 = time(NULL);
    int next = 0, running = 0, done = 0;
    while (done < njobs) {
        while (running < jobs_max && next < njobs) {
            pid_t pid = fork();
            if (pid == 0) child_main(&job[next], next, rfd);
            pids[next] = pid; next++; running++;
        }
        int st; pid_t got = waitpid(-1, &st, 0);
        if (got < 0) break;
        for (int i = 0; i < next; i++) {
            if (pids[i] != got) continue;
            ssize_t n = pread(rfd, &results[i], sizeof results[i], (off_t)((size_t)i * sizeof results[i]));
            if (!(WIFEXITED(st) && WEXITSTATUS(st) == 0) || n != (ssize_t)sizeof results[i]) {
                memset(&results[i], 0, sizeof results[i]);
                results[i].status = ST_FAIL;
                snprintf(results[i].detail, sizeof results[i].detail,
                         "  FAIL: scenario process ended without a result (killed by the wall-time alarm or crashed)\n");
            }
            pids[i] = -1;
            break;
        }
        running--; done++;
    }

    int fails = 0;
    printf("\n");
    for (int i = 0; i < njobs; i++) {
        const char *tag = tag_of(results[i].status);
        printf("=== %s : %s\n%s", job[i].label, tag, results[i].detail);
    }

    printf("\n=== 11 timing: gap between lines over %.0f s of simulated time (limit 2000 +/- %.0f ms, gaps across a reset not counted)\n", g_soak_ms / 1000.0, GAP_TOL_MS);
    printf("    %-78s %6s %9s %9s %9s\n", "scenario", "gaps", "min ms", "max ms", "result");
    int timing_fail = 0;
    for (int i = 0; i < njobs; i++) {
        result_t *r = &results[i];
        int expect_gaps = strcmp(scenarios[job[i].sc].id, "16b") != 0;   /* 16b stops on purpose */
        int ok = (!expect_gaps || r->gaps > 0) && r->gap_worst_dev <= GAP_TOL_MS && r->sim_ms >= g_soak_ms - 1.0;
        if (!ok) timing_fail++;
        printf("    %-78s %6d %9.1f %9.1f %9s\n", job[i].label, r->gaps, r->gap_min, r->gap_max, ok ? "ok" : "OUT");
    }

    printf("\n==================== summary ====================\n");
    printf("%-78s %-8s %8s %8s\n", "scenario", "result", "sim s", "wall s");
    int findings = 0, observed = 0;
    for (int i = 0; i < njobs; i++) {
        result_t *r = &results[i];
        const char *tag = tag_of(r->status);
        if (r->status == ST_FAIL) fails++;
        if (r->status == ST_FINDING) findings++;
        if (r->status == ST_OBSERVED) observed++;
        printf("%-78s %-8s %8.0f %8.0f\n", job[i].label, tag, r->sim_ms / 1000.0, r->wall_s);
    }
    printf("%-78s %-8s\n", "11 timing within tolerance in every scenario", timing_fail ? "FAIL" : "PASS");
    fails += timing_fail ? 1 : 0;
    printf("\n%d failed, %d finding(s), %d observation(s) (not tests), %d scenario runs, total wall time %lds\n", fails, findings, observed, njobs, (long)(time(NULL) - t0));
    return fails ? 1 : 0;
}
