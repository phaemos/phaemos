/**
 * ping.c - byte ring and ping parser
 */

#include "ping.h"
#include <string.h>

/* ---- byte ring ----
 * head is written only by the interrupt and tail only by the main loop, so
 * no lock is needed on a single-core part.  the data byte is stored before
 * head moves, so the consumer never sees an index whose byte is not there. */

void ByteRing_Init(ByteRing *r)
{
    r->head = 0U;
    r->tail = 0U;
}

bool ByteRing_Push(ByteRing *r, uint8_t byte)
{
    uint8_t head = r->head;
    uint8_t next = (uint8_t)((head + 1U) & (BYTE_RING_SIZE - 1U));

    if (next == r->tail)
    {
        return false;   /* full: drop the byte rather than block */
    }
    r->data[head] = byte;
    r->head = next;
    return true;
}

bool ByteRing_Pop(ByteRing *r, uint8_t *byte)
{
    uint8_t tail = r->tail;

    if (tail == r->head)
    {
        return false;
    }
    *byte = r->data[tail];
    r->tail = (uint8_t)((tail + 1U) & (BYTE_RING_SIZE - 1U));
    return true;
}

/* ---- ping parser ---- */

void Ping_Init(PingParser *p)
{
    p->len        = 0U;
    p->discarding = false;
}

/* parse "PING:<digits>" from the first len bytes of buf */
static bool parse_line(const char *buf, uint8_t len, uint16_t *n)
{
    static const char prefix[] = "PING:";
    const uint8_t     plen     = (uint8_t)(sizeof(prefix) - 1U);

    /* one to five digits follow the prefix */
    if ((len <= plen) || (len > plen + 5U) || (memcmp(buf, prefix, plen) != 0))
    {
        return false;
    }

    uint32_t value = 0U;
    for (uint8_t i = plen; i < len; i++)
    {
        if ((buf[i] < '0') || (buf[i] > '9'))
        {
            return false;
        }
        value = (value * 10U) + (uint32_t)(buf[i] - '0');
    }

    if (value > 65535U)
    {
        return false;
    }
    *n = (uint16_t)value;
    return true;
}

bool Ping_Feed(PingParser *p, uint8_t byte, uint16_t *n)
{
    if ((byte == (uint8_t)'\r') || (byte == (uint8_t)'\n'))
    {
        bool found = (!p->discarding) && (p->len > 0U) && parse_line(p->buf, p->len, n);
        p->len        = 0U;
        p->discarding = false;
        return found;
    }

    if (p->discarding)
    {
        return false;
    }

    /* a full buffer is cleared and the rest of that line is skipped so its
     * tail cannot be mistaken for a short line of its own */
    if (p->len >= PING_BUF_SIZE)
    {
        p->len        = 0U;
        p->discarding = true;
        return false;
    }

    p->buf[p->len++] = (char)byte;
    return false;
}
