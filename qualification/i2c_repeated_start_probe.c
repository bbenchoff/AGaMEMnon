#include "ag32.h"

#define MAILBOX ((volatile uint32_t *)0x20001000u)
#define GPIO_BASE(n)  (AG32_GPIO0_BASE + (uint32_t)(n) * 0x1000u)
#define GPIO_AFSEL(n) AG32_REG32(GPIO_BASE(n) + 0x420u)

int main(void) {
    uint32_t fcb = FCB_STAT;
    if (fcb != FCB_STAT_OK)
        fcb = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
    ag32_apb_enable(AG32_APB_GPIO(3));
    GPIO_AFSEL(3) |= 0x30u;

    MAILBOX[0] = 0x49324352u; /* I2CR */
    MAILBOX[1] = SYSCTL_DEVID;
    MAILBOX[2] = fcb;
    MAILBOX[3] = (uint32_t)ag32_i2c_init(
        AG32_I2C0, ag32_uart_ref_hz_measured(), 100000u);
    MAILBOX[4] = 0x52454144u;
    MAILBOX[5] = 0u;
    while (MAILBOX[5] != 1u) { }

    MAILBOX[6] = (uint32_t)ag32_i2c_start(AG32_I2C0, 0x55u, 0, 200000u);
    MAILBOX[7] = (uint32_t)ag32_i2c_write(AG32_I2C0, 0x2au, 0, 200000u);
    MAILBOX[8] = (uint32_t)ag32_i2c_write(AG32_I2C0, 0xa6u, 0, 200000u);
    MAILBOX[9] = (uint32_t)ag32_i2c_start(AG32_I2C0, 0x55u, 1, 200000u);

    uint8_t values[3] = {0u, 0u, 0u};
    MAILBOX[10] = (uint32_t)ag32_i2c_read(AG32_I2C0, &values[0], 0, 200000u);
    MAILBOX[11] = (uint32_t)ag32_i2c_read(AG32_I2C0, &values[1], 0, 200000u);
    MAILBOX[12] = (uint32_t)ag32_i2c_read(AG32_I2C0, &values[2], 1, 200000u);
    MAILBOX[13] = values[0];
    MAILBOX[14] = values[1];
    MAILBOX[15] = values[2];
    MAILBOX[16] = AG32_I2C0->SR;
    MAILBOX[17] = 0xc0ffee2du;
    for (;;) { }
}
