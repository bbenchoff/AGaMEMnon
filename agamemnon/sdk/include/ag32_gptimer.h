#ifndef AGAMEMNON_AG32_GPTIMER_H
#define AGAMEMNON_AG32_GPTIMER_H

/*
 * Open AG32 advanced-timer (GPTIMER0..4) driver, written from the published
 * AG32 register map. These are STM32-TIM-class timers: a prescaler/auto-reload
 * time base with four independent capture/compare channels, PWM generation,
 * input capture, break/dead-time control and update/compare interrupts. Only
 * the register layout and bit meanings are reused; no vendor code is copied.
 *
 * Layout (byte offsets): CR1 0x00, CR2 0x04, SMCR 0x08, DIER 0x0C, SR 0x10,
 * EGR 0x14, CCMR0 0x18, CCMR1 0x1C, CCER 0x20, CNT 0x24, PSC 0x28, ARR 0x2C,
 * RCR 0x30, CCR[0..3] 0x34..0x40, BDTR 0x44.
 */

#include <stdint.h>

#include "ag32_device.h"
#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t CR1;      /* 0x00 control 1                          */
    volatile uint32_t CR2;      /* 0x04 control 2                          */
    volatile uint32_t SMCR;     /* 0x08 slave-mode control                 */
    volatile uint32_t DIER;     /* 0x0c DMA/interrupt enable               */
    volatile uint32_t SR;       /* 0x10 status                            */
    volatile uint32_t EGR;      /* 0x14 event generation (write-1)         */
    volatile uint32_t CCMR0;    /* 0x18 capture/compare mode (ch0/ch1)     */
    volatile uint32_t CCMR1;    /* 0x1c capture/compare mode (ch2/ch3)     */
    volatile uint32_t CCER;     /* 0x20 capture/compare enable             */
    volatile uint32_t CNT;      /* 0x24 counter                           */
    volatile uint32_t PSC;      /* 0x28 prescaler                         */
    volatile uint32_t ARR;      /* 0x2c auto-reload                       */
    volatile uint32_t RCR;      /* 0x30 repetition counter                 */
    volatile uint32_t CCR[4];   /* 0x34..0x40 capture/compare values       */
    volatile uint32_t BDTR;     /* 0x44 break and dead-time                */
} ag32_gptimer_t;

#define AG32_GPTIMER0 ((ag32_gptimer_t *)(uintptr_t)AG32_GPTIMER0_BASE)
#define AG32_GPTIMER1 ((ag32_gptimer_t *)(uintptr_t)AG32_GPTIMER1_BASE)
#define AG32_GPTIMER2 ((ag32_gptimer_t *)(uintptr_t)AG32_GPTIMER2_BASE)
#define AG32_GPTIMER3 ((ag32_gptimer_t *)(uintptr_t)AG32_GPTIMER3_BASE)
#define AG32_GPTIMER4 ((ag32_gptimer_t *)(uintptr_t)AG32_GPTIMER4_BASE)

/* CR1 */
#define AG32_GPTIMER_CR1_CEN   (1u << 0)  /* counter enable            */
#define AG32_GPTIMER_CR1_UDIS  (1u << 1)  /* update disable            */
#define AG32_GPTIMER_CR1_URS   (1u << 2)  /* update request source     */
#define AG32_GPTIMER_CR1_OPM   (1u << 3)  /* one-pulse mode            */
#define AG32_GPTIMER_CR1_DIR   (1u << 4)  /* 0 up, 1 down              */
#define AG32_GPTIMER_CR1_ARPE  (1u << 7)  /* auto-reload preload       */
#define AG32_GPTIMER_CR1_CMS(n)   (((uint32_t)(n) & 3u) << 5)
#define AG32_GPTIMER_CR1_CKD(n)   (((uint32_t)(n) & 3u) << 8)

/* CR2 master-mode selection (TRGO source). */
#define AG32_GPTIMER_CR2_MMS(n)   (((uint32_t)(n) & 7u) << 4)

/* SMCR slave-mode selection / trigger. */
#define AG32_GPTIMER_SMCR_SMS(n)  (((uint32_t)(n) & 7u) << 0)
#define AG32_GPTIMER_SMCR_TS(n)   (((uint32_t)(n) & 7u) << 4)
#define AG32_GPTIMER_SMCR_ECE     (1u << 14) /* external clock enable  */

