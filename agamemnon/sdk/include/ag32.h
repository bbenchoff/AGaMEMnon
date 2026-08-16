#ifndef AGAMEMNON_AG32_H
#define AGAMEMNON_AG32_H

#include "ag32_device.h"
#include "ag32_sysctl.h"
#include "ag32_interrupt.h"

/* Legacy aliases; ag32_sysctl.h carries the named fields and accessors. */
#define SYSCTL_CLKCTRL AG32_REG32(AG32_SYSCTL_BASE + 0x0C)
#define SYSCTL_APBCLK  AG32_REG32(AG32_SYSCTL_BASE + 0x60)
#define SYSCTL_AHBCLK  AG32_REG32(AG32_SYSCTL_BASE + 0x70)
#define SYSCTL_DEVID   AG32_REG32(AG32_SYSCTL_BASE + 0x100)
#define APBCLK_FCB     (1u << 0)
#define APBCLK_GPIO4   (1u << 8)
#define APBCLK_GPIO5   (1u << 9)
#define APBCLK_TIMER0  (1u << 14)

#define CLINT_MTIMELO AG32_REG32(AG32_CLINT_BASE + 0xBFF8)
#define CLINT_MTIMEHI AG32_REG32(AG32_CLINT_BASE + 0xBFFC)

/*
 * FCB0 -- fabric configuration block.
 *
 * NAMING: 0x0C is the AUTO-mode streaming port, not the generic data register.
 * The recovered register layout is CTRL 0x00, ADDR 0x04, DATA 0x08, AUTO 0x0C,
 * STAT 0x10. `ag32_fcb_config()` below sets CTRL.AUTO and then pushes the whole
 * image into 0x0C, i.e. it uses the auto-config path -- so 0x0C is AUTO. This
 * header historically called it `FCB_DATA`, which sent people hunting for a
 * "DATA" register at the wrong offset; `FCB_DATA` is kept only as a compatibility
 * alias. The per-chain path (set ADDR, then write words to DATA at 0x08 with
 * CTRL.WRITE|CTRL.UPDATE, then ACTIVATE) is a different sequence and is NOT what
 * this header does.
 */
#define FCB_CTRL AG32_REG32(AG32_FCB0_BASE + 0x00)
#define FCB_ADDR AG32_REG32(AG32_FCB0_BASE + 0x04)
#define FCB_DATA_PORT AG32_REG32(AG32_FCB0_BASE + 0x08) /* per-chain data */
#define FCB_AUTO AG32_REG32(AG32_FCB0_BASE + 0x0C)      /* auto-config stream */
#define FCB_DATA FCB_AUTO   /* deprecated alias: 0x0C is AUTO, not DATA */
#define FCB_STAT AG32_REG32(AG32_FCB0_BASE + 0x10)
#define FCB_CTRL_AUTO (1u << 6)
/* STAT_OK = ACTIVE|INIT_EMB|CFGDONE|CHIP_RSTB|DEVOE (bits 1,16,17,18,19).
 * Note bit 0 (INIT) is NOT set in this value. Error bits live at 4 (ID),
 * 5 (HEADER) and 6 (CRC) -- a stale-CRC image returns exactly 0x40. */
#define FCB_STAT_OK 0x000f0002u
#define FCB_STAT_ERR_ID     (1u << 4)
#define FCB_STAT_ERR_HEADER (1u << 5)
#define FCB_STAT_ERR_CRC    (1u << 6)

#define GPIO4_DATA(mask) AG32_REG32(AG32_GPIO4_BASE + ((uint32_t)(mask) << 2))
#define GPIO4_DIR   AG32_REG32(AG32_GPIO4_BASE + 0x400)
#define GPIO4_AFSEL AG32_REG32(AG32_GPIO4_BASE + 0x420)
#define GPIO5_DATA(mask) AG32_REG32(AG32_GPIO5_BASE + ((uint32_t)(mask) << 2))
#define GPIO5_DIR   AG32_REG32(AG32_GPIO5_BASE + 0x400)
#define GPIO5_AFSEL AG32_REG32(AG32_GPIO5_BASE + 0x420)
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

/*
 * Stream a fabric configuration image through FCB0 and return FCB_STAT
 * (FCB_STAT_OK on success).
 *
 * CLOCK SIDE EFFECT, read this before computing any baud rate afterwards: the
 * first line clears CLK_CNTL's source-select field plus the HSE and PLL enables
 * (0x27 == AG32_CLK_SOURCE_MASK | AG32_CLK_HSE_ON | AG32_CLK_PLL_ON), selecting
 * the reset-default source for the duration of the transfer and leaving it
 * selected. Nothing in this SDK switches back. Do not derive a bit rate from an
 * assumed SYSCLK afterwards: the clock tree is not characterized, and this call
 * itself changes the source selection. See the per-domain
 * measurements and helpers in ag32_sysctl.h.
 */
static inline uint32_t ag32_fcb_config(const uint32_t *image, uint32_t words) {
    SYSCTL_CLKCTRL &= ~(AG32_CLK_SOURCE_MASK | AG32_CLK_HSE_ON | AG32_CLK_PLL_ON);
    SYSCTL_APBCLK |= APBCLK_FCB;
    FCB_CTRL = FCB_CTRL_AUTO;
    for (uint32_t i = 0; i < words; ++i)
        FCB_AUTO = image[i];        /* 0x0C is the AUTO stream port, not DATA */
    return FCB_STAT;
}

/* Polling drivers built only from the published AG32 register manual. */
#include "ag32_uart.h"
#include "ag32_spi.h"
#include "ag32_i2c.h"
#include "ag32_dma.h"
#include "ag32_crc.h"
#include "ag32_watchdog.h"
#include "ag32_rtc.h"
#include "ag32_iwdg.h"
#include "ag32_gptimer.h"
#include "ag32_can.h"
#include "ag32_mac.h"
#include "ag32_adc.h"
#include "ag32_dac.h"
#include "ag32_comparator.h"

#endif
