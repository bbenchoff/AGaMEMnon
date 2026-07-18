#ifndef AGAMEMNON_AG32_INTERRUPT_H
#define AGAMEMNON_AG32_INTERRUPT_H

#include <stdint.h>

/*
 * AG32 MCU Reference Manual v1.2, chapter 6.
 *
 * Core-local software/timer interrupts use the CLINT. The 44 maskable
 * peripheral/fabric interrupt sources use the PLIC, despite some older
 * overview diagrams labelling the CPU interrupt block "ECLIC".
 */
#define AG32_PLIC_BASE                 0x0C000000u
#define AG32_PLIC_SOURCE_COUNT         44u
#define AG32_PLIC_PRIORITY(irq)        (*(volatile uint32_t *)(uintptr_t)(AG32_PLIC_BASE + 4u * (uint32_t)(irq)))
#define AG32_PLIC_PENDING_WORD(word)   (*(volatile uint32_t *)(uintptr_t)(AG32_PLIC_BASE + 0x1000u + 4u * (uint32_t)(word)))
#define AG32_PLIC_ENABLE_WORD(word)    (*(volatile uint32_t *)(uintptr_t)(AG32_PLIC_BASE + 0x2000u + 4u * (uint32_t)(word)))
#define AG32_PLIC_THRESHOLD            (*(volatile uint32_t *)(uintptr_t)(AG32_PLIC_BASE + 0x200000u))
#define AG32_PLIC_CLAIM_COMPLETE       (*(volatile uint32_t *)(uintptr_t)(AG32_PLIC_BASE + 0x200004u))

#define AG32_CLINT_MSIP                (*(volatile uint32_t *)(uintptr_t)0x02000000u)
#define AG32_CLINT_MTIMECMP_LO         (*(volatile uint32_t *)(uintptr_t)0x02004000u)
#define AG32_CLINT_MTIMECMP_HI         (*(volatile uint32_t *)(uintptr_t)0x02004004u)

#define AG32_MSTATUS_MIE               (1u << 3)
#define AG32_MIE_MSIE                  (1u << 3)
#define AG32_MIE_MTIE                  (1u << 7)
#define AG32_MIE_MEIE                  (1u << 11)
#define AG32_MIE_LOCAL(n)              (1u << (16u + (uint32_t)(n)))
#define AG32_MCAUSE_INTERRUPT          (1u << 31)
#define AG32_MCAUSE_CODE(value)        ((uint32_t)(value) & ~AG32_MCAUSE_INTERRUPT)

enum ag32_machine_interrupt {
    AG32_MACHINE_INTERRUPT_SOFTWARE = 3,
    AG32_MACHINE_INTERRUPT_TIMER = 7,
    AG32_MACHINE_INTERRUPT_EXTERNAL = 11,
    AG32_MACHINE_INTERRUPT_LOCAL0 = 16,
    AG32_MACHINE_INTERRUPT_LOCAL1 = 17,
    AG32_MACHINE_INTERRUPT_LOCAL2 = 18,
    AG32_MACHINE_INTERRUPT_LOCAL3 = 19,
};

enum ag32_exception {
    AG32_EXCEPTION_INSTRUCTION_MISALIGNED = 0,
    AG32_EXCEPTION_INSTRUCTION_ACCESS = 1,
    AG32_EXCEPTION_ILLEGAL_INSTRUCTION = 2,
    AG32_EXCEPTION_BREAKPOINT = 3,
    AG32_EXCEPTION_LOAD_MISALIGNED = 4,
    AG32_EXCEPTION_LOAD_ACCESS = 5,
    AG32_EXCEPTION_STORE_MISALIGNED = 6,
    AG32_EXCEPTION_STORE_ACCESS = 7,
    AG32_EXCEPTION_ECALL_U = 8,
    AG32_EXCEPTION_ECALL_M = 11,
    AG32_EXCEPTION_INSTRUCTION_PAGE = 12,
    AG32_EXCEPTION_LOAD_PAGE = 13,
    AG32_EXCEPTION_STORE_PAGE = 15,
};

