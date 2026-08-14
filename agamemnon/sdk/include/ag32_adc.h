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
 * driver-only. External channels 0..3 read full scale; cause unestablished.
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
 * {0,128,...,1023} and reading ADC0 channel 4 gave, on one representative run,
 * 0, 512, 1024, 1536, 2054, 2575, 3085, 3598, 4095.
 *
 * DO NOT TREAT THAT VECTOR AS A CONSTANT. It is a single run of a real analog
 * converter and the low bits vary between runs -- an independent run of the same
 * sweep recorded 0, 511, 1024, 1538, 2054, 2573, 3085, 3594, 4095. Anything that
 * asserts the exact codes will be flaky. What is actually qualified, and what a
 * test should check, are the run-invariant properties: the response is strictly
 * MONOTONIC in the DAC code, the slope is ~4.00x (a 12-bit result against a
 * 10-bit code), and it SATURATES at full scale.
 *
 * DAC1 -> channel 5 reproduces the same behaviour on ADC0, and DAC0 -> channel 4
 * reproduces it on ADC1 and ADC2. (The DAC1 -> channel 5 tap was exercised on
 * ADC0 only, not on every ADC instance.)
 */
#define AG32_ADC_CH_DAC0      AG32_ADC_CHANNEL(4u)
#define AG32_ADC_CH_DAC1      AG32_ADC_CHANNEL(5u)

/*
 * External analog channels 0..3 read FULL SCALE (0xfff) on the L48 part here.
 * That observation is solid; the CAUSE IS NOT ESTABLISHED, so do not repeat the
 * "those pads are not bonded on L48" explanation that used to sit here -- it is
 * contradicted by our own data. The datasheet-derived pin table places
 * ADC_IN0..IN3 on PIN_10..PIN_13, and those four pads are bonded AND
 * harness-confirmed working as ordinary digital IO (they are how UART0, I2C0 SDA
 * and SPI0 SCK/CSN were qualified). Meanwhile the lab record explicitly declines
 * to characterize analog bonding.
 *
 * So a full-scale read on channels 0..3 means only "no usable analog input was
 * presented". Candidate explanations, none confirmed: the analog input mux is not
 * enabled for those channels; the pad is held in digital mode by the fabric IO
 * ring and never switched to its analog function; the input is genuinely
 * unconnected on this board; or the channel needs a reference/bias that is not
 * configured. Treat channels 0..3 as UNPROVEN, not as known-absent.
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
