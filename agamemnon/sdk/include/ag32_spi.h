#ifndef AGAMEMNON_AG32_SPI_H
#define AGAMEMNON_AG32_SPI_H

/*
 * Open AG32 hard SPI master. A transfer is a list of phases; each phase shifts
 * 1..4 bytes (or a DMA-fed run) as TX, dummy-TX, RX, or poll.
 *
 * ============================================================================
 * TX PAYLOADS ARE BYTE-REVERSED INTO THE LOW LANES - MEASURED, NOT INFERRED
 * ============================================================================
 * A synchronized 8-channel capture on 2026-08-24 measured SPI0 SCK, MOSI, and
 * CSN together for 32,768 samples.  The controller shifted PHASE_DATA's low
 * byte first.  The old helper left-justified sub-word values; its exact wire
 * results were therefore:
 *
 *   call value/width       old PHASE_DATA       observed wire bytes
 *   0x000000a5 / 1        0xa5000000           00
 *   0x00001234 / 2        0x12340000           00 00
 *   0x00c35a7e / 3        0xc35a7e00           00 7e 5a
 *   0x11223344 / 4        0x11223344           44 33 22 11
 *
 * The public API accepts a right-justified integer and promises natural,
 * most-significant-byte-first wire order.  The helper below reverses only the
 * requested bytes into PHASE_DATA's low lanes: a request for 0x1234/2 writes
 * 0x00003412, so the low-byte-first controller emits 12 34.
 *
 * That capture also establishes the shipped configuration's electrical mode:
 * SCK is idle-high, MOSI changes on falling edges, and the stable value is
 * sampled on rising edges (CPOL=1, CPHA=1).  This statement is deliberately
 * scoped to the configuration programmed by ag32_spi_init().
 *
 * The earlier 2026-08-14 top-lane conclusion used a decoder whose clock mode
 * was not locked and is superseded by the synchronized, CS-framed capture.
 *
 * CTRL bit 10 is now directly characterized rather than trusted from its name.
 * At divider 32, a four-byte phase with raw PHASE_DATA=0x11223344 emits
 * 44 33 22 11 when bit 10 is set and 11 22 33 44 when it is clear. A separate
 * control-first ensemble passed both states across four vendor images for each
 * of the ordinary-Verilog and explicit-IOB forms plus both open images in 3/3.
 * The public helpers below deliberately keep the bit set and convert natural
 * right-justified caller values into that measured low-byte-first register
 * convention. Code that clears the bit is using direct register semantics and
 * must supply its own payload convention.
 *
 * One deliberate non-claim remains. RX lane placement and byte order are
 * measured on L48 silicon.  An RP2350
 *      PIO slave sent prefixes of the on-wire sequence 12 34 56 78 after the TX
 *      command.  Receive widths 1..4 returned raw PHASE_DATA words 00000012,
 *      00003412, 00563412, and 78563412: valid bytes occupy the LOW-order end,
 *      in reverse register order, while upper bits retain unrelated shift state
 *      for widths below four.  The public read API reverses only the requested
 *      low bytes and returns natural wire order (12, 1234, 123456, 12345678).
 *      The earlier sampled-high control returned A50000FF, A500FFFF,
 *      A5FFFFFF, and FFFFFFFF and independently established the same lanes.
 *
 * The lane/order statement above comes from the vendor-routed SPI0 reference.
 * The corrected L48 typed SPI0/SPI1 MISO paths are now admitted: both source
 * forms pass three 32-transaction runs of mode 3, divider 256, command A5 and
 * four-byte response 12345678. Fresh ordinary builds reproduce those images.
 * Known stuck-high images remain rejected (VP-AGM-008). Other receive lengths,
 * payloads, rates and modes need further qualification; see
 * docs/SPI_RECEIVE_QUALIFICATION.md for the exact evidence boundary.
 *
 * ============================================================================
 * THE DIVIDER IS SILICON-QUALIFIED; DO NOT ASSERT CTRL.SOFT_RESET FIRST
 * ============================================================================
 * An earlier 2026-08-14 analyzer sweep reported the same SCK at divisors 4,
 * 20, and 200.  The divider field was not the fault.  The old open driver
 * wrote CTRL.SOFT_RESET immediately before CTRL.DIV; on silicon that sequence
 * left CTRL at the reset value 0x00008202 and every requested divisor was lost.
 *
 * The repaired sequence uses the documented APB reset pulse and then writes
 * CTRL.DIV directly.  A 2026-08-16 SRAM-only timing sweep measured 64 one-byte
 * transfers at all documented divisors against MTIME.  All 64 transfers passed
 * at every point, CTRL read back the requested field, and elapsed ticks rose
 * monotonically:
 *
 *   divisor:        2      4      8      16      32      64       128      256
 *   MTIME ticks: 6484   7774  10813   16046   26399   46527     87327   169658
 *
 * Runs two and three were tick-identical (the divisor-2 point varied by only 15
 * ticks in run one).  This qualifies the power-of-two 2..256 divider behavior
 * and the repaired initialization sequence on SPI0.
 *
 * A later synchronized 20-Msample/s external capture removed the earlier
 * absolute-frequency non-claim.  The apparatus was fixed first with three
 * captures per divider from an already-qualified vendor image.  A separate
 * control-first parity session then passed all 112 divider/image points on the
 * first captures: four vendor images for each of the ordinary-Verilog and
 * explicit-IOB forms, plus both open images in 3/3.  Analyzer-referenced median
 * SCK ranged from about 7.368 MHz at divider 2 to 56.5--56.7 kHz at divider 256;
 * divider 32 measured about 451.6--454.5 kHz.  Every point transmitted exact
 * one-byte A5 windows and read back the requested CTRL encoding with zero
 * transfer errors.  This qualifies those eight divider points under the exact
 * inherited clock and L48 SPI0 TX corridor.  It is not a PVT, oscillator-
 * tolerance, maximum-frequency, SPI1, receive, dual/quad, or DMA qualification.
 */

