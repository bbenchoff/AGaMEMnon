#ifndef AGAMEMNON_AG32_COMPARATOR_H
#define AGAMEMNON_AG32_COMPARATOR_H

/*
 * Open AG32 analog comparator (CMP0) driver, written from the published
 * register map. CMP0 is a dual comparator: each of the two units has an
 * independently selectable positive and negative input and a live output bit.
 * It is an analog hard block reached over the External-AHB (fabric) window,
 * not MCU-core MMIO. No vendor code is copied.
 *
 * Layout: CTRL 0x00 (per-unit enable/hysteresis/mode), CHNL 0x04 (per-unit
 * +/- input selects), DATA 0x08 (per-unit output).
 *
 * Silicon status (L48, open flow, 2026-08-14): unit 1 is QUALIFIED. With
 * PSEL1 = DAC0 and MSEL1 walking the four internal VREF taps, its output flipped
 * at DAC0 codes 94 / 188 / 281 / 373 -- a clean 1:2:3:4 progression against the
 * 93 / 186 / 279 / 372 the vendor RTL predicts. Unit 2 is UNPROVEN: it is
 * register-readable and its enable takes, but its output read high at every
 * DAC0 code under both PSEL2 selects, so its positive-input mux maps to
 * something other than unit 1's in an undocumented way. HYST and MODE have not
 * been exercised on silicon at all.
 */

#include <stdint.h>

#include "ag32_device.h"

typedef struct {
    volatile uint32_t CTRL;         /* 0x00 enables                        */
    volatile uint32_t CHNL;         /* 0x04 input selects                  */
    volatile const uint32_t DATA;   /* 0x08 comparator outputs             */
} ag32_cmp_t;

#define AG32_CMP0 ((ag32_cmp_t *)(uintptr_t)AG32_CMP0_BASE)

/*
 * CTRL: enable, hysteresis, and mode, one set per comparator unit. HYST and
 * MODE are register-map facts; neither has been exercised on silicon, and the
 * mode bit's effect is not characterized, so treat both as unqualified.
 */
#define AG32_CMP_CTRL_EN1    (1u << 0)
#define AG32_CMP_CTRL_HYST1  (1u << 1)   /* unit 1 hysteresis, unqualified   */
#define AG32_CMP_CTRL_MODE1  (1u << 2)   /* unit 1 mode select, unqualified  */
#define AG32_CMP_CTRL_EN2    (1u << 8)
#define AG32_CMP_CTRL_HYST2  (1u << 9)   /* unit 2 hysteresis, unqualified   */
#define AG32_CMP_CTRL_MODE2  (1u << 10)  /* unit 2 mode select, unqualified  */

/*
 * CHNL packs four selects: PSEL1[1:0], MSEL1[6:4], PSEL2[9:8], MSEL2[14:12].
 * PSEL chooses the positive input (1..2), MSEL the negative input (1..7).
 *
 * Unit 1's map is silicon-confirmed: PSEL1 = AG32_CMP_PSEL_DAC0 puts DAC0 on the
 * positive input and MSEL1 = 4..7 select the four internal VREF taps on the
 * negative input. Unit 2's positive-input map is NOT the same and is unproven.
 */
#define AG32_CMP_PSEL_CHNL1       1u   /* external analog input 1            */
#define AG32_CMP_PSEL_CHNL2       2u   /* unit 1: DAC0 (silicon-confirmed)   */
#define AG32_CMP_PSEL_DAC0        AG32_CMP_PSEL_CHNL2
#define AG32_CMP_MSEL_VREF_DIV4   4u   /* VREF/4                             */
#define AG32_CMP_MSEL_VREF_DIV2   5u   /* VREF/2                             */
#define AG32_CMP_MSEL_VREF_3DIV4  6u   /* 3*VREF/4                           */
#define AG32_CMP_MSEL_VREF        7u   /* VREF                               */
#define AG32_CMP_CHNL_PSEL1(s) (((uint32_t)(s) & 3u) << 0)
#define AG32_CMP_CHNL_MSEL1(s) (((uint32_t)(s) & 7u) << 4)
#define AG32_CMP_CHNL_PSEL2(s) (((uint32_t)(s) & 3u) << 8)
#define AG32_CMP_CHNL_MSEL2(s) (((uint32_t)(s) & 7u) << 12)
#define AG32_CMP_CHNL_PSEL1_MASK AG32_CMP_CHNL_PSEL1(3u)
#define AG32_CMP_CHNL_MSEL1_MASK AG32_CMP_CHNL_MSEL1(7u)
#define AG32_CMP_CHNL_PSEL2_MASK AG32_CMP_CHNL_PSEL2(3u)
#define AG32_CMP_CHNL_MSEL2_MASK AG32_CMP_CHNL_MSEL2(7u)

