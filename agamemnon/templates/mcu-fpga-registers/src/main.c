#include "ag32.h"

int main(void) {
    volatile uint32_t *result = (volatile uint32_t *)0x20001000u;
    volatile uint32_t *bank = (volatile uint32_t *)AG32_EXT_AHB_BASE;
    result[0] = ag32_fcb_config((const uint32_t *)0x20002000u, 24986u);
    result[1] = bank[0] & 0xffu;
    result[2] = bank[1] & 0xffu;
    bank[1] = 0x5au;
    result[3] = bank[1] & 0xffu;
    bank[1] = 0xa5u;
    result[4] = bank[1] & 0xffu;
    bank[0] = 0u;
    result[5] = bank[0] & 0xffu;
    result[6] = bank[1] & 0xffu;
    result[7] = (
        result[0] == 0x000f0002u && result[1] == 0x4du &&
        result[2] == 0u && result[3] == 0x5au &&
        result[4] == 0xa5u && result[5] == 0x4du &&
        result[6] == 0xa5u
    ) ? 0x50415353u : 0x4641494cu;
    for (;;) { }
}
