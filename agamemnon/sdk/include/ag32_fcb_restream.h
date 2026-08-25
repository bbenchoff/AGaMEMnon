#ifndef AG32_FCB_RESTREAM_H
#define AG32_FCB_RESTREAM_H

/*
 * Mailbox protocol for reusing one SRAM-resident MCU firmware while a host
 * stages successive full fabric images at 0x20002000.
 *
 * This composes the silicon-qualified ag32_fcb_config() AUTO stream.  It does
 * One exact A/B/A composition is silicon-qualified: the retained constant AHB
 * endpoint, a route-identical constant-zero LUT variant, then the retained
 * endpoint again.  Arbitrary consecutive images remain unqualified.  A failed
 * FCB status latches until MCU reset, and all malformed requests are refused
 * before the FCB is touched.
 */

#include <stdint.h>

#include "ag32.h"

#define AG32_FCB_RESTREAM_MAILBOX_ADDRESS 0x20001000u
#define AG32_FCB_RESTREAM_IMAGE_ADDRESS   0x20002000u
#define AG32_FCB_RESTREAM_IMAGE_BYTES     99944u
#define AG32_FCB_RESTREAM_IMAGE_WORDS     24986u

#define AG32_FCB_RESTREAM_MAGIC           0x46434252u /* "FCBR" */
#define AG32_FCB_RESTREAM_VERSION         1u
#define AG32_FCB_RESTREAM_SENTINEL        0xc0ffee46u

#define AG32_FCB_RESTREAM_STATE_READY     1u
#define AG32_FCB_RESTREAM_STATE_BUSY      2u
#define AG32_FCB_RESTREAM_STATE_DONE      3u
#define AG32_FCB_RESTREAM_STATE_ERROR     4u
#define AG32_FCB_RESTREAM_STATE_REJECTED  5u

#define AG32_FCB_RESTREAM_COMMAND_CONFIGURE 1u

#define AG32_FCB_RESTREAM_RESULT_NONE          0u
#define AG32_FCB_RESTREAM_RESULT_OK            1u
#define AG32_FCB_RESTREAM_RESULT_BAD_COMMAND   2u
#define AG32_FCB_RESTREAM_RESULT_BAD_LENGTH    3u
#define AG32_FCB_RESTREAM_RESULT_BAD_ADDRESS   4u
#define AG32_FCB_RESTREAM_RESULT_FCB_STATUS    5u
#define AG32_FCB_RESTREAM_RESULT_FAULT_LATCHED 6u

typedef struct {
    volatile uint32_t magic;             /*  0: firmware writes last when ready */
    volatile uint32_t version;           /*  1: protocol version */
    volatile uint32_t state;             /*  2: READY/BUSY/DONE/ERROR/REJECTED */
    volatile uint32_t request_sequence;  /*  3: host writes last; zero is idle */
    volatile uint32_t command;           /*  4: CONFIGURE */
    volatile uint32_t image_words;       /*  5: must be exactly 24986 */
    volatile uint32_t image_tag;         /*  6: host label; echoed, not trusted */
    volatile uint32_t result_sequence;   /*  7: firmware writes last on complete */
    volatile uint32_t result_code;       /*  8: AG32_FCB_RESTREAM_RESULT_* */
    volatile uint32_t fcb_status;        /*  9: exact FCB_STAT observation */
    volatile uint32_t result_tag;        /* 10: snapshot of request image_tag */
    volatile uint32_t attempts;          /* 11: every distinct nonzero request */
    volatile uint32_t successes;         /* 12: exact FCB_STAT_OK results */
    volatile uint32_t rejected;          /* 13: malformed or latched requests */
    volatile uint32_t reserved;          /* 14: must remain zero */
    volatile uint32_t sentinel;          /* 15: fixed protocol sentinel */
} ag32_fcb_restream_mailbox_t;

_Static_assert(sizeof(ag32_fcb_restream_mailbox_t) == 16u * sizeof(uint32_t),
               "FCB restream mailbox must be exactly 16 words");

static inline void ag32_fcb_restream_fence(void) {
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
}

