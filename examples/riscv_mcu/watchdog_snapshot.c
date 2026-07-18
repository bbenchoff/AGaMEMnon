#include "ag32.h"

/*
 * Read-only watchdog qualification candidate. It temporarily enables the APB
 * clock, snapshots public status, and restores the original clock-gate state.
 * Run after reset; it never unlocks, starts, clears, or reprograms the block.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

int main(void) {
    uint32_t apb_before = AG32_SYSCTL_APB_ENABLE;
    ag32_apb_enable(AG32_APB_WATCHDOG0);

    mailbox[0] = 0x57445430u; /* "WDT0" */
    mailbox[1] = AG32_WATCHDOG0->VALUE;
    mailbox[2] = AG32_WATCHDOG0->CONTROL;
    mailbox[3] = (AG32_WATCHDOG0->RIS & 1u) |
        ((AG32_WATCHDOG0->MIS & 1u) << 1) |
        ((AG32_WATCHDOG0->LOCK & 1u) << 2);

    if (!(apb_before & AG32_APB_WATCHDOG0))
        AG32_SYSCTL_APB_ENABLE &= ~AG32_APB_WATCHDOG0;
    for (;;) { }
}
