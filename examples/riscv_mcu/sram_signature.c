#include <stdint.h>

#include "ag32.h"

#define RESULT ((volatile uint32_t *)0x20001000u)

static inline uint32_t read_misa(void)
{
    uint32_t value;
    __asm__ volatile("csrr %0, misa" : "=r"(value));
    return value;
}

static inline uint32_t read_pc(void)
{
    uint32_t value;
    __asm__ volatile("auipc %0, 0" : "=r"(value));
    return value;
}

int main(void)
{
    RESULT[0] = 0x52563332u; /* ASCII "RV32". */
    RESULT[1] = SYSCTL_DEVID;
    RESULT[2] = read_misa();
    RESULT[3] = read_pc();
    __asm__ volatile("fence rw, rw" ::: "memory");
    return 0;
}

