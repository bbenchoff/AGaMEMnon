#include "ag32.h"

/*
 * SRAM-only UART0 baud witness. The exact peripheral-route fabric places UART0
 * TX on L48 PIN_10 / Pico GP4. Build this source with -DUART_BAUD=<rate>; the
 * independent Pico PIO UART receiver must decode the repeating four-byte
 * pattern at that same requested rate.
 */

#ifndef UART_BAUD
#define UART_BAUD 9600u
#endif

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

static const uint8_t pattern[] = {0x55u, 0x41u, 0x00u, 0xffu};

int main(void) {
    uint32_t fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    ag32_apb_enable(AG32_APB_GPIO(7));
    GPIO_AFSEL(7) |= 1u << 6; /* UART0 TXD */

    uint32_t reference = ag32_uart_ref_hz_measured();
    int init = ag32_uart_init(AG32_UART0, reference, UART_BAUD);

    MAILBOX[0] = 0x55424155u; /* UBAU */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[3] = UART_BAUD;
    MAILBOX[4] = reference;
    MAILBOX[5] = (uint32_t)init;
    MAILBOX[6] = AG32_UART0->IBRD;
    MAILBOX[7] = AG32_UART0->FBRD;
    MAILBOX[8] = AG32_SYSCTL_CLK_CNTL;
    MAILBOX[9] = AG32_SYSCTL_PBUS_DIVIDER;
    MAILBOX[10] = AG32_SYSCTL_MTIME_PSC;
    MAILBOX[11] = 0xc0ffee5bu;

    unsigned next = 0;
    for (;;) {
        if (!(AG32_UART0->FR & AG32_UART_FR_TXFF))
            AG32_UART0->DR = pattern[next++ & 3u];
    }
}
