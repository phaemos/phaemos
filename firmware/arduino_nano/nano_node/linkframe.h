#pragma once
// linkframe.h - checksum helpers for the serial link, free of any Arduino header
//
// kept apart from the sketch so the same code can be compiled and tested on a host.

#include <stddef.h>
#include <stdint.h>

// CRC-16/CCITT-FALSE: polynomial 0x1021, start value 0xFFFF, no reflection and no final XOR.
// the check value for the ASCII string "123456789" is 0x29B1.  it is computed bit by bit
// because a 256 entry table would cost 512 bytes of the 2 kB of RAM or the same of flash.
static inline uint16_t link_crc16(const uint8_t *data, size_t len) {
    uint16_t crc = 0xFFFF;
    while (len--) {
        crc ^= (uint16_t)(*data++) << 8;
        for (uint8_t bit = 0; bit < 8; bit++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

// four upper-case hex digits of a 16 bit value, not terminated.  no lookup table so no RAM is used.
static inline void link_hex4(uint16_t value, char *out) {
    for (uint8_t i = 0; i < 4; i++) {
        uint8_t nibble = (value >> (12 - 4 * i)) & 0x0F;
        out[i] = (char)(nibble < 10 ? '0' + nibble : 'A' + (nibble - 10));
    }
}
