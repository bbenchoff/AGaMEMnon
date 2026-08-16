#ifndef AGAMEMNON_AG32_SPI_H
#define AGAMEMNON_AG32_SPI_H

/*
 * Open AG32 hard SPI master. A transfer is a list of phases; each phase shifts
 * 1..4 bytes (or a DMA-fed run) as TX, dummy-TX, RX, or poll.
 *
 * ============================================================================
 * SUB-WORD TX PAYLOADS ARE LEFT-JUSTIFIED - MEASURED, NOT INFERRED
 * ============================================================================
 * On 2026-08-14, with a fabric routing SPI0 SCK/MOSI/CSN to wired L48 pads and
 * a logic analyzer on the pins:
 *
 *   - ag32_spi_write(SPI0, 0x55, 1, ...) - and 0x41, 0xFF, i.e. the byte in the
 *     natural LOW lane - clocked SCK and CSN normally but MOSI stayed driven
 *     LOW (read 0 under both an external pulldown and an external pullup, so
 *     actively driven, not floating) and every decoded word was 0x00.
 *   - ag32_spi_write(SPI0, 0xFF000000, 1, ...) - only the TOP byte non-zero -
 *     toggled MOSI at 262 Hz, matching SCK/CSN.
 *   - ag32_spi_write(SPI0, 0x11223344, 4, ...) toggled MOSI at 374 Hz and the
 *     SCK edge rate rose 262 -> 937 Hz, consistent with 4x the clocks.
 *
 * So for an N-byte TX phase this controller shifts the HIGH-order bytes of
 * PHASE_DATA out first, and a payload passed in the low lane never reaches the
 * wire. The drivers below therefore left-justify sub-word TX payloads
 * (`data << (8 * (4 - bytes))`) so the public API does the obvious thing:
 * passing 0x55 with bytes=1 puts 0x55 on the wire, and multi-byte payloads go
 * out most-significant byte first. A 4-byte payload is unchanged.
 *
 * THE FIX ITSELF IS SILICON-VERIFIED, not just applied: with this header,
 * `ag32_spi_write(AG32_SPI0, 0x55u, 1u, ...)` in a loop was captured on the
 * routed SPI0 pads and decoded to 233 words, every one of them 0x55
 * (histogram: {0x55: 233}). The same call before the change transmitted 0x00
 * and left MOSI driven low. Capture was an 8-channel PIO sample at 12 MHz,
 * decoded MSB-first with CS framing; SCK measured 1.30 MHz.
 *
 * Two deliberate non-claims:
 *
 *   1. CTRL bit 10 is left exactly as `ag32_spi_init()` programs it. The vendor
 *      register description names bit 10 an endianness select and its own flash
 *      driver, with the same bit set, packs command bytes in the LOW lane -
 *      which is the opposite of what this board measured. The bit's real
 *      meaning is therefore NOT established, so it is not flipped on the
 *      strength of a name. The left-justification above compensates for the
 *      behavior actually observed in the configuration this SDK ships; if that
 *      bit is ever reconfigured, re-measure before trusting either.
 *   2. Sub-word RX lane placement is now measured on L48 silicon.  With the
 *      bidirectional IO1 pad routed and held high, 1..4-byte RX phases returned
 *      raw words A50000FF, A500FFFF, A5FFFFFF, and FFFFFFFF.  The valid RX bytes
 *      therefore occupy the LOW-order end; upper bits retain unrelated shift
 *      state for widths below four.  The public read API masks those stale bits
 *      and returns a right-justified value.  This establishes lane placement,
 *      not arbitrary data reception: the routed pad remained pullup-dominated
 *      under both weak external pulls, so duplex values still need an actively
 *      driven, contention-safe slave.
 *
 * The 4-byte capture decoded as 20 07 0A 01 28 00 rather than 11 22 33 44; the
 * host decoder's CPOL/CPHA was almost certainly wrong, so that byte sequence is
 * NOT evidence about lane order. The load-bearing evidence is the
 * toggling-versus-stuck-at-zero comparison above.
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
 * and the repaired initialization sequence on SPI0.  It does not establish an
 * absolute SPI reference frequency: MTIME's absolute rate and the short fixed
 * software overhead still need an independent simultaneous measurement.
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
/*
 * Bit 10 is the vendor's byte-order select. The name is retained for source
 * compatibility only: this board transmits the HIGH-order byte of a sub-word
 * payload first with this bit set, which contradicts the "little" reading. Treat
 * the bit as uncharacterized and see the header comment before changing it.
 */
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

/*
 * Place a 1..4 byte TX payload where the controller actually shifts from: the
 * high-order end of the phase-data word (see the measurement at the top of this
 * header). Callers pass the payload right-justified, as any sane API expects.
 */
static inline uint32_t ag32_spi_tx_align(uint32_t data, unsigned bytes) {
    if (bytes >= 4u)
        return data;
    return data << (8u * (4u - bytes));
}

/* Keep only the low-order bytes populated by an RX phase.  Silicon leaves
 * unrelated shift-register state above them for sub-word reads. */
static inline uint32_t ag32_spi_rx_value(uint32_t raw, unsigned bytes) {
    if (bytes >= 4u)
        return raw;
    return raw & ((1u << (8u * bytes)) - 1u);
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
 * like ag32_spi_write(). `*rx` is right-justified and masked to the requested
 * width; raw upper bits are stale controller state on sub-word RX phases.
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