/* DIER interrupt enables */
#define AG32_GPTIMER_DIER_UIE     (1u << 0)  /* update                 */
#define AG32_GPTIMER_DIER_CCIE(ch) (1u << (1u + (uint32_t)(ch)))
#define AG32_GPTIMER_DIER_TIE     (1u << 6)  /* trigger                */
#define AG32_GPTIMER_DIER_BIE     (1u << 7)  /* break                  */
#define AG32_GPTIMER_DIER_UDE     (1u << 8)  /* update DMA request     */
#define AG32_GPTIMER_DIER_CCDE(ch) (1u << (9u + (uint32_t)(ch)))

/* SR status flags (write-0 to clear a flag) */
#define AG32_GPTIMER_SR_UIF       (1u << 0)
#define AG32_GPTIMER_SR_CCIF(ch)  (1u << (1u + (uint32_t)(ch)))
#define AG32_GPTIMER_SR_TIF       (1u << 6)
#define AG32_GPTIMER_SR_BIF       (1u << 7)
#define AG32_GPTIMER_SR_CCOF(ch)  (1u << (9u + (uint32_t)(ch)))

/* EGR event generation (write-1) */
#define AG32_GPTIMER_EGR_UG       (1u << 0)  /* force update           */
#define AG32_GPTIMER_EGR_CCG(ch)  (1u << (1u + (uint32_t)(ch)))
#define AG32_GPTIMER_EGR_TG       (1u << 6)
#define AG32_GPTIMER_EGR_BG       (1u << 7)

/*
 * CCMR is two channels per register, each in an 8-bit half. For channel ch:
 * register index is ch>>1, and the field shift is 8 for the odd channel.
 * Output-compare view: CCS[1:0], OCxFE[2], OCxPE[3], OCxM[6:4], OCxCE[7].
 * Input-capture view:  CCS[1:0], ICxPSC[3:2], ICxF[7:4].
 */
#define AG32_GPTIMER_CCS_OUTPUT   0u
#define AG32_GPTIMER_CCS_INPUT_TI 1u          /* map TIx directly       */
#define AG32_GPTIMER_OCM_FROZEN   0u
#define AG32_GPTIMER_OCM_TOGGLE   3u
#define AG32_GPTIMER_OCM_PWM1     6u          /* active while CNT<CCR   */
#define AG32_GPTIMER_OCM_PWM2     7u          /* active while CNT>=CCR  */
#define AG32_GPTIMER_OCPE         (1u << 3)   /* preload enable (in half)*/

/* CCER packs four bits per channel: CCxE, CCxP, CCxNE, CCxNP. */
#define AG32_GPTIMER_CCER_CCE(ch)  (1u << ((uint32_t)(ch) * 4u))
#define AG32_GPTIMER_CCER_CCP(ch)  (1u << ((uint32_t)(ch) * 4u + 1u))
#define AG32_GPTIMER_CCER_CCNE(ch) (1u << ((uint32_t)(ch) * 4u + 2u))
#define AG32_GPTIMER_CCER_CCNP(ch) (1u << ((uint32_t)(ch) * 4u + 3u))

/* BDTR */
#define AG32_GPTIMER_BDTR_DTG(n)  ((uint32_t)(n) & 0xffu) /* dead-time  */
#define AG32_GPTIMER_BDTR_BKE     (1u << 12) /* break enable            */
#define AG32_GPTIMER_BDTR_BKP     (1u << 13) /* break polarity high     */
#define AG32_GPTIMER_BDTR_AOE     (1u << 14) /* automatic output enable */
#define AG32_GPTIMER_BDTR_MOE     (1u << 15) /* main output enable      */

static inline unsigned ag32_gptimer_index(const ag32_gptimer_t *gpt) {
    return (unsigned)(((uintptr_t)gpt - AG32_GPTIMER0_BASE) / 0x1000u);
}

/*
 * Program the time base: PSC divides the timer clock, ARR is the period
 * (up-counting wraps at ARR). A forced update loads PSC/ARR into the shadow
 * registers. The counter is left disabled; call ag32_gptimer_start().
 */
