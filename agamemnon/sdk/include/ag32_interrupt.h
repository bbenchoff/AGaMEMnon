#ifndef AGAMEMNON_AG32_INTERRUPT_H
#define AGAMEMNON_AG32_INTERRUPT_H

#include <stdint.h>

#define AG32_PLIC_BASE 0x0C000000u
#define AG32_PLIC_PRIORITY(irq) (*(volatile uint32_t *)(AG32_PLIC_BASE + 4u * (irq)))
#define AG32_PLIC_ENABLE0 (*(volatile uint32_t *)(AG32_PLIC_BASE + 0x2000u))
#define AG32_PLIC_THRESHOLD (*(volatile uint32_t *)(AG32_PLIC_BASE + 0x200000u))
#define AG32_PLIC_CLAIM (*(volatile uint32_t *)(AG32_PLIC_BASE + 0x200004u))

enum ag32_irq {
    AG32_IRQ_FLASH=1, AG32_IRQ_RTC=2, AG32_IRQ_FCB0=3, AG32_IRQ_WATCHDOG0=4,
    AG32_IRQ_SPI0=5, AG32_IRQ_SPI1=6, AG32_IRQ_GPIO0=7, AG32_IRQ_GPIO1=8,
    AG32_IRQ_GPIO2=9, AG32_IRQ_GPIO3=10, AG32_IRQ_GPIO4=11,
    AG32_IRQ_TIMER0=17, AG32_IRQ_TIMER1=18,
    AG32_IRQ_GPTIMER0=19, AG32_IRQ_GPTIMER1=20, AG32_IRQ_GPTIMER2=21,
    AG32_IRQ_GPTIMER3=22, AG32_IRQ_GPTIMER4=23,
    AG32_IRQ_UART0=24, AG32_IRQ_UART1=25, AG32_IRQ_UART2=26,
    AG32_IRQ_UART3=27, AG32_IRQ_UART4=28, AG32_IRQ_CAN0=29,
    AG32_IRQ_I2C0=30, AG32_IRQ_I2C1=31, AG32_IRQ_DMAC=32,
    AG32_IRQ_USB0=35, AG32_IRQ_MAC0=36,
};

static inline void ag32_enable_machine_interrupts(void) {
    __asm__ volatile("csrs mstatus, %0" :: "r"(1u << 3));
}

static inline void ag32_enable_machine_external_interrupt(void) {
    __asm__ volatile("csrs mie, %0" :: "r"(1u << 11));
}

/* Override this weak startup symbol. Clear/complete the interrupt before return. */
void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval);

#endif
