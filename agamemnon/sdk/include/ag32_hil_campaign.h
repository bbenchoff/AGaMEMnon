#ifndef AG32_HIL_CAMPAIGN_H
#define AG32_HIL_CAMPAIGN_H

/*
 * Observation mailbox layered on the one-firmware FCB restream service.
 *
 * After one exact image configures successfully, the caller-supplied observer
 * records raw DUT words here and publishes result_sequence last.  The host
 * classifies those words against a separately hash-bound campaign work list.
 * FCB acceptance and observation classification remain separate events.
 */

#include <stdint.h>

#include "ag32_fcb_restream.h"

#define AG32_HIL_CAMPAIGN_MAILBOX_ADDRESS 0x20001040u
#define AG32_HIL_CAMPAIGN_MAGIC           0x48494c43u /* "HILC" */
#define AG32_HIL_CAMPAIGN_VERSION         1u
#define AG32_HIL_CAMPAIGN_SENTINEL        0xc0ffee48u
#define AG32_HIL_CAMPAIGN_MAX_WORDS       32u

#define AG32_HIL_CAMPAIGN_STATE_READY 1u
#define AG32_HIL_CAMPAIGN_STATE_BUSY  2u
#define AG32_HIL_CAMPAIGN_STATE_DONE  3u
#define AG32_HIL_CAMPAIGN_STATE_ERROR 4u

#define AG32_HIL_CAMPAIGN_ERROR_NONE          0u
#define AG32_HIL_CAMPAIGN_ERROR_FCB           1u
#define AG32_HIL_CAMPAIGN_ERROR_OBSERVER_SIZE 2u
#define AG32_HIL_CAMPAIGN_ERROR_SCRATCH_LAYOUT 3u

/*
 * Buffered observers keep observation traffic out of the low-SRAM mailboxes.
 * A compatible high-SRAM linker script must retain the named section at or
 * above SCRATCH_MIN_ADDRESS.  The service copies accepted words to the public
 * mailbox only after the observer returns.  The original observer type and
 * ag32_hil_campaign_service() contract remain unchanged.
 */
#define AG32_HIL_CAMPAIGN_SCRATCH_MIN_ADDRESS 0x2001b000u
#define AG32_HIL_CAMPAIGN_SCRATCH_END_ADDRESS 0x20020000u
#define AG32_HIL_CAMPAIGN_BUFFERED_SCRATCH(name)                         \
    uint32_t name[AG32_HIL_CAMPAIGN_MAX_WORDS]                           \
        __attribute__((section(".ag32_hil_observer_scratch"), aligned(4), used))

typedef struct {
    volatile uint32_t magic;
    volatile uint32_t version;
    volatile uint32_t state;
    volatile uint32_t result_sequence;
    volatile uint32_t result_tag;
    volatile uint32_t word_count;
    volatile uint32_t error_code;
    volatile uint32_t reserved;
    volatile uint32_t words[AG32_HIL_CAMPAIGN_MAX_WORDS];
    volatile uint32_t sentinel;
} ag32_hil_campaign_mailbox_t;

_Static_assert(sizeof(ag32_hil_campaign_mailbox_t) == 41u * sizeof(uint32_t),
               "HIL campaign mailbox must be exactly 41 words");

typedef uint32_t (*ag32_hil_campaign_observer_t)(
    uint32_t sequence, uint32_t image_tag,
    volatile uint32_t *words, uint32_t capacity);

typedef uint32_t (*ag32_hil_campaign_buffered_observer_t)(
    uint32_t sequence, uint32_t image_tag,
    uint32_t *scratch, uint32_t capacity);

static inline void ag32_hil_campaign_init(
        volatile ag32_hil_campaign_mailbox_t *mailbox) {
    uint32_t index;
    mailbox->magic = 0u;
    mailbox->version = AG32_HIL_CAMPAIGN_VERSION;
    mailbox->state = AG32_HIL_CAMPAIGN_STATE_READY;
    mailbox->result_sequence = 0u;
    mailbox->result_tag = 0u;
    mailbox->word_count = 0u;
    mailbox->error_code = AG32_HIL_CAMPAIGN_ERROR_NONE;
    mailbox->reserved = 0u;
    for (index = 0u; index < AG32_HIL_CAMPAIGN_MAX_WORDS; ++index)
        mailbox->words[index] = 0u;
    mailbox->sentinel = AG32_HIL_CAMPAIGN_SENTINEL;
    ag32_fcb_restream_fence();
    mailbox->magic = AG32_HIL_CAMPAIGN_MAGIC;
}

static inline void ag32_hil_campaign_complete(
        volatile ag32_hil_campaign_mailbox_t *mailbox,
        uint32_t sequence, uint32_t tag, uint32_t state,
        uint32_t word_count, uint32_t error_code) {
    mailbox->result_tag = tag;
    mailbox->word_count = word_count;
    mailbox->error_code = error_code;
    mailbox->state = state;
    ag32_fcb_restream_fence();
    mailbox->result_sequence = sequence;
}

