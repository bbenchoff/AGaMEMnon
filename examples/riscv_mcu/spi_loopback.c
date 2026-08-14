#include "ag32.h"

/*
 * SPI0 master single-byte shift + optional external loopback readback.
 *
 * The AG32 hard SPI master is phase-based: a transfer is a list of phases, each
 * shifting 1..4 bytes as TX/RX. This demo brings SPI0 up, shifts one known byte
 * out of a TX phase, and reports the transfer status plus the shifted data
 * register. It then runs a TX-then-RX transfer (the hardware requires RX last)
 * and reports the received word.
 *
 * "The byte cycled" is meaningful on the MOSI line unconditionally, but the RX
 * word only equals the TX byte when MISO is fed back -- either by an external
 * MOSI->MISO jumper or by a real SPI device. Reaching the SPI0 pads at all
 * requires a fabric route of the SPI0 alternate-function pins, so both the
 * pin waveform and the RX value are pad/fabric dependent (marked below). The
 * transfer wait is bounded, so an unrouted SPI0 reports a timeout rather than
 * hanging.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 10`):
 *   [0] 0x53504930  "SPI0" tag
 *   [1] init status         (0 = master reset+configured, <0 = bad divider)
 *   [2] write status        (0 = TX phase completed, -2 timeout, -3 error)
 *   [3] byte shifted out    (0x9f)
 *   [4] TX phase-data readback
 *   [5] write_read status   (0 = TX+RX completed)
 *   [6] RX word             (== byte with an external MOSI->MISO loop) [PAD]
 *   [7] CTRL readback       (bit1 DONE, bit2 ERROR)
 *   [8] SYSCTL DEVICE_ID
 *   [9] 0xc0ffee5b  done sentinel
 */

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

#define SPI_DIVIDER  8u
#define SPI_BYTE     0x9fu       /* e.g. a JEDEC READ-ID opcode        */
#define SPI_TIMEOUT  200000u

int main(void) {
    mailbox[0] = 0x53504930u;                 /* "SPI0" */

    int init = ag32_spi_init(AG32_SPI0, SPI_DIVIDER);
    mailbox[1] = (uint32_t)init;

    int wr = ag32_spi_write(AG32_SPI0, SPI_BYTE, 1u, SPI_TIMEOUT);
    mailbox[2] = (uint32_t)wr;
    mailbox[3] = SPI_BYTE;
    mailbox[4] = AG32_SPI0->PHASE_DATA[0];

    uint32_t rx = 0;
    int wrr = ag32_spi_write_read(AG32_SPI0, SPI_BYTE, 1u, &rx, 1u, SPI_TIMEOUT);
    mailbox[5] = (uint32_t)wrr;
    mailbox[6] = rx;                           /* [PAD] needs external loop */
    mailbox[7] = AG32_SPI0->CTRL;
    mailbox[8] = SYSCTL_DEVID;
    mailbox[9] = 0xc0ffee5bu;

    for (;;) { }
}
