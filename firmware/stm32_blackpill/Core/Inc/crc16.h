/**
 * crc16.h - CRC-16/CCITT-FALSE for the serial line checksum
 *
 * polynomial 0x1021, start value 0xFFFF, no reflection, no final XOR.  the
 * check value for the ASCII string "123456789" is 0x29B1.  no HAL header, so
 * it builds on a host compiler.
 */

#ifndef CRC16_H
#define CRC16_H

#include <stddef.h>
#include <stdint.h>

uint16_t CRC16_Compute(const uint8_t *data, size_t len);

#endif /* CRC16_H */
