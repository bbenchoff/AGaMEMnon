#include "ag32.h"

/* SRAM-only qualification for four simultaneously routed, independent
 * fabric local-interrupt sources.  The matching fabric image derives lane n
 * from External-AHB address bit 2+n. */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

static inline uint32_t csr_mip(void) {
    uint32_t value;
    __asm__ volatile("csrr %0, mip" : "=r"(value));
    return value;
}

void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    uint32_t cause = AG32_MCAUSE_CODE(mcause);
    if ((mcause & AG32_MCAUSE_INTERRUPT) && cause >= 16u && cause <= 19u) {
        uint32_t lane = cause - 16u;
        mailbox[4u + lane] += 1u;
        mailbox[8u + lane] = mcause;
        mailbox[12u + lane] = csr_mip();
        mailbox[2] |= 1u << lane;
        /* A level may remain high after the address phase. Mask it before
         * mret; main explicitly arms only the next lane. */
        ag32_disable_machine_interrupt_mask(AG32_MIE_LOCAL(lane));
        return;
    }

    mailbox[1] = 0x4641494cu; /* "FAIL" */
    mailbox[16] = mcause;
    mailbox[17] = mepc;
    mailbox[18] = mtval;
    ag32_disable_machine_interrupts();
    for (;;) { }
}

int main(void) {
    for (unsigned int i = 0; i < 32; ++i)
        mailbox[i] = 0u;

    ag32_disable_machine_interrupts();
    ag32_disable_machine_interrupt_mask(0x000f0000u);
    mailbox[0] = ag32_fcb_config((const uint32_t *)0x20002000u, 24986u);

    for (uint32_t lane = 0; lane < 4u; ++lane) {
        volatile uint32_t *const trigger =
            (volatile uint32_t *)(0x60000000u + (1u << (2u + lane)));
        mailbox[3] = lane;
        ag32_disable_machine_interrupt_mask(0x000f0000u);
        ag32_enable_machine_interrupt_mask(AG32_MIE_LOCAL(lane));
        ag32_enable_machine_interrupts();

        for (uint32_t attempt = 0; attempt < 1024u && !(mailbox[2] & (1u << lane)); ++attempt)
            mailbox[20u + lane] = *trigger;

        ag32_disable_machine_interrupts();
        ag32_disable_machine_interrupt_mask(0x000f0000u);
        mailbox[24u + lane] = csr_mip();
    }

    mailbox[1] = mailbox[2] == 0x0fu ? 0x4c494e41u : 0x4641494cu; /* "LINA" / "FAIL" */
    for (;;) { }
}
