#include "ag32_hil_campaign.h"

/*
 * R4 transition-trace observer for the bounded fabric-master readback arm.
 * The live firmware remains in the dedicated R3 high-SRAM window, while only
 * the explicit 0/1 marker words occupy low SRAM.  Each phase performs one
 * transaction-triggering endpoint read, waits the same 128-NOP interval used
 * by R3, and then records 64 consecutive passive same-address status reads.
 * Eight owned four-bit endpoint samples are packed little-nibble-first into
 * each trace word.  The first 32 samples are diagnostic; classification is
 * deliberately confined to the final 32-sample stable suffix.
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

static inline void io_fence(void) {
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
}

static void trace_phase(
        volatile const uint32_t *status, volatile uint32_t *trace) {
    uint32_t index;
    uint32_t sample;

    /* Exactly one endpoint load emits the request; the delay covers it. */
    sample = *status;
    (void)sample;
    io_fence();
    for (index = 0u; index < 128u; ++index)
        __asm__ volatile ("nop");

    /* Later same-address reads are passive; preserve every owned low nibble. */
    for (index = 0u; index < TRACE_SAMPLES_PER_PHASE; ++index) {
        sample = *status & 0x0fu;
        trace[index >> 3] |= sample << ((index & 7u) * 4u);
    }
}

static uint32_t observe(
        uint32_t sequence, uint32_t image_tag,
        volatile uint32_t *words, uint32_t capacity) {
    uint32_t index;

    (void)sequence;
    (void)image_tag;
    if (capacity < OBSERVATION_WORDS)
        return capacity + 1u;

    for (index = 0u; index < 3u * TRACE_WORDS_PER_PHASE; ++index)
        words[index] = 0u;

    trace_phase(STATUS_WORD0, &words[0]);
    trace_phase(STATUS_WORD1, &words[8]);
    trace_phase(STATUS_WORD0, &words[16]);
    words[24] = SRAM_WORD0;
    words[25] = SRAM_WORD1;
    words[26] = 0x41484252u; /* "AHBR" */
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
        (void)ag32_hil_campaign_service(
            restream, campaign, image, &fault_latched, observe);
    }
}
