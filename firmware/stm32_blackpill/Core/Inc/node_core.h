/**
 * node_core.h - the per-tick logic of the node without the hardware
 *
 * no HAL header, so it builds on a host compiler.  main.c does the reads and
 * the sending and calls this for everything in between: counting the tick,
 * discarding a window, the lost-sensor rule, filling the window and finding
 * out when a line is due.  the host test drives the same code, so a step
 * missing here is missing in both.
 */

#ifndef NODE_CORE_H
#define NODE_CORE_H

#include <stdbool.h>
#include <stdint.h>
#include "sensor_state.h"
#include "status.h"
#include "window_stats.h"

typedef struct
{
    SensorState sensor;
    WindowBuf   win;
    StatusState status;
} NodeCore;

typedef struct
{
    uint32_t now_ms;
    uint32_t missed_ticks;      /* ticks the main loop missed since the last call */
    bool     first_ok;          /* first read worked and was not all-zero */
    int16_t  first_raw[3];
    bool     retried;           /* a retry was made (SensorState_ShouldRetry said so) */
    bool     second_ok;
    int16_t  second_raw[3];
} TickInput;

typedef struct
{
    bool    recover;            /* bus recovery and sensor re-init are due */
    bool    window_complete;    /* a full window is ready in core->win */
    uint8_t failed_reads;       /* to add to RF */
} TickOutput;

void Node_Init(NodeCore *n, bool sensor_init_ok, uint8_t boot_status_bits, uint32_t now_ms);

/* discard a partly filled window and note it for the status word */
void Node_DiscardWindow(NodeCore *n);

/* process one 10 ms tick */
void Node_Tick(NodeCore *n, const TickInput *in, TickOutput *out);

/* a line (data or zero) was sent */
void Node_LineSent(NodeCore *n);

/* which zero-reading line is due now, if any */
ZeroLine Node_ZeroLineDue(const NodeCore *n);

#endif /* NODE_CORE_H */
