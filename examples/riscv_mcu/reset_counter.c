#include <stdint.h>

#include "ag32.h"

#define RESULT ((volatile uint32_t *)0x20001000u)
#define COUNTER_MAGIC 0x434e5452u /* ASCII "CNTR". */

static inline uint32_t read_pc(void)
{
    uint32_t value;
    __asm__ volatile("auipc %0, 0" : "=r"(value));
    return value;
}

int main(void)
{
    if (RESULT[0] != COUNTER_MAGIC) {
        RESULT[0] = COUNTER_MAGIC;
        RESULT[1] = 0;
    }

    RESULT[1] += 1;
    RESULT[2] = SYSCTL_DEVID;
    RESULT[3] = read_pc();
    __asm__ volatile("fence rw, rw" ::: "memory");
    return 0;
}

