/**
 * ping.h - receive side of the serial link: a byte ring and the ping parser
 *
 * no HAL header, so it builds on a host compiler.  the receive interrupt
 * pushes bytes into the ring and the main loop pops them into the parser, so
 * the parser never runs in an interrupt and nothing here ever blocks.
 */

#ifndef PING_H
#define PING_H

#include <stdbool.h>
#include <stdint.h>

/* ---- byte ring, one producer (interrupt) and one consumer (main loop) ---- */

#define BYTE_RING_SIZE  64U     /* a power of two so the index wrap is a mask */

typedef struct
{
    uint8_t          data[BYTE_RING_SIZE];
    volatile uint8_t head;      /* next write index, moved only by the producer */
    volatile uint8_t tail;      /* next read index, moved only by the consumer */
} ByteRing;

void ByteRing_Init(ByteRing *r);

/* returns false and drops the byte when the ring is full */
bool ByteRing_Push(ByteRing *r, uint8_t byte);

/* returns false when the ring is empty */
bool ByteRing_Pop(ByteRing *r, uint8_t *byte);

/* ---- ping parser ---- */

/* "PING:65535" is 10 bytes.  16 leaves room for a little noise in front.
 * a line that fills the buffer is thrown away. */
#define PING_BUF_SIZE   16U

typedef struct
{
    char    buf[PING_BUF_SIZE];
    uint8_t len;
    bool    discarding;     /* the line overflowed, skip to its end */
} PingParser;

void Ping_Init(PingParser *p);

/**
 * Ping_Feed: give the parser one received byte.
 * returns true and sets *n when the byte ends a line that is exactly
 * "PING:<n>" with n a decimal from 0 to 65535.  CR, LF and CR LF all end a
 * line.  anything else is ignored.
 */
bool Ping_Feed(PingParser *p, uint8_t byte, uint16_t *n);

#endif /* PING_H */