static inline int ag32_gptimer_init(ag32_gptimer_t *gpt, uint32_t prescaler,
                                    uint32_t reload) {
    unsigned index = ag32_gptimer_index(gpt);
    if (index >= AG32_GPTIMER_COUNT)
        return -1;
    ag32_apb_enable(AG32_APB_GPTIMER(index));
    ag32_apb_reset(AG32_APB_GPTIMER(index));
    gpt->CR1 = 0u;
    gpt->PSC = prescaler;
    gpt->ARR = reload;
    gpt->RCR = 0u;
    gpt->EGR = AG32_GPTIMER_EGR_UG;   /* latch PSC/ARR now */
    gpt->SR = 0u;                     /* clear the update flag raised by UG */
    return 0;
}

static inline void ag32_gptimer_start(ag32_gptimer_t *gpt) {
    gpt->CR1 |= AG32_GPTIMER_CR1_CEN;
}

static inline void ag32_gptimer_stop(ag32_gptimer_t *gpt) {
    gpt->CR1 &= ~AG32_GPTIMER_CR1_CEN;
}

static inline uint32_t ag32_gptimer_counter(const ag32_gptimer_t *gpt) {
    return gpt->CNT;
}

static inline void ag32_gptimer_set_compare(ag32_gptimer_t *gpt, unsigned channel,
                                            uint32_t value) {
    if (channel < 4u)
        gpt->CCR[channel] = value;
}

static inline uint32_t ag32_gptimer_capture(const ag32_gptimer_t *gpt,
                                            unsigned channel) {
    return channel < 4u ? gpt->CCR[channel] : 0u;
}

/*
 * Configure one channel as an edge-aligned PWM output. mode is PWM1 or PWM2;
 * compare is the duty threshold against ARR. Enables output preload, the
 * channel output, and main-output-enable so advanced-timer outputs actually
 * drive. The time base must already be programmed with ag32_gptimer_init().
 */
static inline int ag32_gptimer_pwm_output(ag32_gptimer_t *gpt, unsigned channel,
                                          uint32_t mode, uint32_t compare) {
    if (channel >= 4u || (mode != AG32_GPTIMER_OCM_PWM1 &&
                          mode != AG32_GPTIMER_OCM_PWM2))
        return -1;
    volatile uint32_t *ccmr = (channel < 2u) ? &gpt->CCMR0 : &gpt->CCMR1;
    unsigned shift = (channel & 1u) ? 8u : 0u;
    uint32_t field = ((mode & 7u) << 4) | AG32_GPTIMER_OCPE; /* CCS=output */
    *ccmr = (*ccmr & ~(0xffu << shift)) | (field << shift);
    gpt->CCR[channel] = compare;
    gpt->CCER |= AG32_GPTIMER_CCER_CCE(channel);
    gpt->CR1 |= AG32_GPTIMER_CR1_ARPE;
    gpt->BDTR |= AG32_GPTIMER_BDTR_MOE;
    return 0;
}

/*
 * Configure one channel as an input capture on TIx. polarity selects the
 * active edge via CCP/CCNP; read the captured value with ag32_gptimer_capture()
 * after the corresponding CCIF flag sets.
 */
static inline int ag32_gptimer_input_capture(ag32_gptimer_t *gpt, unsigned channel,
                                             uint32_t ccer_polarity) {
    if (channel >= 4u)
        return -1;
    volatile uint32_t *ccmr = (channel < 2u) ? &gpt->CCMR0 : &gpt->CCMR1;
    unsigned shift = (channel & 1u) ? 8u : 0u;
    uint32_t field = AG32_GPTIMER_CCS_INPUT_TI; /* map TIx to ICx, no filter */
    *ccmr = (*ccmr & ~(0xffu << shift)) | (field << shift);
    gpt->CCER &= ~(0xfu << (channel * 4u));
    gpt->CCER |= AG32_GPTIMER_CCER_CCE(channel) | ccer_polarity;
    return 0;
}

static inline void ag32_gptimer_enable_update_irq(ag32_gptimer_t *gpt) {
    gpt->DIER |= AG32_GPTIMER_DIER_UIE;
}

static inline int ag32_gptimer_update_flag(const ag32_gptimer_t *gpt) {
    return (gpt->SR & AG32_GPTIMER_SR_UIF) ? 1 : 0;
}

static inline void ag32_gptimer_clear_flags(ag32_gptimer_t *gpt, uint32_t mask) {
    gpt->SR = ~mask;   /* status bits are cleared by writing 0 */
}

#endif /* AGAMEMNON_AG32_GPTIMER_H */
