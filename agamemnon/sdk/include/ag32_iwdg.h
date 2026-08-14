#ifndef AGAMEMNON_AG32_IWDG_H
#define AGAMEMNON_AG32_IWDG_H

/*
 * Open AG32 independent watchdog (IWDG) driver, written from the published
 * register map. The IWDG is a single control register living inside the RTC /
 * backup domain at RTC_BASE + 0x34, clocked by the low-speed oscillator (LSI
 * or LSE) so it keeps running when the main clock is stopped. It has a 3-bit
 * prescaler, a low-speed clock select, stop/standby freeze bits, an enable,
 * and a reload field that is "kicked" by writing a fixed reload key. No vendor
 * code is copied.
 *
 * Every write to the backup domain must wait for the RTC operation-off flag
 * (RTC CRL bit 5) before the write takes effect. Because that flag never
 * asserts without a running low-speed clock, all waits here are bounded.
 */

#include <stdint.h>

#include "ag32_device.h"

/* 16-bit register in the backup domain. */
#define AG32_IWDG_REG   (*(volatile uint16_t *)(uintptr_t)(AG32_RTC_BASE + 0x34u))
/* RTC control-low register carries the operation-off (write-ready) flag. */
#define AG32_IWDG_RTC_CRL (*(volatile uint16_t *)(uintptr_t)(AG32_RTC_BASE + 0x04u))
#define AG32_IWDG_RTOFF (1u << 5)

#define AG32_IWDG_PRESCALER_MASK 0x0007u
#define AG32_IWDG_STOP_FREEZE    (1u << 4)
#define AG32_IWDG_STANDBY_FREEZE (1u << 5)
#define AG32_IWDG_CLKSEL_LSE     (1u << 6)   /* 0 = LSI, 1 = LSE          */
#define AG32_IWDG_ENABLE         (1u << 8)
#define AG32_IWDG_RELOAD_MASK    0xf000u
#define AG32_IWDG_RELOAD_KEY     0xa000u     /* write to kick the counter */

/* Wait (bounded) until a backup-domain write may proceed. Returns -1 on
 * timeout, which on this part means no low-speed clock is running. */
static inline int ag32_iwdg_wait_ready(uint32_t timeout) {
    while (!(AG32_IWDG_RTC_CRL & AG32_IWDG_RTOFF)) {
        if (!timeout--)
            return -1;
    }
    return 0;
}

static inline int ag32_iwdg_modify(uint16_t clear_mask, uint16_t set_mask,
                                   uint32_t timeout) {
    if (ag32_iwdg_wait_ready(timeout))
        return -1;
    AG32_IWDG_REG = (uint16_t)((AG32_IWDG_REG & ~clear_mask) | set_mask);
    return ag32_iwdg_wait_ready(timeout);
}

/* prescaler is 0..7 (divides the low-speed clock); clk_lse selects LSE over
 * LSI; freeze OR-combines AG32_IWDG_STOP_FREEZE / _STANDBY_FREEZE. */
static inline int ag32_iwdg_configure(uint32_t prescaler, int clk_lse,
                                      uint16_t freeze, uint32_t timeout) {
    uint16_t set = (uint16_t)((prescaler & AG32_IWDG_PRESCALER_MASK) |
                              (clk_lse ? AG32_IWDG_CLKSEL_LSE : 0u) |
                              (freeze & (AG32_IWDG_STOP_FREEZE |
                                         AG32_IWDG_STANDBY_FREEZE)));
    uint16_t clear = (uint16_t)(AG32_IWDG_PRESCALER_MASK | AG32_IWDG_CLKSEL_LSE |
                                AG32_IWDG_STOP_FREEZE | AG32_IWDG_STANDBY_FREEZE);
    return ag32_iwdg_modify(clear, set, timeout);
}

static inline int ag32_iwdg_enable(uint32_t timeout) {
    return ag32_iwdg_modify(0u, AG32_IWDG_ENABLE, timeout);
}

static inline int ag32_iwdg_disable(uint32_t timeout) {
    return ag32_iwdg_modify(AG32_IWDG_ENABLE, 0u, timeout);
}

/* Kick the watchdog by writing the reload key into the reload field. */
static inline int ag32_iwdg_reload(uint32_t timeout) {
    return ag32_iwdg_modify(AG32_IWDG_RELOAD_MASK, AG32_IWDG_RELOAD_KEY, timeout);
}

static inline int ag32_iwdg_is_enabled(void) {
    return (AG32_IWDG_REG & AG32_IWDG_ENABLE) ? 1 : 0;
}

#endif /* AGAMEMNON_AG32_IWDG_H */
