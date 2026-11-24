/**
 * test_uart.c - host test for the transmit queue and the real uart_output.c
 *
 * the real uart_output.c and tx_queue.c are built against a stub HAL (stub/stm32f4xx_hal.h).  the test plays the
 * part of the transmitter: HAL_UART_Transmit_IT starts a transfer from the caller's buffer and the test steps it
 * one byte at a time, reading each byte from that buffer at the moment it is sent, as the interrupt does. a
 * message overwritten while it is on the wire therefore shows up as wrong bytes on the wire.
 *
 * covers: every pair of arrival offsets of a line, a pong and a second pong (S2), a ping during a line, the queue
 * limits and the drop counters, the receive callbacks (a byte, a framing error, an overrun, a refused re-arm)
 * and a sweep of all 128 phases of the first good window after an outage against a line still on the wire (S1).
 *
 * build and run from this folder:
 *   cc -std=c11 -Wall -Wextra -Werror -Istub -I../Core/Inc test_uart.c ../Core/Src/uart_output.c ../Core/Src/tx_queue.c ../Core/Src/ping.c ../Core/Src/node_core.c ../Core/Src/sensor_state.c ../Core/Src/window_stats.c ../Core/Src/status.c -lm -o "${TMPDIR:-/tmp}/test_uart" && "${TMPDIR:-/tmp}/test_uart"
 * the same with the address and undefined behaviour checkers:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -Istub -I../Core/Inc test_uart.c ../Core/Src/uart_output.c ../Core/Src/tx_queue.c ../Core/Src/ping.c ../Core/Src/node_core.c ../Core/Src/sensor_state.c ../Core/Src/window_stats.c ../Core/Src/status.c -lm -o "${TMPDIR:-/tmp}/test_uart_san" && "${TMPDIR:-/tmp}/test_uart_san"
 */

#include "uart_output.h"
#include "node_core.h"
#include "test_common.h"
#include <stdio.h>
#include <string.h>

USART_TypeDef stub_usart1;
static UART_HandleTypeDef h;

/* ---- the transmitter: one transfer at a time, read byte by byte from the caller's buffer ---- */
static struct { const uint8_t *p; uint16_t len, pos; } tx;
static uint8_t wire[8192];
static size_t  wire_n;
static int     refuse_rx;      /* make HAL_UART_Receive_IT refuse */
static uint8_t *rx_ptr;
static int     rx_calls;

HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *hu, uint8_t *pData, uint16_t Size)
{
    if (hu->gState != HAL_UART_STATE_READY) return HAL_BUSY;
    tx.p = pData; tx.len = Size; tx.pos = 0;
    hu->gState = HAL_UART_STATE_BUSY_TX;
    return HAL_OK;
}

HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *hu, uint8_t *pData, uint16_t Size)
{
    (void)Size;
    rx_calls++;
    if (refuse_rx || hu->RxState != HAL_UART_STATE_READY) return HAL_BUSY;
    rx_ptr = pData;
    hu->RxState = HAL_UART_STATE_BUSY_RX;
    hu->ErrorCode = HAL_UART_ERROR_NONE;
    return HAL_OK;
}

static void wire_step(void)
{
    if (h.gState == HAL_UART_STATE_BUSY_TX)
    {
        wire[wire_n++] = tx.p[tx.pos++];
        if (tx.pos >= tx.len) h.gState = HAL_UART_STATE_READY;     /* the last byte has gone: transfer finished */
    }
}

static void reset_all(void)
{
    memset(&h, 0, sizeof(h));
    h.Instance = USART1;
    h.gState = HAL_UART_STATE_READY;
    h.RxState = HAL_UART_STATE_READY;
    wire_n = 0;
    /* a fresh queue: the module's own state is reset by draining it */
    for (int i = 0; i < 20000 && (h.gState != HAL_UART_STATE_READY || UART_LineSpace() == 0); i++) { UART_TxService(&h); wire_step(); }
}

/* ---- messages with distinct bytes so mixing is visible ---- */
static size_t make_line(uint8_t *b, char tag, size_t len)
{
    for (size_t i = 0; i < len - 2; i++) b[i] = (uint8_t)(tag + (i % 7));
    b[len - 2] = '\r'; b[len - 1] = '\n';
    return len;
}
static size_t make_pong(uint8_t *b, char tag)
{
    int n = snprintf((char *)b, 24, "PONG:%c*%c%c%c%c\r\n", tag, tag, tag, tag, tag);
    return (size_t)n;
}

typedef struct { int at; int kind; char tag; size_t len; } Ev;     /* kind 0 line, 1 pong */

/* run events (sorted by 'at', a byte-time offset) and compare the wire with what was accepted, in order */
static int run_case(const Ev *ev, int nev)
{
    uint8_t expect[4096];
    size_t  en = 0;
    reset_all();
    int next = 0;
    for (int t = 0; t < 1500; t++)
    {
        while (next < nev && ev[next].at == t)
        {
            uint8_t m[TX_SLOT_BYTES];
            size_t  l;
            bool ok;
            if (ev[next].kind == 0) { l = make_line(m, ev[next].tag, ev[next].len); ok = UART_QueueLine((char *)m, l); }
            else                    { l = make_pong(m, ev[next].tag);                ok = UART_QueuePong((char *)m, l); }
            if (ok) { memcpy(expect + en, m, l); en += l; }
            next++;
        }
        UART_TxService(&h);
        wire_step();
    }
    return wire_n == en && memcmp(wire, expect, en) == 0;
}

