#ifndef AGAMEMNON_AG32_RTC_H
#define AGAMEMNON_AG32_RTC_H

/*
 * Open AG32 RTC driver, derived only from the published AG32 register map
 * (backup-domain RTC: CRH/CRL control, PRL prescaler, DIV divider, CNT
 * 32-bit counter split high/low, ALR alarm, BDCR backup-domain control with
 * the clock-source select and RTC enable). No vendor code is copied.
 *
 * The counter is the concatenation {CNTH,CNTL}. The prescaler PRL divides the
 * selected low-speed clock; DIV is the live down-counter reload snapshot.
 * BDCR selects the source (LSI internal / LSE external 32 kHz) and enables the
 * RTC. Writes to the backup domain may require a platform backup-access
 * enable; callers should verify RTCEN reads back before trusting the counter.
 */

#include <stdint.h>

#include "ag32_device.h"

#define AG32_RTC_BASE 0x40000000u

typedef struct {
    volatile uint16_t CRH;   uint16_t _r0;   /* 0x00 control high (int enables) */
    volatile uint16_t CRL;   uint16_t _r1;   /* 0x04 control low  (flags)        */
    volatile uint16_t PRLH;  uint16_t _r2;   /* 0x08 prescaler load high         */
    volatile uint16_t PRLL;  uint16_t _r3;   /* 0x0c prescaler load low          */
    volatile const uint16_t DIVH; uint16_t _r4; /* 0x10 divider high (live)      */
    volatile const uint16_t DIVL; uint16_t _r5; /* 0x14 divider low  (live)      */
    volatile uint16_t CNTH;  uint16_t _r6;   /* 0x18 counter high                */
    volatile uint16_t CNTL;  uint16_t _r7;   /* 0x1c counter low                 */
    volatile uint16_t ALRH;  uint16_t _r8;   /* 0x20 alarm high                  */
    volatile uint16_t ALRL;  uint16_t _r9;   /* 0x24 alarm low                   */
    volatile uint16_t RCYC;  uint16_t _r10;  /* 0x28 read minimum cycle          */
    uint32_t _r11;                            /* 0x2c                            */
    volatile uint16_t BDCR;                   /* 0x30 backup-domain control       */
    volatile uint16_t BDRST;                  /* 0x32 backup-domain reset         */
} ag32_rtc_t;

#define AG32_RTC ((ag32_rtc_t *)(uintptr_t)AG32_RTC_BASE)

/* CRL flags */
#define AG32_RTC_FLAG_SEC   (1u << 0)  /* second */
#define AG32_RTC_FLAG_ALR   (1u << 1)  /* alarm */
#define AG32_RTC_FLAG_OW    (1u << 2)  /* overflow */
#define AG32_RTC_FLAG_RSF   (1u << 3)  /* registers synchronized */
#define AG32_RTC_FLAG_RTOFF (1u << 5)  /* operation off (write-ready) */

/* BDCR */
#define AG32_RTC_BDCR_LSEON  (1u << 0)
#define AG32_RTC_BDCR_LSERDY (1u << 1)
#define AG32_RTC_BDCR_RTCEN  (1u << 15)
#define AG32_RTC_BDCR_RTCSEL_OFFSET 8u
#define AG32_RTC_BDCR_RTCSEL_MASK   (3u << AG32_RTC_BDCR_RTCSEL_OFFSET)
#define AG32_RTC_CLK_LSE   (1u << AG32_RTC_BDCR_RTCSEL_OFFSET)
#define AG32_RTC_CLK_LSI   (2u << AG32_RTC_BDCR_RTCSEL_OFFSET)

static inline uint32_t ag32_rtc_counter(void) {
    /* re-read on rollover of the low half */
    for (;;) {
        uint16_t hi = AG32_RTC->CNTH;
        uint16_t lo = AG32_RTC->CNTL;
        if (hi == AG32_RTC->CNTH)
            return ((uint32_t)hi << 16) | lo;
    }
}

/* Select the RTC clock source and enable the counter. Returns non-zero if the
 * RTC enable did not read back (e.g. the backup domain is write-protected on
 * this platform). Bounded: no unbounded LSE-ready or RSF spin. */
static inline int ag32_rtc_enable(uint32_t clk_source, uint32_t prescaler) {
    uint16_t bdcr = AG32_RTC->BDCR;
    bdcr = (uint16_t)((bdcr & ~AG32_RTC_BDCR_RTCSEL_MASK) | clk_source
                      | AG32_RTC_BDCR_RTCEN);
    if (clk_source == AG32_RTC_CLK_LSE)
        bdcr |= AG32_RTC_BDCR_LSEON;
    AG32_RTC->BDCR = bdcr;
    AG32_RTC->PRLH = (uint16_t)((prescaler >> 16) & 0x000fu);
    AG32_RTC->PRLL = (uint16_t)(prescaler & 0xffffu);
    return (AG32_RTC->BDCR & AG32_RTC_BDCR_RTCEN) ? 0 : 1;
}

#endif /* AGAMEMNON_AG32_RTC_H */
