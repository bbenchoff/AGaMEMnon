#ifndef AGAMEMNON_AG32_CAN_H
#define AGAMEMNON_AG32_CAN_H

/*
 * Open AG32 CAN 2.0 (CAN0) driver, written from the published register map.
 * The controller is an SJA1000/PeliCAN-style core with two register
 * personalities: registers such as the bit-timing and acceptance filters are
 * only writable while the MOD.RESET (reset) mode is set; the transmit and
 * receive frame windows are only meaningful in operating mode. This driver
 * re-implements the documented behaviour; no vendor code is copied.
 *
 * A real CAN transceiver is required to move traffic on a bus; the driver
 * itself is transport-agnostic and supports self-test/loopback bring-up.
 */

#include <stdint.h>

#include "ag32_device.h"
#include "ag32_sysctl.h"

typedef struct {
    volatile uint32_t MOD;              /* 0x00 mode                       */
    volatile uint32_t CMR;              /* 0x04 command (write-only)       */
    volatile const uint32_t SR;         /* 0x08 status                     */
    volatile const uint32_t IR;         /* 0x0c interrupt (read clears)    */
    volatile uint32_t IER;              /* 0x10 interrupt enable           */
    uint32_t reserved_14;
    volatile uint32_t BTR0;             /* 0x18 bus timing 0               */
    volatile uint32_t BTR1;             /* 0x1c bus timing 1               */
    volatile uint32_t OCR;              /* 0x20 output control             */
    uint32_t reserved_24[2];
    volatile const uint32_t ALC;        /* 0x2c arbitration-lost capture   */
    volatile const uint32_t ECC;        /* 0x30 error-code capture         */
    volatile uint32_t EWLR;             /* 0x34 error-warning limit        */
    volatile uint32_t RXERR;            /* 0x38 receive error counter      */
    volatile uint32_t TXERR;            /* 0x3c transmit error counter     */
    union {                             /* 0x40..0x70 shared 13-word window */
        volatile uint32_t FRAME[13];    /* [0]=frame info, [1..]=id+data   */
        struct {
            volatile uint32_t ACR[4];   /* 0x40 acceptance code            */
            volatile uint32_t AMR[4];   /* 0x50 acceptance mask            */
        } filter;
    };
    volatile const uint32_t RMC;        /* 0x74 receive message counter    */
    volatile uint32_t RBSA;             /* 0x78 receive buffer start addr  */
    uint32_t reserved_7c;
    volatile uint32_t RXFIFO[64];       /* 0x80..0x17c                     */
    volatile const uint32_t TXBUF[13];  /* 0x180..0x1b0 read-back window   */
} ag32_can_t;

#define AG32_CAN0 ((ag32_can_t *)(uintptr_t)AG32_CAN0_BASE)

/* MOD */
#define AG32_CAN_MOD_RESET    (1u << 0)
#define AG32_CAN_MOD_LISTEN   (1u << 1)  /* listen-only               */
#define AG32_CAN_MOD_SELFTEST (1u << 2)  /* self-test (no ack needed) */
#define AG32_CAN_MOD_AFM      (1u << 3)  /* single acceptance filter  */
#define AG32_CAN_MOD_SLEEP    (1u << 4)

/* CMR */
#define AG32_CAN_CMR_TR   (1u << 0)  /* transmission request          */
#define AG32_CAN_CMR_AT   (1u << 1)  /* abort transmission            */
#define AG32_CAN_CMR_RRB  (1u << 2)  /* release receive buffer        */
#define AG32_CAN_CMR_CDO  (1u << 3)  /* clear data overrun            */
#define AG32_CAN_CMR_SRR  (1u << 4)  /* self reception request        */

/* SR */
#define AG32_CAN_SR_RBS  (1u << 0)  /* receive buffer status         */
#define AG32_CAN_SR_DOS  (1u << 1)  /* data overrun                  */
#define AG32_CAN_SR_TBS  (1u << 2)  /* transmit buffer released      */
#define AG32_CAN_SR_TCS  (1u << 3)  /* transmission complete         */
#define AG32_CAN_SR_RS   (1u << 4)  /* receiving                     */
#define AG32_CAN_SR_TS   (1u << 5)  /* transmitting                  */
#define AG32_CAN_SR_ES   (1u << 6)  /* error                         */
#define AG32_CAN_SR_BS   (1u << 7)  /* bus-off                       */

/* IR / IER share the same bit positions. */
#define AG32_CAN_INT_RX  (1u << 0)
#define AG32_CAN_INT_TX  (1u << 1)
#define AG32_CAN_INT_ERR (1u << 2)
#define AG32_CAN_INT_DO  (1u << 3)
#define AG32_CAN_INT_WU  (1u << 4)
#define AG32_CAN_INT_EP  (1u << 5)
#define AG32_CAN_INT_AL  (1u << 6)
#define AG32_CAN_INT_BE  (1u << 7)

