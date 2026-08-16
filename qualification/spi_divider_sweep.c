#include "ag32.h"

/*
 * SRAM-only timing sweep for the hard SPI0 divider.
 *
 * The original external capture was close to its analyzer sample-rate limit.
 * This witness instead times 64 one-byte transfers against MTIME for each
 * documented power-of-two divider.  The matching peripheral-route fabric image
 * connects SCK/MOSI/CSN to L48 pads, but the load-bearing observation is the
 * internal transfer completion count, CTRL readback, and monotonic tick series.
 * No flash or clock-tree state is changed.
 *
 * Mailbox at 0x20001000, read as 39 words:
 *   [0..5]       tag, DEVICE_ID, FCB_STAT, CLK_CNTL, PBUS_DIVIDER, MTIME_PSC
 *   [6+4*i..]    requested divider, CTRL readback, completed count, MTIME ticks
 *   [38]         sentinel
 */

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

static const uint16_t dividers[] = {2u, 4u, 8u, 16u, 32u, 64u, 128u, 256u};

int main(void) {
    uint32_t fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    ag32_apb_enable(AG32_APB_GPIO(0) | AG32_APB_GPIO(4));
    GPIO_AFSEL(0) |= 1u;                             /* SPI0 MOSI */
    GPIO_AFSEL(4) = (GPIO_AFSEL(4) & ~0x60u) | 0x60u; /* SCK + CSN */

    MAILBOX[0] = 0x53444956u; /* SDIV */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[3] = AG32_SYSCTL_CLK_CNTL;
    MAILBOX[4] = AG32_SYSCTL_PBUS_DIVIDER;
    MAILBOX[5] = AG32_SYSCTL_MTIME_PSC;

    for (unsigned i = 0; i < sizeof(dividers) / sizeof(dividers[0]); ++i) {
        uint32_t base = 6u + 4u * i;
        uint32_t ok = 0;
        int init = ag32_spi_init(AG32_SPI0, dividers[i]);
        uint32_t configured = AG32_SPI0->CTRL;
        uint64_t start = ag32_mtime();
        if (init == 0) {
            for (unsigned transfer = 0; transfer < 64u; ++transfer)
                if (ag32_spi_write(AG32_SPI0, 0x55u, 1u, 200000u) == 0)
                    ++ok;
        }
        uint64_t elapsed = ag32_mtime() - start;
        MAILBOX[base + 0u] = dividers[i];
        MAILBOX[base + 1u] = configured;
        MAILBOX[base + 2u] = ok;
        MAILBOX[base + 3u] = (uint32_t)elapsed;
    }
    MAILBOX[38] = 0xc0ffee5bu;
    for (;;) { }
}
