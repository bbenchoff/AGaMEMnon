#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

static const uint8_t pattern[4] = {0xffu, 0x55u, 0x41u, 0x00u};

int main(void) {
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    MAILBOX[0] = 0x55455252u; /* UERR */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[5] = 0u;
    while (MAILBOX[5] != 1u) { }
    ag32_apb_enable(AG32_APB_GPIO(6));
    GPIO_AFSEL(6) |= 0x02u;
    MAILBOX[6] = (uint32_t)ag32_uart_init(
        AG32_UART0, ag32_uart_ref_hz_measured(), MAILBOX[3]);
    AG32_UART0->CR = 0u;
    AG32_UART0->LCR_H = AG32_UART_LCR_WLEN_8 | AG32_UART_LCR_FEN |
                        AG32_UART_LCR_PEN | AG32_UART_LCR_EPS;
    AG32_UART0->ICR = 0x7ffu;
    AG32_UART0->RSR_ECR = 0u;
    AG32_UART0->CR = AG32_UART_CR_RXE | AG32_UART_CR_UARTEN;
    MAILBOX[4] = 0x52454144u;

    uint32_t received = 0u, timeout_error = 0u, mismatch = 0u;
    uint32_t parity = 0u, framing = 0u, brk = 0u, overrun = 0u;
    for (; received < 64u; ++received) {
        uint32_t timeout = 50000000u;
        while (AG32_UART0->FR & AG32_UART_FR_RXFE) {
            if (!timeout--) { timeout_error = 1u; break; }
        }
        if (timeout_error) break;
        uint32_t data = AG32_UART0->DR;
        if ((uint8_t)data != pattern[received & 3u]) ++mismatch;
        if (data & (1u << 9)) ++parity;
        if (data & (1u << 8)) ++framing;
        if (data & (1u << 10)) ++brk;
        if (data & (1u << 11)) ++overrun;
        AG32_UART0->RSR_ECR = 0u;
    }
    MAILBOX[7] = received;
    MAILBOX[8] = timeout_error;
    MAILBOX[9] = mismatch;
    MAILBOX[10] = parity;
    MAILBOX[11] = framing;
    MAILBOX[12] = brk;
    MAILBOX[13] = overrun;
    MAILBOX[14] = AG32_UART0->RSR_ECR;
    MAILBOX[15] = 0xc0ffee34u;
    for (;;) { }
}