#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t CTRL;          /* 0x00 global control (SPCR) */
    uint32_t reserved0[3];           /* 0x04..0x0c */
    volatile uint32_t PHASE_CTRL[8]; /* 0x10..0x2c */
    volatile uint32_t PHASE_DATA[8]; /* 0x30..0x4c */
} ag32_spi_t;

#define AG32_SPI0 ((ag32_spi_t *)(uintptr_t)AG32_SPI0_BASE)
#define AG32_SPI1 ((ag32_spi_t *)(uintptr_t)AG32_SPI1_BASE)

#define AG32_SPI_CTRL_START      (1u << 0)
#define AG32_SPI_CTRL_DONE       (1u << 1)
#define AG32_SPI_CTRL_ERROR      (1u << 2)
#define AG32_SPI_CTRL_PHASES(n)  (((uint32_t)(n) - 1u) << 4)
#define AG32_SPI_CTRL_DMA        (1u << 8)
#define AG32_SPI_CTRL_WP         (1u << 9)
/* Bit 10 is a measured TX raw-register byte-order select. Set shifts the low
 * register byte first; clear shifts the high register byte first for a four-byte
 * phase. Public helpers keep it set and perform the natural-order conversion. */
#define AG32_SPI_CTRL_BIG        0u
#define AG32_SPI_CTRL_LITTLE     (1u << 10)
#define AG32_SPI_CTRL_ENDIAN     AG32_SPI_CTRL_LITTLE
/*
 * SCK divider field. The silicon-qualified values are the documented powers of
 * two 2..256, with an encoded zero meaning 256. See the divider sweep above.
 */
#define AG32_SPI_CTRL_DIV(n)     (((uint32_t)(n) & 0xffu) << 12)
#define AG32_SPI_CTRL_IRQ        (1u << 20)
#define AG32_SPI_CTRL_RESET      (1u << 31)

#define AG32_SPI_PHASE_TX        (0u << 4)
#define AG32_SPI_PHASE_DUMMY     (1u << 4)
#define AG32_SPI_PHASE_RX        (2u << 4)
#define AG32_SPI_PHASE_POLL      (3u << 4)
#define AG32_SPI_PHASE_BYTES(n)  (((uint32_t)(n) & 0xfffu) << 8)
#define AG32_SPI_PHASE_SINGLE    (0u << 20)
#define AG32_SPI_PHASE_DUAL      (1u << 20)
#define AG32_SPI_PHASE_QUAD      (2u << 20)

static inline unsigned ag32_spi_index(const ag32_spi_t *spi) {
    return (unsigned)(((uintptr_t)spi - AG32_SPI0_BASE) / 0x1000u);
}