/* DATA: live output of each comparator unit (1 = positive input higher). */
#define AG32_CMP_DATA1  (1u << 0)
#define AG32_CMP_DATA2  (1u << 8)

/* Configure and enable comparator unit 1 with the chosen +/- inputs. */
static inline void ag32_cmp_configure1(ag32_cmp_t *cmp, uint32_t psel,
                                       uint32_t msel) {
    cmp->CHNL = (cmp->CHNL & ~(AG32_CMP_CHNL_PSEL1_MASK | AG32_CMP_CHNL_MSEL1_MASK)) |
                AG32_CMP_CHNL_PSEL1(psel) | AG32_CMP_CHNL_MSEL1(msel);
    cmp->CTRL |= AG32_CMP_CTRL_EN1;
}

/* Configure and enable comparator unit 2 with the chosen +/- inputs. */
static inline void ag32_cmp_configure2(ag32_cmp_t *cmp, uint32_t psel,
                                       uint32_t msel) {
    cmp->CHNL = (cmp->CHNL & ~(AG32_CMP_CHNL_PSEL2_MASK | AG32_CMP_CHNL_MSEL2_MASK)) |
                AG32_CMP_CHNL_PSEL2(psel) | AG32_CMP_CHNL_MSEL2(msel);
    cmp->CTRL |= AG32_CMP_CTRL_EN2;
}

/* Per-unit hysteresis. Register-map feature; unexercised on silicon. */
static inline void ag32_cmp_set_hysteresis1(ag32_cmp_t *cmp, int enable) {
    if (enable)
        cmp->CTRL |= AG32_CMP_CTRL_HYST1;
    else
        cmp->CTRL &= ~AG32_CMP_CTRL_HYST1;
}

static inline void ag32_cmp_set_hysteresis2(ag32_cmp_t *cmp, int enable) {
    if (enable)
        cmp->CTRL |= AG32_CMP_CTRL_HYST2;
    else
        cmp->CTRL &= ~AG32_CMP_CTRL_HYST2;
}

/* Per-unit mode select. Register-map feature; effect not characterized. */
static inline void ag32_cmp_set_mode1(ag32_cmp_t *cmp, int mode) {
    if (mode)
        cmp->CTRL |= AG32_CMP_CTRL_MODE1;
    else
        cmp->CTRL &= ~AG32_CMP_CTRL_MODE1;
}

static inline void ag32_cmp_set_mode2(ag32_cmp_t *cmp, int mode) {
    if (mode)
        cmp->CTRL |= AG32_CMP_CTRL_MODE2;
    else
        cmp->CTRL &= ~AG32_CMP_CTRL_MODE2;
}

static inline void ag32_cmp_disable1(ag32_cmp_t *cmp) {
    cmp->CTRL &= ~AG32_CMP_CTRL_EN1;
}

static inline void ag32_cmp_disable2(ag32_cmp_t *cmp) {
    cmp->CTRL &= ~AG32_CMP_CTRL_EN2;
}

static inline int ag32_cmp_output1(const ag32_cmp_t *cmp) {
    return (cmp->DATA & AG32_CMP_DATA1) ? 1 : 0;
}

static inline int ag32_cmp_output2(const ag32_cmp_t *cmp) {
    return (cmp->DATA & AG32_CMP_DATA2) ? 1 : 0;
}

#endif /* AGAMEMNON_AG32_COMPARATOR_H */
