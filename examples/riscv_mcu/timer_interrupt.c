#include "ag32.h"

/*
 * Core-local timer interrupt demonstration. MTIME and MTIMECMP are hard-core
 * resources, so this needs no fabric or GPIO route.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    (void)mepc;
    (void)mtval;

    if (mcause == (AG32_MCAUSE_INTERRUPT |
                  AG32_MACHINE_INTERRUPT_TIMER)) {
        ag32_mtimecmp_set(UINT64_MAX);
        mailbox[1] = mcause;
        mailbox[0] = 0x54494D52u; /* "TIMR" */
        return;
    }

    mailbox[0] = 0x4641494Cu; /* "FAIL" */
    ag32_disable_machine_interrupts();
    for (;;) { }
}

int main(void) {
    mailbox[0] = 0u;
    mailbox[1] = 0u;
    ag32_mtimecmp_set(ag32_mtime() + 1000u);
    ag32_enable_machine_timer_interrupt();
    ag32_enable_machine_interrupts();

    while (mailbox[0] == 0u) { }
    ag32_disable_machine_interrupts();
    ag32_disable_machine_interrupt_mask(AG32_MIE_MTIE);

    for (;;) { }
}
