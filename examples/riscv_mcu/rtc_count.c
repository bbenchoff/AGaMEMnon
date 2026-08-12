#include "ag32.h"

/*
 * Non-destructive RTC qualification: snapshot the backup-domain RTC, select
 * the internal low-speed clock, enable the counter, and sample it twice across
 * a fixed MTIME window to prove it advances. Bounded (no unbounded ready/sync
 * spins), so a write-protected backup domain or absent low-speed clock yields
 * an honest reported negative rather than a hang. No flash, no pins.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;
#define MTIME_LO (*(volatile uint32_t *)0x0200bff8u)

int main(void) {
    mailbox[0] = 0x52544330u;                 /* "RTC0" */
    mailbox[1] = AG32_RTC->BDCR;              /* backup-domain control as-found */
    uint32_t c0_asfound = ag32_rtc_counter();

    int enable_fail = ag32_rtc_enable(AG32_RTC_CLK_LSI, 0x7fffu);
    mailbox[2] = AG32_RTC->BDCR;              /* BDCR after enable (RTCEN stuck?) */
    mailbox[3] = (uint32_t)enable_fail;

    uint32_t first = ag32_rtc_counter();
    uint32_t start = MTIME_LO;
    while ((uint32_t)(MTIME_LO - start) < 2000000u) { }  /* ~fixed window */
    uint32_t second = ag32_rtc_counter();

    mailbox[4] = c0_asfound;
    mailbox[5] = first;
    mailbox[6] = second;                      /* second > first => RTC counting */
    mailbox[7] = (second != first) ? 0x50415353u /* "PASS" */ : 0x4e4f4e45u /* "NONE" */;
    mailbox[8] = 0xc0ffee12u;
    for (;;) { }
}
