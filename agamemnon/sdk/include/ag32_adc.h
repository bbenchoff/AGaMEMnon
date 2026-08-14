#ifndef AGAMEMNON_AG32_ADC_H
#define AGAMEMNON_AG32_ADC_H

/*
 * Open AG32 ADC (ADC0/1/2) driver, written from the published register map.
 * A 12-bit SAR converter with a 16-entry channel sequencer and optional
 * continuous / DMA operation. These are analog hard blocks reached over the
 * External-AHB (fabric) window, not MCU-core MMIO. No vendor code is copied.
 *
 * Layout: CTRL 0x00, STAT 0x04, DATA 0x08, CHNL 0x3C (sequence length - 1),
 * SEQ[0..15] 0x40..0x7C (channel indices 1..17). Sample rate is
 * APB / (1 + SCLK_DIV) / 2 / 13. Reading DATA clears EOC, and writing CHNL or
 * any SEQ entry restarts the converter.
 *
 * Silicon status (L48, open flow, 2026-08-14): ADC0, ADC1, and ADC2 are all
 * QUALIFIED for single-channel one-shot conversion against the internal DAC
 * loopback taps below. DMA, continuous scan, and multi-entry sequences are
 * driver-only. External channels 0..3 are not bonded on L48.
 */

#include <stdint.h>

#include "ag32_device.h"

typedef struct {
    volatile uint32_t CTRL;         /* 0x00                               */
    volatile uint32_t STAT;         /* 0x04                               */
    volatile const uint32_t DATA;   /* 0x08 latest conversion result      */
    uint32_t reserved_0c[12];       /* 0x0c..0x38                         */
    volatile uint32_t CHNL;         /* 0x3c sequence length minus one     */
    volatile uint32_t SEQ[16];      /* 0x40..0x7c channel sequence        */
} ag32_adc_t;

#define AG32_ADC0 ((ag32_adc_t *)(uintptr_t)AG32_ADC0_BASE)
#define AG32_ADC1 ((ag32_adc_t *)(uintptr_t)AG32_ADC1_BASE)
#define AG32_ADC2 ((ag32_adc_t *)(uintptr_t)AG32_ADC2_BASE)

#define AG32_ADC_CTRL_START   (1u << 0)
#define AG32_ADC_CTRL_STOP    (1u << 1)
#define AG32_ADC_CTRL_CONT    (1u << 2)  /* continuous conversion       */
#define AG32_ADC_CTRL_DMAEN   (1u << 3)
#define AG32_ADC_CTRL_SCLK_DIV(d) (((uint32_t)(d) & 0xffffu) << 16)

#define AG32_ADC_STAT_EN      (1u << 0)
#define AG32_ADC_STAT_EOC     (1u << 1)  /* end of conversion           */

#define AG32_ADC_MAX_VALUE    0xfffu     /* 12-bit result               */
#define AG32_ADC_CHANNEL(n)   ((uint32_t)(n) + 1u) /* channel 0.. -> index */

/*
 * Internal DAC loopback taps. DAC0's output is wired on-die to ADC input
 * channel 4 and DAC1's to channel 5, on ALL THREE ADC instances. These need no
 * external analog wiring, which makes them the self-contained way to prove an
 * ADC actually converts: drive a DAC code and watch the ADC follow.
 *
 * Silicon-qualified (L48, open flow, 2026-08-14): sweeping DAC0 across
 * {0,128,...,1023} returned 0, 512, 1024, 1536, 2054, 2575, 3085, 3598, 4095 on
 * ADC0 channel 4 -- strictly monotonic and ~4.00x linear, exactly the 12-bit
 * result versus 10-bit code ratio, saturating at full scale. DAC1 -> channel 5
 * and both DAC0 -> ADC1/ADC2 channel 4 paths reproduce it.
 */
#define AG32_ADC_CH_DAC0      AG32_ADC_CHANNEL(4u)
#define AG32_ADC_CH_DAC1      AG32_ADC_CHANNEL(5u)

/*
 * External analog channels 0..3 exist in the register map but their pads are
 * NOT BONDED on the L48 package, so they read full scale (0xfff) on that part.
 * A full-scale reading there is an unbonded rail, not a measurement.
 */

/* Program a conversion sequence. length is 1..16; channels[] are ADC channel
 * indices as accepted by the sequencer (1..17). Returns -1 on bad length. */
static inline int ag32_adc_set_sequence(ag32_adc_t *adc, const uint32_t *channels,
                                        unsigned length) {
    if (length < 1u || length > 16u)
        return -1;
    for (unsigned i = 0; i < length; ++i)
        adc->SEQ[i] = channels[i];
    adc->CHNL = length - 1u;
    return 0;
}

/* Convenience: a single-channel sequence. */
static inline void ag32_adc_set_channel(ag32_adc_t *adc, uint32_t channel) {
    adc->SEQ[0] = channel;
    adc->CHNL = 0u;
}

static inline void ag32_adc_start(ag32_adc_t *adc, uint32_t sclk_div) {
    adc->CTRL = AG32_ADC_CTRL_START | AG32_ADC_CTRL_SCLK_DIV(sclk_div);
}

static inline void ag32_adc_start_continuous(ag32_adc_t *adc, uint32_t sclk_div) {
    adc->CTRL = AG32_ADC_CTRL_START | AG32_ADC_CTRL_CONT |
                AG32_ADC_CTRL_SCLK_DIV(sclk_div);
}

static inline void ag32_adc_start_dma(ag32_adc_t *adc, uint32_t sclk_div) {
    adc->CTRL = AG32_ADC_CTRL_START | AG32_ADC_CTRL_CONT | AG32_ADC_CTRL_DMAEN |
                AG32_ADC_CTRL_SCLK_DIV(sclk_div);
}

static inline void ag32_adc_stop(ag32_adc_t *adc) {
    adc->CTRL |= AG32_ADC_CTRL_STOP;
}

static inline int ag32_adc_wait_eoc(ag32_adc_t *adc, uint32_t timeout) {
    while (!(adc->STAT & AG32_ADC_STAT_EOC)) {
        if (!timeout--)
            return -1;
    }
    return 0;
}

static inline uint32_t ag32_adc_read(const ag32_adc_t *adc) {
    return adc->DATA & AG32_ADC_MAX_VALUE;
}

/* Single blocking conversion of one channel; returns the 12-bit result or a
 * negative timeout code. */
static inline int32_t ag32_adc_convert(ag32_adc_t *adc, uint32_t channel,
                                       uint32_t sclk_div, uint32_t timeout) {
    ag32_adc_set_channel(adc, channel);
    ag32_adc_start(adc, sclk_div);
    if (ag32_adc_wait_eoc(adc, timeout))
        return -1;
    return (int32_t)ag32_adc_read(adc);
}

#endif /* AGAMEMNON_AG32_ADC_H */