static inline void ag32_fcb_restream_init(
        volatile ag32_fcb_restream_mailbox_t *mailbox) {
    mailbox->magic = 0u;
    mailbox->version = AG32_FCB_RESTREAM_VERSION;
    mailbox->state = AG32_FCB_RESTREAM_STATE_READY;
    mailbox->request_sequence = 0u;
    mailbox->command = 0u;
    mailbox->image_words = 0u;
    mailbox->image_tag = 0u;
    mailbox->result_sequence = 0u;
    mailbox->result_code = AG32_FCB_RESTREAM_RESULT_NONE;
    mailbox->fcb_status = FCB_STAT;
    mailbox->result_tag = 0u;
    mailbox->attempts = 0u;
    mailbox->successes = 0u;
    mailbox->rejected = 0u;
    mailbox->reserved = 0u;
    mailbox->sentinel = AG32_FCB_RESTREAM_SENTINEL;
    ag32_fcb_restream_fence();
    mailbox->magic = AG32_FCB_RESTREAM_MAGIC;
}

static inline void ag32_fcb_restream_complete(
        volatile ag32_fcb_restream_mailbox_t *mailbox,
        uint32_t sequence, uint32_t tag, uint32_t state,
        uint32_t result, uint32_t fcb_status) {
    mailbox->result_code = result;
    mailbox->fcb_status = fcb_status;
    mailbox->result_tag = tag;
    mailbox->state = state;
    ag32_fcb_restream_fence();
    /* The host treats this echo as the only completion publication. */
    mailbox->result_sequence = sequence;
}

/*
 * Service at most one new request.  fault_latched is private firmware state,
 * not a mailbox bit a host can clear.  Return one when a request was handled.
 */
static inline uint32_t ag32_fcb_restream_service(
        volatile ag32_fcb_restream_mailbox_t *mailbox,
        const uint32_t *image, uint32_t *fault_latched) {
    uint32_t sequence = mailbox->request_sequence;
    if (sequence == 0u || sequence == mailbox->result_sequence)
        return 0u;

    uint32_t command = mailbox->command;
    uint32_t words = mailbox->image_words;
    uint32_t tag = mailbox->image_tag;
    mailbox->state = AG32_FCB_RESTREAM_STATE_BUSY;
    mailbox->attempts += 1u;
    ag32_fcb_restream_fence();

    if (*fault_latched != 0u) {
        mailbox->rejected += 1u;
        ag32_fcb_restream_complete(
            mailbox, sequence, tag, AG32_FCB_RESTREAM_STATE_REJECTED,
            AG32_FCB_RESTREAM_RESULT_FAULT_LATCHED, FCB_STAT);
        return 1u;
    }
    if (command != AG32_FCB_RESTREAM_COMMAND_CONFIGURE) {
        mailbox->rejected += 1u;
        ag32_fcb_restream_complete(
            mailbox, sequence, tag, AG32_FCB_RESTREAM_STATE_REJECTED,
            AG32_FCB_RESTREAM_RESULT_BAD_COMMAND, FCB_STAT);
        return 1u;
    }
    if (words != AG32_FCB_RESTREAM_IMAGE_WORDS) {
        mailbox->rejected += 1u;
        ag32_fcb_restream_complete(
            mailbox, sequence, tag, AG32_FCB_RESTREAM_STATE_REJECTED,
            AG32_FCB_RESTREAM_RESULT_BAD_LENGTH, FCB_STAT);
        return 1u;
    }
    if ((uintptr_t)image != AG32_FCB_RESTREAM_IMAGE_ADDRESS) {
        mailbox->rejected += 1u;
        ag32_fcb_restream_complete(
            mailbox, sequence, tag, AG32_FCB_RESTREAM_STATE_REJECTED,
            AG32_FCB_RESTREAM_RESULT_BAD_ADDRESS, FCB_STAT);
        return 1u;
    }

    uint32_t status = ag32_fcb_config(image, words);
    if (status != FCB_STAT_OK) {
        *fault_latched = 1u;
        ag32_fcb_restream_complete(
            mailbox, sequence, tag, AG32_FCB_RESTREAM_STATE_ERROR,
            AG32_FCB_RESTREAM_RESULT_FCB_STATUS, status);
        return 1u;
    }

    mailbox->successes += 1u;
    ag32_fcb_restream_complete(
        mailbox, sequence, tag, AG32_FCB_RESTREAM_STATE_DONE,
        AG32_FCB_RESTREAM_RESULT_OK, status);
    return 1u;
}

#endif
