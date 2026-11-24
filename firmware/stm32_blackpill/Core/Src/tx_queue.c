/**
 * tx_queue.c - the queue of messages waiting for the UART transmitter
 */

#include "tx_queue.h"
#include <string.h>

void TxQueue_Init(TxQueue *q)
{
    memset(q, 0, sizeof(*q));
}

static bool push(TxQueue *q, const uint8_t *data, size_t len, bool is_pong)
{
    if ((data == NULL) || (len == 0U) || (len > TX_SLOT_BYTES) || (q->count >= TX_SLOTS))
    {
        return false;
    }
    /* the next free slot is the one after the newest message.  the oldest may
     * be on the wire and it is never the slot written here because the queue
     * is not full */
    TxSlot *s = &q->slot[(uint8_t)((q->head + q->count) % TX_SLOTS)];
    memcpy(s->data, data, len);
    s->len     = (uint16_t)len;
    s->is_pong = is_pong;
    q->count++;
    if (is_pong)
    {
        q->pongs++;
    }
    return true;
}

bool TxQueue_PushLine(TxQueue *q, const uint8_t *data, size_t len)
{
    if (!push(q, data, len, false))
    {
        q->lines_dropped++;
        return false;
    }
    return true;
}

bool TxQueue_PushPong(TxQueue *q, const uint8_t *data, size_t len)
{
    if ((q->pongs >= TX_MAX_PONGS) || !push(q, data, len, true))
    {
        q->pongs_dropped++;
        return false;
    }
    return true;
}

bool TxQueue_LineSpace(const TxQueue *q)
{
    return q->count < TX_SLOTS;
}

bool TxQueue_Start(TxQueue *q, const uint8_t **data, uint16_t *len)
{
    if ((q->count == 0U) || q->in_flight)
    {
        return false;
    }
    TxSlot *s = &q->slot[q->head];
    *data = s->data;
    *len  = s->len;
    q->in_flight = true;
    return true;
}

void TxQueue_Done(TxQueue *q)
{
    if (!q->in_flight)
    {
        return;
    }
    if (q->slot[q->head].is_pong)
    {
        q->pongs--;
    }
    q->head = (uint8_t)((q->head + 1U) % TX_SLOTS);
    q->count--;
    q->in_flight = false;
}
