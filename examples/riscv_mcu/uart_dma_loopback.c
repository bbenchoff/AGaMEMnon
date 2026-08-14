#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)

/*
 * Safe SRAM diagnostic: DMA stays in SRAM and UART0 uses internal loopback.
 *
 * The baud clock comes from ag32_uart_ref_hz_measured(), the MEASURED UART0
 * reference clock (~14.47 MHz, back-solved from the programmed divisors against
 * a logic-analyzer bit time on this board). Nothing in the SDK configures the
 * clock tree, and the tree is not uniform: SPI0 measured ~258 MHz in the same
 * configuration, so there is no single "peripheral clock" to assume. Passing
 * ag32_pbus_hz(248000000) here previously produced ~560 baud for a requested
 * 9600 -- a ~17x error. Words 4..7 publish the clock used and the three clock
 * registers so the domain can be re-derived from a run instead of trusted.
 *
 * Mailbox at 0x20001000:
 *   [0] 0x48414c30 "HAL0" tag
 *   [1] DMA start<<24 | DMA wait<<16 | mismatch
 *   [2] UART status<<16 | received byte
 *   [3] SYSCTL DEVICE_ID
 *   [4] UART reference clock used for the baud divisor, in Hz
 *   [5] CLK_CNTL readback (bits[1:0] source, bit4 HSE ready, bit6 PLL ready)
 *   [6] PBUS_DIVIDER readback
 *   [7] MTIME_PSC readback
 */
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

    uint32_t uart_clock = ag32_uart_ref_hz_measured();
    int uart_status = ag32_uart_init(AG32_UART0, uart_clock, 115200u);
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
    MAILBOX[4] = uart_clock;
    MAILBOX[5] = AG32_SYSCTL_CLK_CNTL;
    MAILBOX[6] = AG32_SYSCTL_PBUS_DIVIDER;
    MAILBOX[7] = AG32_SYSCTL_MTIME_PSC;
    for (;;) { }
}
