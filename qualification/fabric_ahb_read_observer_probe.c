#include "ag32_hil_campaign.h"

/*
 * Low-SRAM observer for the bounded fabric-master readback arm. After _start
 * has entered main, the retired first two startup words are replaced by the
 * explicit 0/1 markers. The live service loop remains below the mailbox at
 * 0x20001000. The first External-AHB read at +0/+4, or a transition between
 * them, emits one bounded fabric-master request; later same-address reads only
 * return its retained four-bit status.
 */

#define SRAM_WORD0 (*(volatile uint32_t *)0x20000000u)
#define SRAM_WORD1 (*(volatile uint32_t *)0x20000004u)
#define DEBUG_WORDS ((volatile uint32_t *)0x20000008u)
#define STATUS_WORD0 ((volatile const uint32_t *)0x60000000u)
#define STATUS_WORD1 ((volatile const uint32_t *)0x60000004u)

#define STATUS_RESPONSE (1u << 0)
#define STATUS_BUSY     (1u << 1)
#define STATUS_DONE     (1u << 2)
#define STATUS_VALID    (1u << 3)

#define REG32(address) (*(volatile uint32_t *)(address))
#define SYS_CLKSEL     REG32(0x0300000cu)
#define APB_ENABLE     REG32(0x03000060u)

static inline void io_fence(void) {
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
}

static uint32_t observe_phase(volatile const uint32_t *status) {
    uint32_t index;
    uint32_t sample = 0u;
    uint32_t seen = 0u;
    uint32_t response_ones = 0u;

    /* One endpoint load emits one request; the delay covers its four clocks. */
    sample = *status;
    io_fence();
    for (index = 0u; index < 128u; ++index)
        __asm__ volatile ("nop");

    /* Same-address polls are passive and must observe a stable result. */
    for (index = 0u; index < 32u; ++index) {
        sample = *status & 0x0fu;
        seen |= sample;
        response_ones += sample & STATUS_RESPONSE;
    }
    return (sample & 0x0fu) |
           ((seen & STATUS_BUSY) ? (1u << 8) : 0u) |
           ((seen & STATUS_DONE) ? (1u << 9) : 0u) |
           ((seen & STATUS_VALID) ? (1u << 10) : 0u) |
           ((response_ones != 32u) ? (1u << 11) : 0u) |
           ((response_ones != 0u) ? (1u << 12) : 0u) |
           (response_ones << 16);
}

static uint32_t observe(
        uint32_t sequence, uint32_t image_tag,
        volatile uint32_t *words, uint32_t capacity) {
    (void)sequence;
    (void)image_tag;
    if (capacity < 6u)
        return capacity + 1u;

    words[0] = observe_phase(STATUS_WORD0);
    words[1] = observe_phase(STATUS_WORD1);
    words[2] = observe_phase(STATUS_WORD0);
    words[3] = SRAM_WORD0;
    words[4] = SRAM_WORD1;
    words[5] = 0x41484252u; /* "AHBR" */
    return 6u;
}

int main(void) {
    volatile ag32_fcb_restream_mailbox_t *const restream =
        (volatile ag32_fcb_restream_mailbox_t *)
            AG32_FCB_RESTREAM_MAILBOX_ADDRESS;
    volatile ag32_hil_campaign_mailbox_t *const campaign =
        (volatile ag32_hil_campaign_mailbox_t *)
            AG32_HIL_CAMPAIGN_MAILBOX_ADDRESS;
    const uint32_t *const image =
        (const uint32_t *)AG32_FCB_RESTREAM_IMAGE_ADDRESS;
    uint32_t fault_latched = 0u;

    /* Match the qualified low-SRAM FCB probes before publishing READY. */
    SYS_CLKSEL &= ~0x27u;
    APB_ENABLE |= (1u << 0) | (1u << 8);
    DEBUG_WORDS[0] = SYS_CLKSEL;
    DEBUG_WORDS[1] = APB_ENABLE;
    DEBUG_WORDS[2] = FCB_STAT;
    SRAM_WORD0 = 0u;
    SRAM_WORD1 = 1u;
    io_fence();
    ag32_fcb_restream_init(restream);
    ag32_hil_campaign_init(campaign);
    for (;;) {
        uint32_t handled = ag32_hil_campaign_service(
            restream, campaign, image, &fault_latched, observe);
        if (handled != 0u) {
            DEBUG_WORDS[3] = SYS_CLKSEL;
            DEBUG_WORDS[4] = APB_ENABLE;
            DEBUG_WORDS[5] = FCB_STAT;
        }
    }
}
