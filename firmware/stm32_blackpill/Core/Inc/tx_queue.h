/**
 * tx_queue.h - the queue of messages waiting for the UART transmitter
 *
 * no HAL header, so it builds on a host compiler.  the transmitter sends one
 * message at a time by interrupt, straight from the queue's own storage, so a
 * message that has been handed to it must not be touched until it has gone out.
 * every message is therefore copied into a slot on the way in, a slot is
 * released only when the transfer that used it has finished and a message
 * that arrives while another is on the wire waits behind it.
 *
 * all of it runs in the main loop: the interrupt only moves bytes that the
 * HAL already holds, so nothing here needs a lock.
 */

#ifndef TX_QUEUE_H
#define TX_QUEUE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* a data line is at most 160 bytes, a pong at most 17 */
#define TX_SLOT_BYTES   160U
#define TX_SLOTS        4U

/* at most this many pongs wait at once, the one on the wire included, so a
 * burst of pings can never fill the queue and keep a data line out.  a pong
 * past the limit is dropped and counted: the hub asks again in 30 s */
#define TX_MAX_PONGS    2U

typedef struct
{
    uint8_t  data[TX_SLOT_BYTES];
    uint16_t len;
    bool     is_pong;
} TxSlot;

typedef struct
{
    TxSlot   slot[TX_SLOTS];
    uint8_t  head;              /* index of the oldest message */
    uint8_t  count;             /* messages queued, the one on the wire included */
    uint8_t  pongs;             /* of which pongs */
    bool     in_flight;         /* the oldest message has been handed to the transmitter */
    uint32_t lines_dropped;     /* a line arrived with every slot taken */
    uint32_t pongs_dropped;     /* a pong arrived with the pong limit or every slot taken */
} TxQueue;

void TxQueue_Init(TxQueue *q);

/* copy a message in.  false means it was dropped and counted */
bool TxQueue_PushLine(TxQueue *q, const uint8_t *data, size_t len);
bool TxQueue_PushPong(TxQueue *q, const uint8_t *data, size_t len);

/* true when a data line would be accepted now */
bool TxQueue_LineSpace(const TxQueue *q);

/* hand the oldest message to the transmitter.  returns false when nothing is
 * waiting or one is already on the wire.  the pointer stays valid until
 * TxQueue_Done */
bool TxQueue_Start(TxQueue *q, const uint8_t **data, uint16_t *len);

/* the transfer that TxQueue_Start began has finished: release its slot */
void TxQueue_Done(TxQueue *q);

#endif /* TX_QUEUE_H */
