#ifndef AGAMEMNON_AG32_CRC_H
#define AGAMEMNON_AG32_CRC_H

#include <stddef.h>
#include <stdint.h>

#include "ag32_device.h"
#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t DR;       /* 0x00: input/result */
    volatile uint32_t IDR;      /* 0x04: low eight bits are scratch */
    volatile uint32_t CR;       /* 0x08 */
    uint32_t reserved_0c;
    volatile uint32_t INIT;     /* 0x10 */
    volatile uint32_t POL;      /* 0x14 */
} ag32_crc_t;

#define AG32_CRC0 ((ag32_crc_t *)(uintptr_t)AG32_CRC0_BASE)

#define AG32_CRC_RESET             (1u << 0)
#define AG32_CRC_POLYSIZE_32       (0u << 3)
#define AG32_CRC_POLYSIZE_16       (1u << 3)
#define AG32_CRC_POLYSIZE_8        (2u << 3)
#define AG32_CRC_POLYSIZE_7        (3u << 3)
#define AG32_CRC_REVERSE_NONE      (0u << 5)
#define AG32_CRC_REVERSE_BYTE      (1u << 5)
#define AG32_CRC_REVERSE_HALFWORD  (2u << 5)
#define AG32_CRC_REVERSE_WORD      (3u << 5)
#define AG32_CRC_REVERSE_OUTPUT    (1u << 7)
#define AG32_CRC32_POLYNOMIAL      0x04C11DB7u

static inline void ag32_crc_configure(
    uint32_t polynomial, uint32_t initial, uint32_t control
) {
    ag32_ahb_enable(AG32_AHB_CRC0);
    AG32_CRC0->INIT = initial;
    AG32_CRC0->POL = polynomial;
    AG32_CRC0->CR = control | AG32_CRC_RESET;
}

static inline void ag32_crc_reset(void) {
    AG32_CRC0->CR |= AG32_CRC_RESET;
}

static inline void ag32_crc_write32(uint32_t value) {
    AG32_CRC0->DR = value;
}

static inline void ag32_crc_write8(uint8_t value) {
    AG32_REG8(AG32_CRC0_BASE) = value;
}

static inline uint32_t ag32_crc_result(void) {
    return AG32_CRC0->DR;
}

static inline uint32_t ag32_crc_bytes(const void *data, size_t length) {
    const uint8_t *bytes = (const uint8_t *)data;
    for (size_t i = 0; i < length; ++i)
        ag32_crc_write8(bytes[i]);
    return ag32_crc_result();
}

#endif