/* Service at most one new image and, only after exact FCB success, observe it. */
static inline uint32_t ag32_hil_campaign_service(
        volatile ag32_fcb_restream_mailbox_t *restream,
        volatile ag32_hil_campaign_mailbox_t *campaign,
        const uint32_t *image, uint32_t *fault_latched,
        ag32_hil_campaign_observer_t observer) {
    uint32_t index;
    uint32_t handled = ag32_fcb_restream_service(
        restream, image, fault_latched);
    if (handled == 0u)
        return 0u;

    uint32_t sequence = restream->result_sequence;
    uint32_t tag = restream->result_tag;
    campaign->result_sequence = 0u;
    campaign->result_tag = tag;
    campaign->word_count = 0u;
    campaign->error_code = AG32_HIL_CAMPAIGN_ERROR_NONE;
    campaign->state = AG32_HIL_CAMPAIGN_STATE_BUSY;
    for (index = 0u; index < AG32_HIL_CAMPAIGN_MAX_WORDS; ++index)
        campaign->words[index] = 0u;
    ag32_fcb_restream_fence();

    if (restream->state != AG32_FCB_RESTREAM_STATE_DONE ||
            restream->result_code != AG32_FCB_RESTREAM_RESULT_OK ||
            restream->fcb_status != FCB_STAT_OK) {
        ag32_hil_campaign_complete(
            campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_ERROR, 0u,
            AG32_HIL_CAMPAIGN_ERROR_FCB);
        return 1u;
    }

    uint32_t count = observer(
        sequence, tag, campaign->words, AG32_HIL_CAMPAIGN_MAX_WORDS);
    if (count > AG32_HIL_CAMPAIGN_MAX_WORDS) {
        for (index = 0u; index < AG32_HIL_CAMPAIGN_MAX_WORDS; ++index)
            campaign->words[index] = 0u;
        ag32_hil_campaign_complete(
            campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_ERROR, 0u,
            AG32_HIL_CAMPAIGN_ERROR_OBSERVER_SIZE);
        return 1u;
    }

    ag32_hil_campaign_complete(
        campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_DONE, count,
        AG32_HIL_CAMPAIGN_ERROR_NONE);
    return 1u;
}

/*
 * Backward-compatible buffered service.  Low-SRAM campaign metadata is made
 * BUSY before observation.  During the observer callback, all result writes
 * are confined to caller-owned high SRAM.  Successful results are copied to
 * the mailbox as a single post-observation publication phase.
 */
static inline uint32_t ag32_hil_campaign_service_buffered(
        volatile ag32_fcb_restream_mailbox_t *restream,
        volatile ag32_hil_campaign_mailbox_t *campaign,
        const uint32_t *image, uint32_t *fault_latched,
        ag32_hil_campaign_buffered_observer_t observer,
        uint32_t *scratch, uint32_t scratch_capacity) {
    uint32_t index;
    uint32_t handled = ag32_fcb_restream_service(
        restream, image, fault_latched);
    if (handled == 0u)
        return 0u;

    uint32_t sequence = restream->result_sequence;
    uint32_t tag = restream->result_tag;
    campaign->result_sequence = 0u;
    campaign->result_tag = tag;
    campaign->word_count = 0u;
    campaign->error_code = AG32_HIL_CAMPAIGN_ERROR_NONE;
    campaign->state = AG32_HIL_CAMPAIGN_STATE_BUSY;
    for (index = 0u; index < AG32_HIL_CAMPAIGN_MAX_WORDS; ++index)
        campaign->words[index] = 0u;
    ag32_fcb_restream_fence();

    if (restream->state != AG32_FCB_RESTREAM_STATE_DONE ||
            restream->result_code != AG32_FCB_RESTREAM_RESULT_OK ||
            restream->fcb_status != FCB_STAT_OK) {
        ag32_hil_campaign_complete(
            campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_ERROR, 0u,
            AG32_HIL_CAMPAIGN_ERROR_FCB);
        return 1u;
    }

    uintptr_t scratch_begin = (uintptr_t)scratch;
    uintptr_t scratch_bytes =
        (uintptr_t)scratch_capacity * (uintptr_t)sizeof(uint32_t);
    uintptr_t scratch_end = scratch_begin + scratch_bytes;
    if (scratch_capacity != AG32_HIL_CAMPAIGN_MAX_WORDS ||
            scratch_end < scratch_begin ||
            scratch_begin < AG32_HIL_CAMPAIGN_SCRATCH_MIN_ADDRESS ||
            scratch_end > AG32_HIL_CAMPAIGN_SCRATCH_END_ADDRESS) {
        ag32_hil_campaign_complete(
            campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_ERROR, 0u,
            AG32_HIL_CAMPAIGN_ERROR_SCRATCH_LAYOUT);
        return 1u;
    }

    for (index = 0u; index < AG32_HIL_CAMPAIGN_MAX_WORDS; ++index)
        scratch[index] = 0u;
    ag32_fcb_restream_fence();

    uint32_t count = observer(
        sequence, tag, scratch, AG32_HIL_CAMPAIGN_MAX_WORDS);
    if (count > AG32_HIL_CAMPAIGN_MAX_WORDS) {
        ag32_hil_campaign_complete(
            campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_ERROR, 0u,
            AG32_HIL_CAMPAIGN_ERROR_OBSERVER_SIZE);
        return 1u;
    }

    for (index = 0u; index < count; ++index)
        campaign->words[index] = scratch[index];
    ag32_hil_campaign_complete(
        campaign, sequence, tag, AG32_HIL_CAMPAIGN_STATE_DONE, count,
        AG32_HIL_CAMPAIGN_ERROR_NONE);
    return 1u;
}

#endif
