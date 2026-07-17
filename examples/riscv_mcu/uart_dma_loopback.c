#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)

/* Safe SRAM diagnostic: DMA stays in SRAM and UART0 uses internal loopback. */
int main(void) {
    static const uint32_t source[4] = {
        0x48414c30u, 0x11223344u, 0x55667788u, 0xa5a5a5a5u
    };
    static uint32_t destination[4];

    MAILBOX[0] = 0x48414c30u; /* "HAL0" */
    ag32_dma_init();
    int dma_start = ag32_dma_copy32(0, destination, source, 4);
    int dma_wait = dma_start ? dma_start : ag32_dma_wait(0, 1000000u);
    uint32_t mismatch = 0;
    for (unsigned i = 0; i < 4; ++i)
        mismatch |= destination[i] ^ source[i];

    uint32_t pbus = ag32_pbus_hz(248000000u);
    int uart_status = ag32_uart_init(AG32_UART0, pbus, 115200u);
    uint8_t received = 0;
    if (!uart_status) {
        AG32_UART0->CR |= AG32_UART_CR_LBE;
        uart_status = ag32_uart_putc(AG32_UART0, 0xa5u, 1000000u);
        if (!uart_status)
            uart_status = ag32_uart_getc(AG32_UART0, &received, 1000000u);
    }

    MAILBOX[1] = ((uint32_t)(dma_start & 0xff) << 24) |
                 ((uint32_t)(dma_wait & 0xff) << 16) |
                 (mismatch ? 1u : 0u);
    MAILBOX[2] = ((uint32_t)(uart_status & 0xffff) << 16) | received;
    MAILBOX[3] = SYSCTL_DEVID;
    for (;;) { }
}