enum ag32_irq {
    AG32_IRQ_FLASH = 1,
    AG32_IRQ_RTC = 2,
    AG32_IRQ_FCB0 = 3,
    AG32_IRQ_WATCHDOG0 = 4,
    AG32_IRQ_SPI0 = 5,
    AG32_IRQ_SPI1 = 6,
    AG32_IRQ_GPIO0 = 7,
    AG32_IRQ_GPIO1 = 8,
    AG32_IRQ_GPIO2 = 9,
    AG32_IRQ_GPIO3 = 10,
    AG32_IRQ_GPIO4 = 11,
    AG32_IRQ_GPIO5 = 12,
    AG32_IRQ_GPIO6 = 13,
    AG32_IRQ_GPIO7 = 14,
    AG32_IRQ_GPIO8 = 15,
    AG32_IRQ_GPIO9 = 16,
    AG32_IRQ_TIMER0 = 17,
    AG32_IRQ_TIMER1 = 18,
    AG32_IRQ_GPTIMER0 = 19,
    AG32_IRQ_GPTIMER1 = 20,
    AG32_IRQ_GPTIMER2 = 21,
    AG32_IRQ_GPTIMER3 = 22,
    AG32_IRQ_GPTIMER4 = 23,
    AG32_IRQ_UART0 = 24,
    AG32_IRQ_UART1 = 25,
    AG32_IRQ_UART2 = 26,
    AG32_IRQ_UART3 = 27,
    AG32_IRQ_UART4 = 28,
    AG32_IRQ_CAN0 = 29,
    AG32_IRQ_I2C0 = 30,
    AG32_IRQ_I2C1 = 31,
    AG32_IRQ_DMAC0 = 32,
    AG32_IRQ_DMAC0_TC = 33,
    AG32_IRQ_DMAC0_ERROR = 34,
    AG32_IRQ_USB0 = 35,
    AG32_IRQ_MAC0 = 36,
    AG32_IRQ_EXT0 = 37,
    AG32_IRQ_EXT1 = 38,
    AG32_IRQ_EXT2 = 39,
    AG32_IRQ_EXT3 = 40,
    AG32_IRQ_EXT4 = 41,
    AG32_IRQ_EXT5 = 42,
    AG32_IRQ_EXT6 = 43,
    AG32_IRQ_EXT7 = 44,
};

static inline uint32_t ag32_csr_mcause(void) {
    uint32_t value;
    __asm__ volatile("csrr %0, mcause" : "=r"(value));
    return value;
}

static inline void ag32_mepc_write(uint32_t value) {
    __asm__ volatile("csrw mepc, %0" :: "r"(value));
}

static inline void ag32_enable_machine_interrupts(void) {
    __asm__ volatile("csrs mstatus, %0" :: "r"(AG32_MSTATUS_MIE));
}

static inline void ag32_disable_machine_interrupts(void) {
    __asm__ volatile("csrc mstatus, %0" :: "r"(AG32_MSTATUS_MIE));
}

static inline void ag32_enable_machine_interrupt_mask(uint32_t mask) {
    __asm__ volatile("csrs mie, %0" :: "r"(mask));
}

static inline void ag32_disable_machine_interrupt_mask(uint32_t mask) {
    __asm__ volatile("csrc mie, %0" :: "r"(mask));
}

static inline void ag32_enable_machine_software_interrupt(void) {
    ag32_enable_machine_interrupt_mask(AG32_MIE_MSIE);
}

static inline void ag32_enable_machine_timer_interrupt(void) {
    ag32_enable_machine_interrupt_mask(AG32_MIE_MTIE);
}

static inline void ag32_enable_machine_external_interrupt(void) {
    ag32_enable_machine_interrupt_mask(AG32_MIE_MEIE);
}

static inline void ag32_clint_software_interrupt_set(void) {
    AG32_CLINT_MSIP = 1u;
}

static inline void ag32_clint_software_interrupt_clear(void) {
    AG32_CLINT_MSIP = 0u;
}

/* RV32-safe sequence: prevent a transient early match while replacing 64 bits. */
static inline void ag32_mtimecmp_set(uint64_t value) {
    AG32_CLINT_MTIMECMP_HI = UINT32_MAX;
    AG32_CLINT_MTIMECMP_LO = (uint32_t)value;
    AG32_CLINT_MTIMECMP_HI = (uint32_t)(value >> 32);
}

static inline int ag32_plic_valid_irq(uint32_t irq) {
    return irq >= 1u && irq <= AG32_PLIC_SOURCE_COUNT;
}

static inline int ag32_plic_enable(uint32_t irq, uint32_t priority) {
    if (!ag32_plic_valid_irq(irq) || priority > 15u)
        return -1;
    AG32_PLIC_PRIORITY(irq) = priority;
    AG32_PLIC_ENABLE_WORD(irq >> 5) |= 1u << (irq & 31u);
    return 0;
}

static inline int ag32_plic_disable(uint32_t irq) {
    if (!ag32_plic_valid_irq(irq))
        return -1;
    AG32_PLIC_ENABLE_WORD(irq >> 5) &= ~(1u << (irq & 31u));
    return 0;
}

static inline int ag32_plic_pending(uint32_t irq) {
    if (!ag32_plic_valid_irq(irq))
        return 0;
    return (AG32_PLIC_PENDING_WORD(irq >> 5) >> (irq & 31u)) & 1u;
}

static inline void ag32_plic_set_threshold(uint32_t threshold) {
    AG32_PLIC_THRESHOLD = threshold & 15u;
}

static inline uint32_t ag32_plic_claim(void) {
    return AG32_PLIC_CLAIM_COMPLETE;
}

static inline void ag32_plic_complete(uint32_t irq) {
    AG32_PLIC_CLAIM_COMPLETE = irq;
}

/*
 * Override this weak startup symbol. Peripheral handlers must clear their
 * source and complete a claimed PLIC IRQ before returning. Exception handlers
 * that recover must update mepc explicitly (for example, past a 4-byte ECALL).
 */
void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval);

#endif
