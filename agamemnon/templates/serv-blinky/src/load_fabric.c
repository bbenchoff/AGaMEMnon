#include "ag32.h"

int main(void) {
    volatile uint32_t *result = (volatile uint32_t *)0x20001000u;
    result[0] = ag32_fcb_config((const uint32_t *)0x20002000u, 24986u);
    for (;;) { }
}
