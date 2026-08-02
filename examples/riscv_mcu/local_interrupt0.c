#include "ag32.h"

#ifndef LOCAL_INT_BIT
#define LOCAL_INT_BIT 0u
#endif

/* SRAM-only qualification for one fabric local_int hard-boundary lane. */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

static inline uint32_t csr_mie(void) {
    uint32_t value;
    __asm__ volatile("csrr %0, mie" : "=r"(value));
    return value;
}

static inline uint32_t csr_mip(void) {
    uint32_t value;
    __asm__ volatile("csrr %0, mip" : "=r"(value));
    return value;
}

void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    uint32_t cause = AG32_MCAUSE_CODE(mcause);
    if ((mcause & AG32_MCAUSE_INTERRUPT) && cause == 16u + LOCAL_INT_BIT) {
        /* The source image holds the lane high. Mask before mret so one level
         * cannot immediately retrigger and obscure the first observation. */
        mailbox[4] = csr_mie();
        mailbox[5] = csr_mip();
        ag32_disable_machine_interrupt_mask(0x000f0000u);
        mailbox[2] = mcause;
        mailbox[3] += 1u;
        mailbox[8] = mepc;
        mailbox[9] = mtval;
        mailbox[1] = 0x4c494e54u; /* "LINT" */
        return;
    }

    mailbox[1] = 0x4641494cu; /* "FAIL" */
    mailbox[2] = mcause;
    mailbox[8] = mepc;
    mailbox[9] = mtval;
    ag32_disable_machine_interrupts();
    for (;;) { }
}

int main(void) {
    for (unsigned int i = 0; i < 12; ++i)
        mailbox[i] = 0u;
    mailbox[11] = LOCAL_INT_BIT;

    ag32_disable_machine_interrupts();
    ag32_disable_machine_interrupt_mask(0x000f0000u);
    mailbox[0] = ag32_fcb_config((const uint32_t *)0x20002000u, 24986u);
    mailbox[10] = csr_mip();
    ag32_enable_machine_interrupt_mask(AG32_MIE_LOCAL(LOCAL_INT_BIT));
    ag32_enable_machine_interrupts();

    while (mailbox[1] == 0u) { }
    ag32_disable_machine_interrupts();
    mailbox[6] = csr_mie();
    mailbox[7] = csr_mip();
    for (;;) { }
}
