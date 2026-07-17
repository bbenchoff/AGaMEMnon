#ifndef AGAMEMNON_AG32_SPI_H
#define AGAMEMNON_AG32_SPI_H

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
#define AG32_SPI_CTRL_LITTLE     (1u << 10)
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
    if (index >= AG32_SPI_COUNT || clock_divider > 256u ||
        (clock_divider != 256u && (clock_divider & 1u)))
        return -1;
    ag32_apb_enable(index ? AG32_APB_SPI1 : AG32_APB_SPI0);
    ag32_apb_reset(index ? AG32_APB_SPI1 : AG32_APB_SPI0);
    spi->CTRL = AG32_SPI_CTRL_RESET;
    spi->CTRL = AG32_SPI_CTRL_LITTLE |
                AG32_SPI_CTRL_DIV(clock_divider == 256u ? 0u : clock_divider);
    return 0;
}

/* One phase, one to four bytes, single-wire TX. */
static inline int ag32_spi_write(ag32_spi_t *spi, uint32_t data,
                                 unsigned bytes, uint32_t timeout) {
    if (!bytes || bytes > 4u)
        return -1;
    spi->PHASE_CTRL[0] = AG32_SPI_PHASE_SINGLE | AG32_SPI_PHASE_TX |
                         AG32_SPI_PHASE_BYTES(bytes);
    spi->PHASE_DATA[0] = data;
    uint32_t config = spi->CTRL & (AG32_SPI_CTRL_DIV(0xffu) |
                                   AG32_SPI_CTRL_LITTLE | AG32_SPI_CTRL_WP);
    spi->CTRL = config | AG32_SPI_CTRL_PHASES(1) | AG32_SPI_CTRL_START;
    while (!(spi->CTRL & AG32_SPI_CTRL_DONE)) {
        if (!timeout--)
            return -2;
    }
    return (spi->CTRL & AG32_SPI_CTRL_ERROR) ? -3 : 0;
}

/* TX command/address followed by RX; the hardware requires RX to be last and not first. */
static inline int ag32_spi_write_read(ag32_spi_t *spi, uint32_t tx,
                                      unsigned tx_bytes, uint32_t *rx,
                                      unsigned rx_bytes, uint32_t timeout) {
    if (!tx_bytes || tx_bytes > 4u || !rx_bytes || rx_bytes > 4u)
        return -1;
    spi->PHASE_CTRL[0] = AG32_SPI_PHASE_SINGLE | AG32_SPI_PHASE_TX |
                         AG32_SPI_PHASE_BYTES(tx_bytes);
    spi->PHASE_CTRL[1] = AG32_SPI_PHASE_SINGLE | AG32_SPI_PHASE_RX |
                         AG32_SPI_PHASE_BYTES(rx_bytes);
    spi->PHASE_DATA[0] = tx;
    uint32_t config = spi->CTRL & (AG32_SPI_CTRL_DIV(0xffu) |
                                   AG32_SPI_CTRL_LITTLE | AG32_SPI_CTRL_WP);
    spi->CTRL = config | AG32_SPI_CTRL_PHASES(2) | AG32_SPI_CTRL_START;
    while (!(spi->CTRL & AG32_SPI_CTRL_DONE)) {
        if (!timeout--)
            return -2;
    }
    if (spi->CTRL & AG32_SPI_CTRL_ERROR)
        return -3;
    *rx = spi->PHASE_DATA[1];
    return 0;
}

#endif