static inline int ag32_spi_init(ag32_spi_t *spi, unsigned clock_divider) {
    unsigned index = ag32_spi_index(spi);
    if (index >= AG32_SPI_COUNT || clock_divider < 2u ||
        clock_divider > 256u ||
        (clock_divider & (clock_divider - 1u)))
        return -1;
    ag32_apb_enable(index ? AG32_APB_SPI1 : AG32_APB_SPI0);
    ag32_apb_reset(index ? AG32_APB_SPI1 : AG32_APB_SPI0);
    /* Do not write CTRL.SOFT_RESET here.  Silicon leaves CTRL at 0x00008202
     * after that write and ignores the immediately following divider value. */
    spi->CTRL = AG32_SPI_CTRL_LITTLE |
                AG32_SPI_CTRL_DIV(clock_divider == 256u ? 0u : clock_divider);
    return 0;
}

/* Reverse the requested right-justified bytes into the low lanes from which
 * silicon shifts, preserving a natural MSB-first public wire order. */
static inline uint32_t ag32_spi_tx_align(uint32_t data, unsigned bytes) {
    uint32_t value = 0u;
    for (unsigned i = 0; i < bytes; ++i) {
        value = (value << 8) | (data & 0xffu);
        data >>= 8;
    }
    return value;
}

/* Normalize the low-order, byte-reversed RX register lanes into natural wire
 * order. Silicon leaves unrelated shift-register state above sub-word reads. */
static inline uint32_t ag32_spi_rx_value(uint32_t raw, unsigned bytes) {
    uint32_t value = 0u;
    for (unsigned i = 0; i < bytes; ++i) {
        value = (value << 8) | (raw & 0xffu);
        raw >>= 8;
    }
    return value;
}

/* One phase, one to four bytes, single-wire TX. `data` is right-justified: pass
 * 0x55 with bytes=1 to put 0x55 on MOSI. */
static inline int ag32_spi_write(ag32_spi_t *spi, uint32_t data,
                                 unsigned bytes, uint32_t timeout) {
    if (!bytes || bytes > 4u)
        return -1;
    spi->PHASE_CTRL[0] = AG32_SPI_PHASE_SINGLE | AG32_SPI_PHASE_TX |
                         AG32_SPI_PHASE_BYTES(bytes);
    spi->PHASE_DATA[0] = ag32_spi_tx_align(data, bytes);
    uint32_t config = spi->CTRL & (AG32_SPI_CTRL_DIV(0xffu) |
                                   AG32_SPI_CTRL_LITTLE | AG32_SPI_CTRL_WP);
    spi->CTRL = config | AG32_SPI_CTRL_PHASES(1) | AG32_SPI_CTRL_START;
    while (!(spi->CTRL & AG32_SPI_CTRL_DONE)) {
        if (!timeout--)
            return -2;
    }
    return (spi->CTRL & AG32_SPI_CTRL_ERROR) ? -3 : 0;
}

/*
 * TX command/address followed by RX; the hardware requires RX to be last and not
 * first. `tx` is right-justified and left-justified into the phase word exactly
 * like ag32_spi_write(). `*rx` is right-justified in natural wire byte order;
 * raw upper bits are stale controller state on sub-word RX phases.
 */
static inline int ag32_spi_write_read(ag32_spi_t *spi, uint32_t tx,
                                      unsigned tx_bytes, uint32_t *rx,
                                      unsigned rx_bytes, uint32_t timeout) {
    if (!tx_bytes || tx_bytes > 4u || !rx_bytes || rx_bytes > 4u)
        return -1;
    spi->PHASE_CTRL[0] = AG32_SPI_PHASE_SINGLE | AG32_SPI_PHASE_TX |
                         AG32_SPI_PHASE_BYTES(tx_bytes);
    spi->PHASE_CTRL[1] = AG32_SPI_PHASE_SINGLE | AG32_SPI_PHASE_RX |
                         AG32_SPI_PHASE_BYTES(rx_bytes);
    spi->PHASE_DATA[0] = ag32_spi_tx_align(tx, tx_bytes);
    uint32_t config = spi->CTRL & (AG32_SPI_CTRL_DIV(0xffu) |
                                   AG32_SPI_CTRL_LITTLE | AG32_SPI_CTRL_WP);
    spi->CTRL = config | AG32_SPI_CTRL_PHASES(2) | AG32_SPI_CTRL_START;
    while (!(spi->CTRL & AG32_SPI_CTRL_DONE)) {
        if (!timeout--)
            return -2;
    }
    if (spi->CTRL & AG32_SPI_CTRL_ERROR)
        return -3;
    *rx = ag32_spi_rx_value(spi->PHASE_DATA[1], rx_bytes);
    return 0;
}

#endif
