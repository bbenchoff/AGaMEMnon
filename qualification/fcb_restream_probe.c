#include "ag32_fcb_restream.h"

/*
 * SRAM-only, mailbox-driven FCB restream firmware.
 *
 * A host loads this firmware once at 0x20000000, waits for READY at
 * 0x20001000, stages each exact 99,944-byte image at 0x20002000 while the MCU
 * is halted, and publishes a fresh request sequence last.  No flash path is
 * present.  Consecutive-image behavior remains hardware-unqualified until an
 * explicitly approved SRAM-only trial records silicon evidence.
 */

int main(void) {
    volatile ag32_fcb_restream_mailbox_t *const mailbox =
        (volatile ag32_fcb_restream_mailbox_t *)
            AG32_FCB_RESTREAM_MAILBOX_ADDRESS;
    const uint32_t *const image =
        (const uint32_t *)AG32_FCB_RESTREAM_IMAGE_ADDRESS;
    uint32_t fault_latched = 0u;

    ag32_fcb_restream_init(mailbox);
    for (;;)
        (void)ag32_fcb_restream_service(mailbox, image, &fault_latched);
}