/* BTR0: BRP[5:0], SJW[7:6]. BTR1: TSEG1[3:0], TSEG2[6:4], SAM[7]. */
#define AG32_CAN_BTR0(brp, sjw) (((uint32_t)(brp) & 0x3fu) | (((uint32_t)(sjw) & 3u) << 6))
#define AG32_CAN_BTR1(tseg1, tseg2, sam) \
    (((uint32_t)(tseg1) & 0xfu) | (((uint32_t)(tseg2) & 7u) << 4) | \
     (((uint32_t)(sam) & 1u) << 7))

/* Frame-info byte fields in FRAME[0]. */
#define AG32_CAN_FRAME_FF   (1u << 7)  /* 1 = extended (29-bit) id      */
#define AG32_CAN_FRAME_RTR  (1u << 6)  /* remote frame                  */
#define AG32_CAN_FRAME_DLC  0x0fu

/* Push-pull normal output driver. */
#define AG32_CAN_OCR_NORMAL 0x1au

static inline void ag32_can_reset_mode(ag32_can_t *can, int enable) {
    if (enable)
        can->MOD |= AG32_CAN_MOD_RESET;
    else
        can->MOD &= ~AG32_CAN_MOD_RESET;
}

/*
 * Enter reset mode, program bit timing and an accept-all filter, then return
 * to operating mode. btr0/btr1 come from AG32_CAN_BTR0()/AG32_CAN_BTR1() (or a
 * measured pair). mode_bits may add AG32_CAN_MOD_LISTEN or _SELFTEST for
 * transceiver-free bring-up.
 */
static inline int ag32_can_init(ag32_can_t *can, uint32_t btr0, uint32_t btr1,
                                uint32_t mode_bits) {
    ag32_apb_enable(AG32_APB_CAN0);
    ag32_apb_reset(AG32_APB_CAN0);
    can->MOD = AG32_CAN_MOD_RESET | AG32_CAN_MOD_AFM | mode_bits;
    can->BTR0 = btr0;
    can->BTR1 = btr1;
    can->OCR = AG32_CAN_OCR_NORMAL;
    for (unsigned i = 0; i < 4u; ++i) {
        can->filter.ACR[i] = 0u;      /* code irrelevant with */
        can->filter.AMR[i] = 0xffu;   /* an all-ones mask (accept all) */
    }
    can->IER = 0u;
    can->MOD = (mode_bits | AG32_CAN_MOD_AFM); /* clear RESET -> operating */
    return 0;
}

/*
 * Transmit one standard (11-bit) data frame. dlc is 0..8. Waits (bounded) for
 * the transmit buffer to be free, loads the frame window, and issues a
 * transmission request. Returns 0, -1 on bad argument, -2 on timeout.
 */
static inline int ag32_can_transmit(ag32_can_t *can, uint32_t id,
                                    const uint8_t *data, unsigned dlc,
                                    uint32_t timeout) {
    if (dlc > 8u || id > 0x7ffu)
        return -1;
    while (!(can->SR & AG32_CAN_SR_TBS)) {
        if (!timeout--)
            return -2;
    }
    can->FRAME[0] = dlc & AG32_CAN_FRAME_DLC;      /* FF=0, RTR=0 */
    can->FRAME[1] = (id >> 3) & 0xffu;             /* id[10:3]    */
    can->FRAME[2] = (id << 5) & 0xe0u;             /* id[2:0]     */
    for (unsigned i = 0; i < dlc; ++i)
        can->FRAME[3 + i] = data[i];
    can->CMR = AG32_CAN_CMR_TR;
    return 0;
}

/*
 * Receive one standard data frame from the receive buffer. Waits (bounded) for
 * a buffered message, copies up to 8 data bytes, releases the buffer, and
 * returns the data length (0..8), -2 on timeout. id_out may be NULL.
 */
static inline int ag32_can_receive(ag32_can_t *can, uint32_t *id_out,
                                   uint8_t *data, uint32_t timeout) {
    while (!(can->SR & AG32_CAN_SR_RBS)) {
        if (!timeout--)
            return -2;
    }
    uint32_t info = can->FRAME[0];
    unsigned dlc = info & AG32_CAN_FRAME_DLC;
    if (dlc > 8u)
        dlc = 8u;
    if (id_out)
        *id_out = ((can->FRAME[1] & 0xffu) << 3) | ((can->FRAME[2] >> 5) & 7u);
    if (data)
        for (unsigned i = 0; i < dlc; ++i)
            data[i] = (uint8_t)can->FRAME[3 + i];
    can->CMR = AG32_CAN_CMR_RRB;
    return (int)dlc;
}

static inline uint32_t ag32_can_status(const ag32_can_t *can) { return can->SR; }
static inline int ag32_can_bus_off(const ag32_can_t *can) {
    return (can->SR & AG32_CAN_SR_BS) ? 1 : 0;
}
static inline uint32_t ag32_can_rx_error_count(const ag32_can_t *can) {
    return can->RXERR;
}
static inline uint32_t ag32_can_tx_error_count(const ag32_can_t *can) {
    return can->TXERR;
}

#endif /* AGAMEMNON_AG32_CAN_H */
