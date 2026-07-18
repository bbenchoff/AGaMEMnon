#ifndef AGAMEMNON_AG32_WATCHDOG_H
#define AGAMEMNON_AG32_WATCHDOG_H

#include <stdint.h>

#include "ag32_device.h"
#include "ag32_sysctl.h"

/*
 * Programmable APB watchdog from AG32 Reference Manual section 9.3. This is
 * distinct from the option-controlled 12-bit independent watchdog in 9.2.
 */
typedef struct {
    volatile uint32_t LOAD;       /* 0x000 */
    volatile const uint32_t VALUE;/* 0x004 */
    volatile uint32_t CONTROL;    /* 0x008 */
    volatile uint32_t INTCLR;     /* 0x00c, write-only */
    volatile const uint32_t RIS;  /* 0x010 */
    volatile const uint32_t MIS;  /* 0x014 */
    uint32_t reserved_018_bfc[762];
    volatile uint32_t LOCK;       /* 0xc00 */
} ag32_watchdog_t;

#define AG32_WATCHDOG0 \
    ((ag32_watchdog_t *)(uintptr_t)AG32_WATCHDOG0_BASE)

#define AG32_WATCHDOG_INT_ENABLE   (1u << 0)
#define AG32_WATCHDOG_RESET_ENABLE (1u << 1)
#define AG32_WATCHDOG_UNLOCK_KEY   0x1ACCE551u

static inline void ag32_watchdog_unlock(ag32_watchdog_t *watchdog) {
    watchdog->LOCK = AG32_WATCHDOG_UNLOCK_KEY;
}

static inline void ag32_watchdog_lock(ag32_watchdog_t *watchdog) {
    watchdog->LOCK = 0u;
}

static inline void ag32_watchdog_configure(
    ag32_watchdog_t *watchdog, uint32_t load, int reset_enable
) {
    ag32_apb_enable(AG32_APB_WATCHDOG0);
    ag32_watchdog_unlock(watchdog);
    watchdog->CONTROL = 0u;
    watchdog->LOAD = load ? load : 1u;
    watchdog->CONTROL = AG32_WATCHDOG_INT_ENABLE |
        (reset_enable ? AG32_WATCHDOG_RESET_ENABLE : 0u);
    ag32_watchdog_lock(watchdog);
}

static inline void ag32_watchdog_feed(ag32_watchdog_t *watchdog) {
    ag32_watchdog_unlock(watchdog);
    watchdog->INTCLR = 1u;
    ag32_watchdog_lock(watchdog);
}

static inline void ag32_watchdog_disable(ag32_watchdog_t *watchdog) {
    ag32_watchdog_unlock(watchdog);
    watchdog->CONTROL = 0u;
    ag32_watchdog_lock(watchdog);
}

static inline uint32_t ag32_watchdog_value(
    const ag32_watchdog_t *watchdog
) {
    return watchdog->VALUE;
}

#endif
