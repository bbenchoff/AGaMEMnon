#include "ag32.h"

/*
 * Non-destructive exception demonstration. ECALL is a synchronous,
 * architecturally defined four-byte instruction; the handler records it and
 * advances MEPC so execution can resume.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    mailbox[0] = 0x45584350u; /* "EXCP" */
    mailbox[1] = mcause;
    mailbox[2] = mepc;
    mailbox[3] = mtval;

    if (mcause == AG32_EXCEPTION_ECALL_M) {
        ag32_mepc_write(mepc + 4u);
        return;
    }

    for (;;) { }
}

int main(void) {
    mailbox[0] = 0u;
    mailbox[1] = 0u;
    mailbox[2] = 0u;
    mailbox[3] = 0u;

    __asm__ volatile("ecall");
    mailbox[0] = 0x50415353u; /* "PASS": the handler returned via MRET. */

    for (;;) { }
}
