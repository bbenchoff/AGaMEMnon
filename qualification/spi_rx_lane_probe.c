#include "ag32.h"

/*
 * SRAM-only SPI0 receive-lane witness for the exact L48 peripheral route.
 *
 * SPI0_SO_IO1 is routed to PIN_17.  The external Pico remains an input and
 * applies only weak pull-down/pull-up stimulus; it never drives against the
 * bidirectional pad.  A host writes mailbox word 6 with command 1 or 2 after
 * selecting the corresponding pull.  Each command runs receive widths 1..4.
 *
 * Mailbox at 0x20001000, read as 32 words:
 *   [0..7]       tag, DEVICE_ID, FCB status, init status, CTRL, ready,
 *                host command, completed command
 *   [8+12*i..]   four (status, raw PHASE_DATA) pairs, CTRL, AFSEL0, AFSEL4,
 *                sentinel, for stimulus i
 */

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

static void run_probe(unsigned slot) {
    uint32_t base = 8u + slot * 12u;
    for (unsigned bytes = 1; bytes <= 4; ++bytes) {
        uint32_t raw = 0xdeadbeefu;
        int status = ag32_spi_write_read(AG32_SPI0, 0xa5u, 1u, &raw,
                                         bytes, 200000u);
        MAILBOX[base + (bytes - 1u) * 2u] = (uint32_t)status;
        /* Read the register directly: the public API intentionally masks it. */
        MAILBOX[base + (bytes - 1u) * 2u + 1u] = AG32_SPI0->PHASE_DATA[1];
    }
    MAILBOX[base + 8u] = AG32_SPI0->CTRL;
    MAILBOX[base + 9u] = GPIO_AFSEL(0);
    MAILBOX[base + 10u] = GPIO_AFSEL(4);
    MAILBOX[base + 11u] = 0xc0ffee50u + slot;
}

int main(void) {
    /* A guarded second-load path also permits the canonical 76-byte loader to
     * configure and verify FCB before this larger witness starts. */
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    ag32_apb_enable(AG32_APB_GPIO(0) | AG32_APB_GPIO(4));
    GPIO_AFSEL(0) |= 3u; /* SPI0 MOSI + MISO */
    GPIO_AFSEL(4) = (GPIO_AFSEL(4) & ~0x60u) | 0x60u; /* SCK + CSN */

    MAILBOX[0] = 0x53504952u; /* SPIR */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[3] = (uint32_t)ag32_spi_init(AG32_SPI0, 256u);
    MAILBOX[4] = AG32_SPI0->CTRL;
    MAILBOX[5] = 0x52454144u; /* READ: ready for a host command */
    MAILBOX[6] = 0u;
    MAILBOX[7] = 0u;

    for (;;) {
        uint32_t command = MAILBOX[6];
        if (command >= 1u && command <= 2u && command != MAILBOX[7]) {
            run_probe(command - 1u);
            MAILBOX[7] = command;
        }
    }
}
