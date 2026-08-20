#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

int main(void) {
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);

    MAILBOX[0] = 0x55415258u; /* UARX */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[4] = 0x52454144u;
    MAILBOX[5] = 0u;
    while (MAILBOX[5] != 1u) { }

    uint32_t baud = MAILBOX[3];
    ag32_apb_enable(AG32_APB_GPIO(6));
    GPIO_AFSEL(6) |= 0x02u; /* GPIO6.1 -> UART0_UARTRXD */
    MAILBOX[6] = (uint32_t)ag32_uart_init(
        AG32_UART0, ag32_uart_ref_hz_measured(), baud);

    uint32_t received = 0u;
    uint32_t error = 0u;
    for (; received < 64u; ++received) {
        uint8_t value = 0u;
        int result = ag32_uart_getc(AG32_UART0, &value, 50000000u);
        if (result) {
            error = (uint32_t)result;
            break;
        }
        unsigned word = received >> 2;
        unsigned shift = (received & 3u) * 8u;
        if ((received & 3u) == 0u)
            MAILBOX[10u + word] = 0u;
        MAILBOX[10u + word] |= (uint32_t)value << shift;
    }
    MAILBOX[7] = received;
    MAILBOX[8] = error;
    MAILBOX[9] = AG32_UART0->FR;
    MAILBOX[26] = 0xc0ffee30u;
    for (;;) { }
}
