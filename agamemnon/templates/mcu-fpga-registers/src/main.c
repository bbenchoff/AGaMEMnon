#include "ag32.h"

static inline void fabric_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline void fabric_reset(uint32_t asserted) {
    GPIO4_DATA(1u << 1) = asserted ? (1u << 1) : 0u;
}

int main(void) {
    volatile uint32_t *result = (volatile uint32_t *)0x20001000u;
    volatile uint32_t *word = (volatile uint32_t *)AG32_EXT_AHB_BASE;
    volatile uint16_t *half = (volatile uint16_t *)AG32_EXT_AHB_BASE;
    volatile uint8_t *byte = (volatile uint8_t *)AG32_EXT_AHB_BASE;
    uint32_t seen = 0u;
    uint32_t counter_range_ok = 1u;

    SYSCTL_APBCLK |= APBCLK_GPIO4;
    GPIO4_AFSEL &= ~(1u << 1);
    GPIO4_DIR |= 1u << 1;
    fabric_reset(1u);

    result[0] = ag32_fcb_config((const uint32_t *)0x20002000u, 24986u);
    for (volatile uint32_t i = 0; i < 256u; ++i) { }
    result[1] = word[0] & 0xffffu;
    result[2] = word[1] & 0xffffu;
    uint32_t reset_counter = word[2] & 0xffffu;
    uint32_t reset_status = word[3] & 0xffffu;

    fabric_reset(0u);
    for (volatile uint32_t i = 0; i < 256u; ++i) { }

    word[1] = 0xa55au;
    fabric_fence();
    result[3] = word[1] & 0xffffu;
    half[2] = 0x5aa5u;
    fabric_fence();
    result[4] = half[2];
    byte[4] = 0x3cu;
    byte[5] = 0xc3u;
    fabric_fence();
    result[5] = word[1] & 0xffffu;

    for (uint32_t i = 0; i < 512u; ++i) {
        uint32_t counter = word[2] & 0xffffu;
        if (counter <= 7u)
            seen |= 1u << counter;
        else
            counter_range_ok = 0u;
    }
    result[6] = seen;

    word[3] = 2u;
    fabric_fence();
    for (uint32_t i = 0; i < 8u; ++i)
        result[7] = word[3] & 1u;
    word[3] = 1u;
    fabric_fence();
    for (uint32_t i = 0; i < 8u; ++i)
        result[8] = word[3] & 1u;

    result[9] = word[0] & 0xffffu;
    result[10] = word[1] & 0xffffu;
    result[11] = (
        result[0] == FCB_STAT_OK && result[1] == 0x004du &&
        result[2] == 0u && reset_counter == 0u && reset_status == 0u &&
        result[3] == 0xa55au && result[4] == 0x5aa5u &&
        result[5] == 0xc33cu && result[6] == 0xffu && counter_range_ok &&
        result[7] == 1u && result[8] == 0u &&
        result[9] == 0x004du && result[10] == 0xc33cu
    ) ? 0x50415353u : 0x4641494cu;

    for (;;) { }
}
