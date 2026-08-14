#include "ag32.h"

/*
 * CAN0 self-test (internal loopback) known-answer test.
 *
 * The AG32 CAN core is an SJA1000/PeliCAN-class controller. In self-test mode
 * (MOD.SELFTEST) a node can complete a transmission with no bus acknowledgement
 * and, when the transfer is launched with the Self-Reception Request command
 * (CMR.SRR) instead of a normal Transmission Request, it also stores the frame
 * into its own receive buffer. That lets us prove the whole TX -> RX datapath
 * with no CAN transceiver and no wiring on the bench.
 *
 * The demo brings CAN0 up in self-test mode, loads a fixed standard (11-bit)
 * data frame into the shared transmit window, issues SRR, then reads the frame
 * back through the open receive driver and compares id + payload. Bit timing is
 * derived for ~500 kbit/s from the measured APB clock; exact timing is not
 * critical for an internal loopback but is programmed for realism. A real bus
 * still needs an external transceiver -- that path is documented, not run here.
 * All waits are bounded, so an absent/By held-reset core reports a negative.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 10`):
 *   [0] 0x43414e30  "CAN0" tag
 *   [1] init status              (0 = operating in self-test mode)
 *   [2] SR after init            (TBS set => transmit buffer free)
 *   [3] 0x50415353 "PASS" / 0x4641494c "FAIL" (id + payload matched)
 *   [4] received DLC             (>=0 = data length, <0 = rx timeout code)
 *   [5] received id
 *   [6] rx data bytes 0..3       (byte0 in the high lane)
 *   [7] rx data bytes 4..7
 *   [8] TXERR<<16 | RXERR        (error counters, expect 0/0)
 *   [9] SYSCTL DEVICE_ID
 */

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

#define CAN_ID       0x123u
#define CAN_DLC      8u
#define CAN_BAUD     500000u
#define CAN_TSEG1    5u          /* 6 TQ (field = value-1)             */
#define CAN_TSEG2    2u          /* 3 TQ                               */
#define CAN_BIT_TQ   (1u + (CAN_TSEG1 + 1u) + (CAN_TSEG2 + 1u)) /* = 10 */
#define CAN_TIMEOUT  200000u

static const uint8_t tx_frame[CAN_DLC] = {
    0x11u, 0x22u, 0x33u, 0x44u, 0x55u, 0x66u, 0x77u, 0x88u
};

int main(void) {
    mailbox[0] = 0x43414e30u;                 /* "CAN0" */

    uint32_t pbus = ag32_pbus_hz(248000000u);
    /* t_scl = 2*(BRP+1)/pbus, bit time = CAN_BIT_TQ * t_scl. */
    uint32_t brp = pbus / (2u * CAN_BAUD * CAN_BIT_TQ);
    if (brp) brp -= 1u;
    if (brp > 0x3fu) brp = 0x3fu;

    int init = ag32_can_init(AG32_CAN0,
                             AG32_CAN_BTR0(brp, 0u),
                             AG32_CAN_BTR1(CAN_TSEG1, CAN_TSEG2, 0u),
                             AG32_CAN_MOD_SELFTEST);
    mailbox[1] = (uint32_t)init;
    mailbox[2] = ag32_can_status(AG32_CAN0);

    /*
     * Load the fixed standard data frame and request self-reception. The
     * frame window layout (info byte, id[10:3], id[2:0], data...) is the
     * documented PeliCAN transmit buffer; SRR both transmits and self-receives.
     */
    AG32_CAN0->FRAME[0] = CAN_DLC & AG32_CAN_FRAME_DLC;   /* FF=0 RTR=0 */
    AG32_CAN0->FRAME[1] = (CAN_ID >> 3) & 0xffu;
    AG32_CAN0->FRAME[2] = (CAN_ID << 5) & 0xe0u;
    for (unsigned i = 0; i < CAN_DLC; ++i)
        AG32_CAN0->FRAME[3 + i] = tx_frame[i];
    AG32_CAN0->CMR = AG32_CAN_CMR_SRR;

    uint32_t rx_id = 0;
    uint8_t rx[8] = {0};
    int dlc = ag32_can_receive(AG32_CAN0, &rx_id, rx, CAN_TIMEOUT);

    uint32_t match = (dlc == (int)CAN_DLC) && (rx_id == CAN_ID);
    for (int i = 0; i < dlc && i < (int)CAN_DLC; ++i)
        if (rx[i] != tx_frame[i])
            match = 0;

    mailbox[3] = match ? 0x50415353u : 0x4641494cu; /* "PASS" / "FAIL" */
    mailbox[4] = (uint32_t)dlc;
    mailbox[5] = rx_id;
    mailbox[6] = ((uint32_t)rx[0] << 24) | ((uint32_t)rx[1] << 16) |
                 ((uint32_t)rx[2] << 8) | rx[3];
    mailbox[7] = ((uint32_t)rx[4] << 24) | ((uint32_t)rx[5] << 16) |
                 ((uint32_t)rx[6] << 8) | rx[7];
    mailbox[8] = (ag32_can_tx_error_count(AG32_CAN0) << 16) |
                 (ag32_can_rx_error_count(AG32_CAN0) & 0xffffu);
    mailbox[9] = SYSCTL_DEVID;

    for (;;) { }
}
