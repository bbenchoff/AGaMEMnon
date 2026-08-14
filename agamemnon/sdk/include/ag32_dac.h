#ifndef AGAMEMNON_AG32_DAC_H
#define AGAMEMNON_AG32_DAC_H

/*
 * Open AG32 DAC (DAC0/1) driver, written from the published register map.
 * A 10-bit DAC with an optional output buffer and DMA-fed conversion. These
 * are analog hard blocks reached over the External-AHB (fabric) window, not
 * MCU-core MMIO. No vendor code is copied.
 *
 * Layout: CTRL 0x00, DATA 0x04. DMA sample rate is APB / (1 + SCLK_DIV).
 */

#include <stdint.h>

#include "ag32_device.h"

typedef struct {
    volatile uint32_t CTRL;   /* 0x00 enable / buffer / DMA / clock divider */
    volatile uint32_t DATA;   /* 0x04 10-bit output value                   */
} ag32_dac_t;

#define AG32_DAC0 ((ag32_dac_t *)(uintptr_t)AG32_DAC0_BASE)
#define AG32_DAC1 ((ag32_dac_t *)(uintptr_t)AG32_DAC1_BASE)

#define AG32_DAC_CTRL_EN       (1u << 0)
#define AG32_DAC_CTRL_BUFEN    (1u << 1)  /* output buffer enable        */
#define AG32_DAC_CTRL_DMAEN    (1u << 2)
#define AG32_DAC_CTRL_SCLK_DIV(d) (((uint32_t)(d) & 0xffffu) << 16)

#define AG32_DAC_MAX_VALUE     0x3ffu     /* 10-bit range                */

/* Enable the DAC with its output buffer (typical for driving a pin/load). */
static inline void ag32_dac_enable(ag32_dac_t *dac) {
    dac->CTRL = AG32_DAC_CTRL_EN | AG32_DAC_CTRL_BUFEN;
}

/* Enable the DAC without the output buffer (higher output impedance). */
static inline void ag32_dac_enable_unbuffered(ag32_dac_t *dac) {
    dac->CTRL = AG32_DAC_CTRL_EN;
}

static inline void ag32_dac_disable(ag32_dac_t *dac) {
    dac->CTRL = 0u;
}

/* Set the output code (clamped to the 10-bit range). */
static inline void ag32_dac_set(ag32_dac_t *dac, uint32_t value) {
    dac->DATA = value & AG32_DAC_MAX_VALUE;
}

/* Turn on DMA-fed conversion at the given clock divider, preserving the
 * enable/buffer bits already programmed. */
static inline void ag32_dac_enable_dma(ag32_dac_t *dac, uint32_t sclk_div) {
    uint32_t low = dac->CTRL & 0xffffu;
    dac->CTRL = low | AG32_DAC_CTRL_DMAEN | AG32_DAC_CTRL_SCLK_DIV(sclk_div);
}

static inline void ag32_dac_disable_dma(ag32_dac_t *dac) {
    dac->CTRL &= ~AG32_DAC_CTRL_DMAEN;
}

#endif /* AGAMEMNON_AG32_DAC_H */
