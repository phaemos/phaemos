/**
 * crc16.c - CRC-16/CCITT-FALSE
 *
 * computed bit by bit rather than from a 256-entry table.  a line is under
 * 160 bytes and is sent once per 1.28 s, so the few thousand cycles cost
 * nothing and the table's 512 bytes of flash are saved.
 */

#include "crc16.h"

uint16_t CRC16_Compute(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFU;

    for (size_t i = 0U; i < len; i++)
    {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (uint8_t bit = 0U; bit < 8U; bit++)
        {
            crc = (crc & 0x8000U) ? (uint16_t)((crc << 1) ^ 0x1021U)
                                  : (uint16_t)(crc << 1);
        }
    }
    return crc;
}
