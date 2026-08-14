#include "ag32.h"

/*
 * I2C0 master bus scan (address probe).
 *
 * Brings up the hard I2C0 master (OpenCores-style: PRER prescaler =
 * pclk/(5*scl) - 1) and walks the 7-bit address space 0x08..0x77. For each
 * candidate it issues START + address(write) and inspects the status: the core
 * clears TIP when the byte is done and sets RxNACK if no device pulled SDA low
 * for the acknowledge bit. A cleared RxNACK => a device acknowledged. Every
 * probe is closed with a STOP so the bus is always released; nothing is written
 * to any device, so the scan is non-destructive.
 *
 * This needs an intentional fabric route of the I2C0 pads and external SCL/SDA
 * pull-ups to see real acknowledges; with a floating bus every address reads as
 * NACK (or times out), which the mailbox reports honestly. All waits bounded.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 10`):
 *   [0] 0x49324330  "I2C0" tag
 *   [1] init status            (0 = master enabled, <0 = bad clock/index)
 *   [2] devices found          (count of acknowledging addresses)
 *   [3] first address found    (7-bit addr, or 0xffffffff if none)
 *   [4] ACK bitmap addr 0..31  (bit N set => addr N acknowledged)
 *   [5] ACK bitmap addr 32..63
 *   [6] ACK bitmap addr 64..95
 *   [7] ACK bitmap addr 96..127
 *   [8] SYSCTL DEVICE_ID
 *   [9] 0xc0ffee1c  done sentinel
 */

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

#define I2C_SCL_HZ   100000u
#define I2C_TIMEOUT  100000u
#define SCAN_FIRST   0x08u
#define SCAN_LAST    0x77u

static void i2c_stop(void) {
    AG32_I2C0->CR = AG32_I2C_CR_STO;   /* release the bus (driver macros) */
    ag32_i2c_wait(AG32_I2C0, I2C_TIMEOUT);
}

int main(void) {
    mailbox[0] = 0x49324330u;                 /* "I2C0" */

    uint32_t pbus = ag32_pbus_hz(248000000u);
    int init = ag32_i2c_init(AG32_I2C0, pbus, I2C_SCL_HZ);
    mailbox[1] = (uint32_t)init;

    uint32_t bitmap[4] = {0, 0, 0, 0};
    uint32_t found = 0;
    uint32_t first = 0xffffffffu;

    if (init == 0) {
        for (uint32_t addr = SCAN_FIRST; addr <= SCAN_LAST; ++addr) {
            int rc = ag32_i2c_start(AG32_I2C0, (uint8_t)addr, 0, I2C_TIMEOUT);
            i2c_stop();
            if (rc == 0) {                 /* address acknowledged */
                bitmap[addr >> 5] |= (1u << (addr & 31u));
                ++found;
                if (first == 0xffffffffu)
                    first = addr;
            }
        }
    }

    mailbox[2] = found;
    mailbox[3] = first;
    mailbox[4] = bitmap[0];
    mailbox[5] = bitmap[1];
    mailbox[6] = bitmap[2];
    mailbox[7] = bitmap[3];
    mailbox[8] = SYSCTL_DEVID;
    mailbox[9] = 0xc0ffee1cu;

    for (;;) { }
}
