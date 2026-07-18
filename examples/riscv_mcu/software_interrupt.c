#include "ag32.h"

/*
 * Core-local interrupt demonstration. It touches only the CLINT and an SRAM
 * mailbox: no package pin, fabric route, flash sector, or peripheral is used.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    (void)mepc;
    (void)mtval;

    if (mcause == (AG32_MCAUSE_INTERRUPT |
                  AG32_MACHINE_INTERRUPT_SOFTWARE)) {
        ag32_clint_software_interrupt_clear();
        mailbox[1] = mcause;
        mailbox[0] = 0x534F4654u; /* "SOFT" */
        return;
    }

    mailbox[0] = 0x4641494Cu; /* "FAIL" */
    ag32_disable_machine_interrupts();
    for (;;) { }
}

int main(void) {
    mailbox[0] = 0u;
    mailbox[1] = 0u;
    ag32_clint_software_interrupt_clear();
    ag32_enable_machine_software_interrupt();
    ag32_enable_machine_interrupts();
    ag32_clint_software_interrupt_set();

    while (mailbox[0] == 0u) { }
    ag32_disable_machine_interrupts();
    ag32_disable_machine_interrupt_mask(AG32_MIE_MSIE);

    for (;;) { }
}