int main(void)
{
    reset_all();

    /* ---- one message, then each kind in turn ---- */
    {
        Ev a[] = { {0, 0, 'A', 160} };
        CHECK(run_case(a, 1), "a 160 byte line goes out intact and alone");
        Ev b[] = { {0, 1, '1', 0} };
        CHECK(run_case(b, 1), "a pong goes out intact and alone");
    }

    /* ---- S2: a line in flight, a pong at every offset, a second pong at every later offset ---- */
    {
        int bad = 0, cases = 0;
        for (int k = 0; k <= 175; k++)
            for (int j = k; j <= 175; j++)
            {
                Ev e[] = { {0, 0, 'L', 160}, {k, 1, '1', 0}, {j, 1, '2', 0} };
                cases++;
                if (!run_case(e, 3)) bad++;
            }
        CHECK(bad == 0, "line, pong and second pong at every pair of offsets: %d of %d cases corrupted or reordered", bad, cases);
    }

    /* ---- a pong in flight, a second pong 0 to 40 byte times later (the 0.9 ms of the report is about 10) ---- */
    {
        int bad = 0;
        for (int d = 0; d <= 40; d++)
        {
            Ev e[] = { {0, 1, '1', 0}, {d, 1, '2', 0} };
            if (!run_case(e, 2)) bad++;
        }
        CHECK(bad == 0, "two pings 0 to 40 byte times apart: %d corrupted", bad);
    }

    /* ---- a pong in flight, then a line at every offset, then a second pong at every later offset ---- */
    {
        int bad = 0, cases = 0;
        for (int k = 0; k <= 30; k++)
            for (int j = k; j <= 200; j += 3)
            {
                Ev e[] = { {0, 1, '1', 0}, {k, 0, 'L', 160}, {j, 1, '2', 0} };
                cases++;
                if (!run_case(e, 3)) bad++;
            }
        CHECK(bad == 0, "pong, line, pong at every offset pair: %d of %d cases wrong", bad, cases);
    }

    /* ---- two lines close together (the 1 in 128 phase of the report) ---- */
    {
        int bad = 0;
        for (int d = 0; d <= 170; d++)
        {
            Ev e[] = { {0, 0, 'X', 125}, {d, 0, 'Y', 130} };
            if (!run_case(e, 2)) bad++;
        }
        CHECK(bad == 0, "two lines 0 to 170 byte times apart: %d lost or corrupted", bad);
    }

    /* ---- limits: a pong burst keeps two slots for lines and drops are counted ---- */
    {
        reset_all();
        uint8_t m[TX_SLOT_BYTES];
        size_t l = make_pong(m, 'a');
        uint32_t before = g_pong_dropped;
        bool r1 = UART_QueuePong((char *)m, l);
        bool r2 = UART_QueuePong((char *)m, l);
        bool r3 = UART_QueuePong((char *)m, l);
        bool r4 = UART_QueuePong((char *)m, l);
        CHECK(r1 && r2 && !r3 && !r4, "of four pongs at once two are queued and two are dropped (%d %d %d %d)", r1, r2, r3, r4);
        CHECK(g_pong_dropped - before == 2, "each drop is counted (g_pong_dropped rose by %u)", (unsigned)(g_pong_dropped - before));
        size_t ll = make_line(m, 'L', 157);
        bool lq1 = UART_QueueLine((char *)m, ll);
        bool lq2 = UART_QueueLine((char *)m, ll);
        bool lq3 = UART_QueueLine((char *)m, ll);
        CHECK(lq1 && lq2 && !lq3, "with two pongs waiting two lines still fit and a third does not (%d %d %d)", lq1, lq2, lq3);
        CHECK(!UART_LineSpace(), "UART_LineSpace reports the queue full");
        /* everything that was accepted goes out, in order and the queue empties */
        for (int i = 0; i < 2000; i++) { UART_TxService(&h); wire_step(); }
        CHECK(wire_n == 2 * l + 2 * ll, "the four accepted messages went out whole (%zu bytes, expected %zu)", wire_n, 2 * l + 2 * ll);
        CHECK(UART_LineSpace(), "and the queue has room again");
    }

    /* ---- receive callbacks ---- */
    {
        reset_all();
        ByteRing ring;
        ByteRing_Init(&ring);
        rx_calls = 0; refuse_rx = 0;
        UART_RxStart(&h, &ring);
        CHECK(h.RxState == HAL_UART_STATE_BUSY_RX && rx_calls == 1, "receive starts");

        /* a good byte: the HAL stores it, ends the receive (state READY) and calls the callback */
        *rx_ptr = 'P'; h.RxState = HAL_UART_STATE_READY;
        HAL_UART_RxCpltCallback(&h);
        uint8_t b = 0;
        CHECK(ByteRing_Pop(&ring, &b) && b == 'P', "a received byte reaches the ring");
        CHECK(h.RxState == HAL_UART_STATE_BUSY_RX, "and receive is armed again");

        /* a framing error: ErrorCode is set before the callback.  the byte is dropped and receive re-armed */
        *rx_ptr = 'X'; h.RxState = HAL_UART_STATE_READY; h.ErrorCode = HAL_UART_ERROR_FE;
        HAL_UART_RxCpltCallback(&h);
        CHECK(!ByteRing_Pop(&ring, &b), "a byte with a framing error is dropped");
        CHECK(h.RxState == HAL_UART_STATE_BUSY_RX, "and receive is armed again");

        /* an overrun: the HAL ends the receive (READY) and calls the error callback */
        uint32_t errs = g_rx_errors;
        h.RxState = HAL_UART_STATE_READY; h.ErrorCode = HAL_UART_ERROR_ORE;
        HAL_UART_ErrorCallback(&h);
        CHECK(g_rx_errors == errs + 1 && h.RxState == HAL_UART_STATE_BUSY_RX, "an overrun is counted and receive restarts");

        /* a lesser error leaves the receive running: nothing is restarted */
        int calls = rx_calls;
        h.ErrorCode = HAL_UART_ERROR_NE;
        HAL_UART_ErrorCallback(&h);
        CHECK(rx_calls == calls && h.RxState == HAL_UART_STATE_BUSY_RX, "a noise error with receive still running restarts nothing");

        /* a full ring drops the byte and counts it */
        for (int i = 0; i < 100; i++) ByteRing_Push(&ring, 'f');
        uint32_t dr = g_rx_dropped;
        *rx_ptr = 'Z'; h.RxState = HAL_UART_STATE_READY; h.ErrorCode = HAL_UART_ERROR_NONE;
        HAL_UART_RxCpltCallback(&h);
        CHECK(g_rx_dropped == dr + 1, "a byte that finds the ring full is dropped and counted");

        /* the HAL refusing to re-arm is counted, so a stopped receiver is visible */
        uint32_t rf = g_rx_rearm_failed;
        refuse_rx = 1; h.RxState = HAL_UART_STATE_READY; h.ErrorCode = HAL_UART_ERROR_ORE;
        HAL_UART_ErrorCallback(&h);
        CHECK(g_rx_rearm_failed == rf + 1, "a refused re-arm is counted (g_rx_rearm_failed)");
        refuse_rx = 0;
    }

    /* ---- S1: the first good window after an outage, against a line still on the wire, at all 128 phases ---- */
    {
        int bad = 0, worst_phase = -1;
        for (int p = 0; p <= 127; p++)
        {
            reset_all();
            NodeCore n;
            Node_Init(&n, false, 0, 0);                /* sensor absent at start-up: lost */
            unsigned data_queued = 0, data_skipped = 0, zero_queued = 0;
            uint32_t now = 0;
            int recovered_at = -1;
            for (int t = 0; t < 128 * 5; t++)
            {
                now += 10;
                bool good = (recovered_at >= 0) || (t >= 128 + p);      /* the sensor returns p ticks after the first zero line */
                if (good && recovered_at < 0) recovered_at = t;
                TickInput in = {0};
                in.now_ms = now;
                in.first_ok = good;
                in.first_raw[0] = (int16_t)(t * 7); in.first_raw[1] = (int16_t)(t * 3); in.first_raw[2] = 16384;
                TickOutput out;
                Node_Tick(&n, &in, &out);
                if (out.window_complete)
                {
                    uint8_t m[TX_SLOT_BYTES]; size_t l = make_line(m, 'D', 130);
                    if (UART_LineSpace()) { UART_QueueLine((char *)m, l); data_queued++; } else data_skipped++;
                    Node_LineSent(&n);
                    WinBuf_Clear(&n.win);
                }
                ZeroLine zl = Node_ZeroLineDue(&n);
                if (zl != ZERO_LINE_NONE)
                {
                    uint8_t m[TX_SLOT_BYTES]; size_t l = make_line(m, 'Z', 125);
                    if (UART_LineSpace()) { UART_QueueLine((char *)m, l); zero_queued++; }
                    Node_LineSent(&n);
                }
                /* one tick of wire time: 115 bytes at 115200 baud */
                for (int i = 0; i < 115; i++) { UART_TxService(&h); wire_step(); }
            }
            for (int i = 0; i < 400; i++) { UART_TxService(&h); wire_step(); }
            size_t want = (size_t)data_queued * 130 + (size_t)zero_queued * 125;
            if (data_skipped != 0 || data_queued < 3 || wire_n != want) { bad++; if (worst_phase < 0) worst_phase = p; }
        }
        CHECK(bad == 0, "the first good window's line is sent whole at all 128 phases (%d phases failed, first at phase %d)", bad, worst_phase);
    }

    TEST_FINISH();
}
