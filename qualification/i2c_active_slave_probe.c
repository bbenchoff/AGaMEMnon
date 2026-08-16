#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

int main(void) {
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    ag32_apb_enable(AG32_APB_GPIO(3));
    GPIO_AFSEL(3) |= 0x30u; /* I2C0 SCL + SDA */

    MAILBOX[0] = 0x49324341u; /* I2CA */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[3] = (uint32_t)ag32_i2c_init(
        AG32_I2C0, ag32_uart_ref_hz_measured(), 100000u);
    MAILBOX[4] = 0x52454144u;
    MAILBOX[5] = 0u;
    while (MAILBOX[5] != 1u) { }

    MAILBOX[6] = (uint32_t)ag32_i2c_start(AG32_I2C0, 0x55u, 0, 200000u);
    MAILBOX[7] = (uint32_t)ag32_i2c_write(AG32_I2C0, 0xa6u, 1, 200000u);
    for (volatile unsigned delay = 0; delay < 10000u; ++delay) { }
    MAILBOX[8] = (uint32_t)ag32_i2c_start(AG32_I2C0, 0x55u, 1, 200000u);
    uint8_t value = 0u;
    MAILBOX[9] = (uint32_t)ag32_i2c_read(AG32_I2C0, &value, 1, 200000u);
    MAILBOX[10] = value;
    MAILBOX[11] = AG32_I2C0->SR;
    MAILBOX[12] = 0xc0ffee2cu;
    MAILBOX[13] = AG32_I2C0->RXR;
    for (;;) { }
}
