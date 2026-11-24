/**
 * node_core.c - the per-tick logic of the node without the hardware
 */

#include "node_core.h"

void Node_Init(NodeCore *n, bool sensor_init_ok, uint8_t boot_status_bits, uint32_t now_ms)
{
    SensorState_Init(&n->sensor, sensor_init_ok, now_ms);
    WinBuf_Clear(&n->win);
    Status_Init(&n->status, boot_status_bits);
}

void Node_DiscardWindow(NodeCore *n)
{
    /* an empty window has nothing to lose, so it is not reported as dropped */
    if (n->win.count > 0U)
    {
        Status_NoteDropped(&n->status);
    }
    WinBuf_Clear(&n->win);
}

void Node_Tick(NodeCore *n, const TickInput *in, TickOutput *out)
{
    out->recover         = false;
    out->window_complete = false;

    /* the missed ticks still count towards the line period, but a gap in
     * the 100 Hz timebase would smear the spectrum, so the partly filled
     * window is thrown away */
    SensorState_AddTicks(&n->sensor, 1U + in->missed_ticks);
    if (in->missed_ticks != 0U)
    {
        Node_DiscardWindow(n);
    }

    bool tick_ok = SensorState_TickOk(in->first_ok, in->retried, in->second_ok);
    out->failed_reads = SensorState_FailedReads(in->first_ok, in->retried, in->second_ok);

    /* one failed tick discards the partly filled window and nothing else:
     * the sensor is lost only after five failed ticks in a row.  the next
     * complete window carries WINDOW_DROPPED. */
    if (!tick_ok)
    {
        Node_DiscardWindow(n);
    }

    out->recover = SensorState_OnRead(&n->sensor, tick_ok, in->now_ms);

    if (tick_ok)
    {
        const int16_t *raw = in->first_ok ? in->first_raw : in->second_raw;
        if (WinBuf_Add(&n->win, raw[0], raw[1], raw[2]))
        {
            /* a complete window means the sensor is back: it clears the
             * lost flag and restarts the no-data clock */
            SensorState_OnWindowComplete(&n->sensor);
            out->window_complete = true;
        }
    }
}

void Node_LineSent(NodeCore *n)
{
    SensorState_OnLineSent(&n->sensor);
}

ZeroLine Node_ZeroLineDue(const NodeCore *n)
{
    return SensorState_ZeroLineDue(&n->sensor);
}
