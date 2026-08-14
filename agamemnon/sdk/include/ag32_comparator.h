#ifndef AGAMEMNON_AG32_COMPARATOR_H
#define AGAMEMNON_AG32_COMPARATOR_H

/*
 * Open AG32 analog comparator (CMP0) driver, written from the published
 * register map. CMP0 is a dual comparator: each of the two units has an
 * independently selectable positive and negative input and a live output bit.
 * It is an analog hard block reached over the External-AHB (fabric) window,
 * not MCU-core MMIO. No vendor code is copied.
 *
 * Layout: CTRL 0x00 (EN1/EN2), CHNL 0x04 (per-unit +/- input selects),
 * DATA 0x08 (per-unit output).
 */

#include <stdint.h>

#include "ag32_device.h"

typedef struct {
    volatile uint32_t CTRL;         /* 0x00 enables                        */
    volatile uint32_t CHNL;         /* 0x04 input selects                  */
    volatile const uint32_t DATA;   /* 0x08 comparator outputs             */
} ag32_cmp_t;

#define AG32_CMP0 ((ag32_cmp_t *)(uintptr_t)AG32_CMP0_BASE)

/* CTRL: one enable per comparator unit. */
#define AG32_CMP_CTRL_EN1  (1u << 0)
#define AG32_CMP_CTRL_EN2  (1u << 8)

/*
 * CHNL packs four selects: PSEL1[1:0], MSEL1[6:4], PSEL2[9:8], MSEL2[14:12].
 * PSEL chooses the positive input (1..2), MSEL the negative input (1..7).
 */
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
