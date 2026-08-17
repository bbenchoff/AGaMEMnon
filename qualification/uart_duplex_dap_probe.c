#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)
#define TRANSFER_BYTES 4096u

static const uint8_t tx_pattern[4] = {0xa5u, 0x5au, 0xc3u, 0x3cu};
static const uint8_t rx_pattern[4] = {0xffu, 0x55u, 0x41u, 0x00u};

int main(void) {
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);

    MAILBOX[0] = 0x55445058u; /* UDPX */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[4] = 0x41524d44u; /* ARMD */
    MAILBOX[5] = 0u;
    while (MAILBOX[5] != 1u) { }

    ag32_apb_enable(AG32_APB_GPIO(6));
    ag32_apb_enable(AG32_APB_GPIO(7));
    GPIO_AFSEL(6) |= 0x02u;
    GPIO_AFSEL(7) |= 0x40u;
    MAILBOX[6] = (uint32_t)ag32_uart_init(
        AG32_UART0, ag32_uart_ref_hz_measured(), MAILBOX[3]);
    MAILBOX[4] = 0x52454144u; /* READ */

    uint8_t value = 0u;
    int result = ag32_uart_getc(AG32_UART0, &value, 50000000u);
    MAILBOX[10] = value;
    if (result || value != 0x7eu) {
        MAILBOX[8] = (uint32_t)(result ? result : -3);
        MAILBOX[13] = 0xc0ffee31u;
        for (;;) { }
    }

    uint32_t received = 0u;
    uint32_t transmitted = 0u;
    uint32_t mismatch = 0u;
    uint32_t error = 0u;
    for (unsigned index = 0; index < TRANSFER_BYTES; ++index) {
        result = ag32_uart_putc(AG32_UART0, tx_pattern[index & 3u], 50000000u);
        if (result) {
            error = 0x100u | (uint32_t)(-result);
            break;
        }
        ++transmitted;
        result = ag32_uart_getc(AG32_UART0, &value, 50000000u);
        if (result) {
            error = 0x200u | (uint32_t)(-result);
            break;
        }
        if (value != rx_pattern[index & 3u])
            ++mismatch;
        ++received;
    }
    ag32_uart_flush(AG32_UART0);
    MAILBOX[7] = received;
    MAILBOX[8] = error;
    MAILBOX[9] = mismatch;
    MAILBOX[11] = AG32_UART0->FR;
    MAILBOX[12] = transmitted;
    MAILBOX[13] = 0xc0ffee32u;
    for (;;) { }
}
