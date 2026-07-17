#ifndef AGAMEMNON_AG32_H
#define AGAMEMNON_AG32_H

#include "ag32_device.h"
#include "ag32_sysctl.h"

#define SYSCTL_CLKCTRL AG32_REG32(AG32_SYSCTL_BASE + 0x0C)
#define SYSCTL_APBCLK  AG32_REG32(AG32_SYSCTL_BASE + 0x60)
#define SYSCTL_AHBCLK  AG32_REG32(AG32_SYSCTL_BASE + 0x70)
#define SYSCTL_DEVID   AG32_REG32(AG32_SYSCTL_BASE + 0x100)
#define APBCLK_FCB     (1u << 0)
#define APBCLK_GPIO4   (1u << 8)
#define APBCLK_TIMER0  (1u << 14)

#define CLINT_MTIMELO AG32_REG32(AG32_CLINT_BASE + 0xBFF8)
#define CLINT_MTIMEHI AG32_REG32(AG32_CLINT_BASE + 0xBFFC)

#define FCB_CTRL AG32_REG32(AG32_FCB0_BASE + 0x00)
#define FCB_DATA AG32_REG32(AG32_FCB0_BASE + 0x0C)
#define FCB_STAT AG32_REG32(AG32_FCB0_BASE + 0x10)
#define FCB_CTRL_AUTO (1u << 6)
#define FCB_STAT_OK 0x000f0002u

#define GPIO4_DATA(mask) AG32_REG32(AG32_GPIO4_BASE + ((uint32_t)(mask) << 2))
#define GPIO4_DIR   AG32_REG32(AG32_GPIO4_BASE + 0x400)
#define GPIO4_AFSEL AG32_REG32(AG32_GPIO4_BASE + 0x420)
#define BOARD_LED_MASK 0x1Eu

#define TIMER0_LOAD1   AG32_REG32(AG32_TIMER0_BASE + 0x00)
#define TIMER0_CTRL1   AG32_REG32(AG32_TIMER0_BASE + 0x08)
#define TIMER0_INTCLR1 AG32_REG32(AG32_TIMER0_BASE + 0x0C)
#define TIMER0_RIS1    AG32_REG32(AG32_TIMER0_BASE + 0x10)
#define TIMER_CTRL_SIZE32   (1u << 1)
#define TIMER_CTRL_PERIODIC (1u << 6)
#define TIMER_CTRL_ENABLE   (1u << 7)

static inline uint64_t ag32_mtime(void) {
    uint32_t hi0, lo, hi1;
    do {
        hi0 = CLINT_MTIMEHI;
        lo = CLINT_MTIMELO;
        hi1 = CLINT_MTIMEHI;
    } while (hi0 != hi1);
    return ((uint64_t)hi1 << 32) | lo;
}

static inline void ag32_mtime_delay(uint64_t ticks) {
    uint64_t deadline = ag32_mtime() + ticks;
    while ((int64_t)(ag32_mtime() - deadline) < 0) { }
}

static inline uint32_t ag32_fcb_config(const uint32_t *image, uint32_t words) {
    SYSCTL_CLKCTRL &= ~0x27u;
    SYSCTL_APBCLK |= APBCLK_FCB;
    FCB_CTRL = FCB_CTRL_AUTO;
    for (uint32_t i = 0; i < words; ++i)
        FCB_DATA = image[i];
    return FCB_STAT;
}

/* Polling drivers built only from the published AG32 register manual. */
#include "ag32_uart.h"
#include "ag32_spi.h"
#include "ag32_i2c.h"
#include "ag32_dma.h"

#endif
