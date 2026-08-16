#include "ag32.h"

/* SRAM-only SPI0 active-slave receive witness for the exact L48 IO1 route. */
#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)
#ifndef RX_BYTES
#define RX_BYTES 4u
#endif

int main(void) {
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    ag32_apb_enable(AG32_APB_GPIO(0) | AG32_APB_GPIO(4));
    GPIO_AFSEL(0) |= 3u;
    GPIO_AFSEL(4) = (GPIO_AFSEL(4) & ~0x60u) | 0x60u;

    MAILBOX[0] = 0x53504956u; /* SPIV */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[3] = (uint32_t)ag32_spi_init(AG32_SPI0, 256u);
    MAILBOX[4] = AG32_SPI0->CTRL;
    MAILBOX[5] = 0x52454144u;
    MAILBOX[6] = 0u; /* host command */
    MAILBOX[7] = 0u; /* status */
    MAILBOX[8] = 0u; /* normalized API value */
    MAILBOX[9] = 0u; /* raw PHASE_DATA[1] */
    MAILBOX[10] = 0u;

    while (MAILBOX[6] != 1u) { }
    uint32_t value = 0u;
    MAILBOX[7] = (uint32_t)ag32_spi_write_read(
        AG32_SPI0, 0xa5u, 1u, &value, RX_BYTES, 200000u);
    MAILBOX[8] = value;
    MAILBOX[9] = AG32_SPI0->PHASE_DATA[1];
    MAILBOX[10] = 0xc0ffee56u;
    MAILBOX[11] = RX_BYTES;
    for (;;) { }
}
