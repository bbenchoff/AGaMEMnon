#ifndef AGAMEMNON_AG32_DMA_H
#define AGAMEMNON_AG32_DMA_H

#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t SRC;
    volatile uint32_t DST;
    volatile uint32_t LLI;
    volatile uint32_t CONTROL;
    volatile uint32_t CONFIG;
    uint32_t reserved[3];
} ag32_dma_channel_t;

typedef struct {
    volatile const uint32_t INT_STATUS;      /* 0x000 */
    volatile const uint32_t INT_TC_STATUS;   /* 0x004 */
    volatile uint32_t INT_TC_CLEAR;          /* 0x008 */
    volatile const uint32_t INT_ERR_STATUS;  /* 0x00c */
    volatile uint32_t INT_ERR_CLEAR;         /* 0x010 */
    volatile const uint32_t RAW_TC_STATUS;   /* 0x014 */
    volatile const uint32_t RAW_ERR_STATUS;  /* 0x018 */
    volatile const uint32_t ENABLED_CHANNELS;/* 0x01c */
    volatile uint32_t SOFT_BREQ;             /* 0x020 */
    volatile uint32_t SOFT_SREQ;             /* 0x024 */
    volatile uint32_t SOFT_LBREQ;            /* 0x028 */
    volatile uint32_t SOFT_LSREQ;            /* 0x02c */
    volatile uint32_t CONFIG;                /* 0x030 */
    volatile uint32_t SYNC;                  /* 0x034 */
    uint32_t reserved0[50];                  /* 0x038..0x0fc */
    ag32_dma_channel_t CHANNEL[8];            /* 0x100, stride 0x20 */
} ag32_dma_t;

#define AG32_DMAC0 ((ag32_dma_t *)(uintptr_t)AG32_DMAC0_BASE)

#define AG32_DMA_ENABLE          (1u << 0)
#define AG32_DMA_CONTROL_SIZE(n) ((uint32_t)(n) & 0xfffu)
#define AG32_DMA_CONTROL_SWIDTH(n) (((uint32_t)(n) & 7u) << 18)
#define AG32_DMA_CONTROL_DWIDTH(n) (((uint32_t)(n) & 7u) << 21)
#define AG32_DMA_CONTROL_SINC    (1u << 26)
#define AG32_DMA_CONTROL_DINC    (1u << 27)
#define AG32_DMA_CONTROL_TC_IRQ  (1u << 31)
#define AG32_DMA_WIDTH_8         0u
#define AG32_DMA_WIDTH_16        1u
#define AG32_DMA_WIDTH_32        2u

static inline void ag32_dma_init(void) {
    ag32_ahb_enable(AG32_AHB_DMAC0);
    ag32_ahb_reset(AG32_AHB_DMAC0);
    AG32_DMAC0->CONFIG = AG32_DMA_ENABLE;
}

/* Start a memory-to-memory copy. words must be 1..4095 and both pointers aligned. */
static inline int ag32_dma_copy32(unsigned channel, void *destination,
                                  const void *source, uint32_t words) {
    if (channel >= 8u || !words || words > 0xfffu ||
        (((uintptr_t)source | (uintptr_t)destination) & 3u))
        return -1;
    if (AG32_DMAC0->ENABLED_CHANNELS & (1u << channel))
        return -2;
    AG32_DMAC0->INT_TC_CLEAR = 1u << channel;
    AG32_DMAC0->INT_ERR_CLEAR = 1u << channel;
    ag32_dma_channel_t *ch = &AG32_DMAC0->CHANNEL[channel];
    ch->SRC = (uint32_t)(uintptr_t)source;
    ch->DST = (uint32_t)(uintptr_t)destination;
    ch->LLI = 0;
    ch->CONTROL = AG32_DMA_CONTROL_SIZE(words) |
                  AG32_DMA_CONTROL_SWIDTH(AG32_DMA_WIDTH_32) |
                  AG32_DMA_CONTROL_DWIDTH(AG32_DMA_WIDTH_32) |
                  AG32_DMA_CONTROL_SINC | AG32_DMA_CONTROL_DINC |
                  AG32_DMA_CONTROL_TC_IRQ;
    ch->CONFIG = AG32_DMA_ENABLE; /* flow-control 0: memory to memory */
    return 0;
}

static inline int ag32_dma_wait(unsigned channel, uint32_t timeout) {
    while (AG32_DMAC0->ENABLED_CHANNELS & (1u << channel)) {
        if (!timeout--)
            return -1;
    }
    return (AG32_DMAC0->RAW_ERR_STATUS & (1u << channel)) ? -2 : 0;
}

#endif
