#include "ag32.h"

/*
 * Non-destructive hard-CRC qualification candidate. CRC-32/MPEG-2 uses the
 * block's reset polynomial, initial value, no reflection, and no final XOR.
 */
static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

int main(void) {
    static const uint8_t check[] = "123456789";
    const uint32_t expected = 0x0376E6E7u;

    ag32_crc_configure(
        AG32_CRC32_POLYNOMIAL, UINT32_MAX,
        AG32_CRC_POLYSIZE_32 | AG32_CRC_REVERSE_NONE
    );
    uint32_t result = ag32_crc_bytes(check, sizeof(check) - 1u);

    mailbox[0] = 0x43524330u; /* "CRC0" */
    mailbox[1] = result;
    mailbox[2] = expected;
    mailbox[3] = result == expected ? 0x50415353u : 0x4641494Cu;
    for (;;) { }
}
