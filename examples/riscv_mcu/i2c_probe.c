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
 * The PRER solve uses ag32_uart_ref_hz_measured() as an EXPLICIT CROSS-DOMAIN
 * ASSUMPTION: ~14.47 MHz is the measured UART0 reference on this board, I2C0's
 * own reference clock has never been measured, and the clock tree is not uniform
 * (SPI0 measured ~258 MHz in the same configuration). Nothing in the SDK
 * configures the clock tree, and the part's 248 MHz maximum must not be assumed
 * -- doing that for the UART produced a ~17x baud error. The assumed clock and
 * the three clock registers are reported so the achieved SCL can be derived from
 * a scope capture rather than trusted.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 13`):
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
 *  [10] clock assumed for the PRER solve, in Hz (UART domain, unverified)
 *  [11] CLK_CNTL readback (bits[1:0] source, bit4 HSE ready, bit6 PLL ready)
 *  [12] PBUS_DIVIDER<<16 | MTIME_PSC low half
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

    /* Measured UART0 reference, assumed to also clock I2C0. UNVERIFIED. */
    uint32_t assumed_clock = ag32_uart_ref_hz_measured();
    int init = ag32_i2c_init(AG32_I2C0, assumed_clock, I2C_SCL_HZ);
    mailbox[1] = (uint32_t)init;
    mailbox[10] = assumed_clock;
    mailbox[11] = AG32_SYSCTL_CLK_CNTL;
    mailbox[12] = ((AG32_SYSCTL_PBUS_DIVIDER & 0xffffu) << 16) |
                  (AG32_SYSCTL_MTIME_PSC & 0xffffu);

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
