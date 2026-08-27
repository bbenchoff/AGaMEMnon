#include "ag32_hil_campaign.h"

/*
 * Buffered successor to the perturbative R4 transition trace.  All 192
 * samples are accumulated through the reusable high-SRAM scratch service.
 * The service copies the 27-word result to the low-SRAM campaign mailbox only
 * after observe() returns.  Marker reads happen after all trace windows.
 */

#define SRAM_WORD0 (*(volatile uint32_t *)0x20000000u)
#define SRAM_WORD1 (*(volatile uint32_t *)0x20000004u)
#define STATUS_WORD0 ((volatile const uint32_t *)0x60000000u)
#define STATUS_WORD1 ((volatile const uint32_t *)0x60000004u)

#define TRACE_SAMPLES_PER_PHASE 64u
#define TRACE_WORDS_PER_PHASE    8u
#define OBSERVATION_WORDS       27u

#define REG32(address) (*(volatile uint32_t *)(address))
#define SYS_CLKSEL     REG32(0x0300000cu)
#define APB_ENABLE     REG32(0x03000060u)

AG32_HIL_CAMPAIGN_BUFFERED_SCRATCH(ag32_hil_observer_scratch);

static inline void io_fence(void) {
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
}

__attribute__((noinline))
static void trace_phase(
        volatile const uint32_t *status, uint32_t phase) {
    uint32_t word;

    /* Exactly one endpoint load emits the request; the delay covers it. */
    uint32_t sample = *status;
    (void)sample;
    io_fence();
    for (sample = 0u; sample < 128u; ++sample)
        __asm__ volatile ("nop");

    for (word = 0u; word < TRACE_WORDS_PER_PHASE; ++word) {
        uint32_t nibble;
        uint32_t packed = 0u;
        for (nibble = 0u; nibble < 8u; ++nibble) {
            sample = *status & 0x0fu;
            packed |= sample << (nibble * 4u);
        }
        ag32_hil_observer_scratch[
            phase * TRACE_WORDS_PER_PHASE + word] = packed;
    }
}

static uint32_t observe(
        uint32_t sequence, uint32_t image_tag,
        uint32_t *scratch, uint32_t capacity) {
    (void)sequence;
    (void)image_tag;
    if (capacity < OBSERVATION_WORDS ||
            scratch != ag32_hil_observer_scratch)
        return capacity + 1u;

    trace_phase(STATUS_WORD0, 0u);
    trace_phase(STATUS_WORD1, 1u);
    trace_phase(STATUS_WORD0, 2u);
    scratch[24] = SRAM_WORD0;
    scratch[25] = SRAM_WORD1;
    scratch[26] = 0x41484252u; /* "AHBR" */
    return OBSERVATION_WORDS;
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

    SYS_CLKSEL &= ~0x27u;
    APB_ENABLE |= (1u << 0) | (1u << 8);
    SRAM_WORD0 = 0u;
    SRAM_WORD1 = 1u;
    io_fence();
    ag32_fcb_restream_init(restream);
    ag32_hil_campaign_init(campaign);
    for (;;) {
        (void)ag32_hil_campaign_service_buffered(
            restream, campaign, image, &fault_latched, observe,
            ag32_hil_observer_scratch,
            AG32_HIL_CAMPAIGN_MAX_WORDS);
    }
}
