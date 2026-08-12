#include "ag32.h"

/*
 * Non-destructive supervised-watchdog qualification. Arms WATCHDOG0 with
 * reset-enable and a bounded reload, records that the down-counter advances,
 * then deliberately stops feeding it so the second timeout resets the MCU.
 * The reset is a warm CPU reset (no flash write); the sticky reset-cause flag
 * proves the supervised reset fired. The host clears the flag and resets the
 * board clean afterward.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;
#define RST_CNTL (*(volatile uint32_t *)0x03000004u)

int main(void) {
    mailbox[0] = 0x57445432u;      /* "WDT2" */
    mailbox[1] = RST_CNTL;         /* reset-cause as found (host clears first) */

    uint32_t before = AG32_WATCHDOG0->VALUE;
    ag32_watchdog_configure(AG32_WATCHDOG0, 0x00200000u, 1 /* reset_enable */);

    /* brief bounded spin so the counter visibly advances */
    for (volatile uint32_t i = 0; i < 2000u; ++i) { }
    uint32_t after = AG32_WATCHDOG0->VALUE;

    mailbox[2] = before;
    mailbox[3] = after;            /* after < before proves it is counting */
    mailbox[4] = 0x41524d44u;      /* "ARMD": from here we never feed it */

    for (;;) { }                   /* supervised reset ends this program */
}
