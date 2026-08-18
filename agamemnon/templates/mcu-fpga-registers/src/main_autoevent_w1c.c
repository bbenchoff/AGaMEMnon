#include "ag32.h"

static inline void fabric_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline void fabric_reset(uint32_t asserted) {
    GPIO4_DATA(1u << 1) = asserted ? (1u << 1) : 0u;
}

static void settle(void) {
    for (volatile uint32_t i = 0; i < 256u; ++i) { }
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
    settle();
    result[1] = word[0];
    result[2] = word[1];
    uint32_t reset_counter = word[2];
    uint32_t reset_status = word[3];

    // Releasing reset arms one synchronous fabric event.  It latches STATUS,
    // then the source disarms so W1C bit0 can clear it permanently.
    fabric_reset(0u);
    settle();
    result[3] = word[3] & 1u;
    word[3] = 1u;
    fabric_fence();
    settle();
    result[4] = word[3] & 1u;

    word[1] = 0xa55au;
    fabric_fence();
    half[2] = 0x5aa5u;
    fabric_fence();
    byte[4] = 0x3cu;
    byte[5] = 0xc3u;
    fabric_fence();
    result[5] = word[1];

    // Poll until every one of the counter's 8 states has actually been
    // observed, instead of a fixed trip count. A fixed count only proves
    // coverage for whichever exact instruction timing it was tuned against;
    // the CPU-to-fabric AHB bridge crosses clock domains, so the number of
    // polls needed to walk through every phase varies with compiler,
    // optimization level, and wait-state timing. The 65536-poll safety cap
    // still fails closed (result[6] != 0xffu) if the counter is genuinely
    // stuck or miswired.
    for (uint32_t i = 0; i < 65536u && seen != 0xffu; ++i) {
        uint32_t counter = word[2];
        if (counter <= 7u)
            seen |= 1u << counter;
        else
            counter_range_ok = 0u;
    }
    result[6] = seen;

    // Reset must re-arm an independent second event.
    fabric_reset(1u);
    settle();
    result[7] = word[3] & 1u;
    fabric_reset(0u);
    settle();
    result[8] = word[3] & 1u;
    word[3] = 1u;
    fabric_fence();
    settle();
    result[9] = word[3] & 1u;

    result[10] = (
        result[0] == FCB_STAT_OK && result[1] == 0x4147414du &&
        result[2] == 0u && reset_counter == 0u && reset_status == 0u &&
        result[3] == 1u && result[4] == 0u && result[5] == 0xc33cu &&
        result[6] == 0xffu && counter_range_ok && result[7] == 0u &&
        result[8] == 1u && result[9] == 0u
    ) ? 0x50415353u : 0x4641494cu;

    fabric_reset(1u);
    for (;;) { }
}
