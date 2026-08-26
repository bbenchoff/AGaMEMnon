#include "ag32_hil_campaign.h"

/*
 * Minimal production-cadence observer for the retained constant AHB endpoint.
 * The host loads this firmware once, restreams exact images, and classifies the
 * direct AHB word recorded after each successful FCB configuration.
 */

static uint32_t observe(
        uint32_t sequence, uint32_t image_tag,
        volatile uint32_t *words, uint32_t capacity) {
    volatile const uint32_t *const ahb =
        (volatile const uint32_t *)0x60000000u;
    (void)sequence;
    (void)image_tag;
    if (capacity < 1u)
        return capacity + 1u;
    words[0] = ahb[0];
    return 1u;
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

    ag32_fcb_restream_init(restream);
    ag32_hil_campaign_init(campaign);
    for (;;)
        (void)ag32_hil_campaign_service(
            restream, campaign, image, &fault_latched, observe);
}
