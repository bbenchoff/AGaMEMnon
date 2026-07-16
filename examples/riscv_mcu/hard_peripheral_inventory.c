#include "ag32.h"

/*
 * The generated AGM SDK calls these peripheral "instances".  They are hard
 * MCU blocks, not RTL modules.  This program inventories the AG32VF303 digital
 * register map without touching blocks whose clocks or pins may be absent from
 * the currently loaded fabric.  A debugger can inspect catalog[] and result[].
 */
struct peripheral_instance {
    uint32_t base;
    uint16_t count;
    uint16_t stride;
};

enum {
    FCB, WATCHDOG, SPI, GPIO, BASIC_TIMER, ADVANCED_TIMER, UART, CAN, I2C,
    DMA, USB, CRC, ETHERNET_MAC, INSTANCE_FAMILIES
};

static const struct peripheral_instance catalog[INSTANCE_FAMILIES] = {
    [FCB]            = {0x40010000u, 1, 0x0000},
    [WATCHDOG]       = {0x40011000u, 1, 0x0000},
    [SPI]            = {0x40012000u, 2, 0x1000},
    [GPIO]           = {0x40014000u, 10, 0x1000},
    [BASIC_TIMER]    = {0x4001E000u, 2, 0x1000},
    [ADVANCED_TIMER] = {0x40020000u, 5, 0x1000},
    [UART]           = {0x40025000u, 5, 0x1000},
    [CAN]            = {0x4002A000u, 1, 0x0000},
    [I2C]            = {0x4002B000u, 2, 0x1000},
    [DMA]            = {0x41000000u, 1, 0x0000},
    [USB]            = {0x41001000u, 1, 0x0000},
    [CRC]            = {0x41002000u, 1, 0x0000},
    [ETHERNET_MAC]   = {0x41040000u, 1, 0x0000},
};

static volatile uint32_t *const result = (volatile uint32_t *)0x20001000u;

int main(void) {
    uint32_t instances = 0;
    uint32_t hash = 2166136261u;

    for (unsigned i = 0; i < INSTANCE_FAMILIES; ++i) {
        instances += catalog[i].count;
        hash = (hash ^ catalog[i].base) * 16777619u;
        hash = (hash ^ catalog[i].count) * 16777619u;
        hash = (hash ^ catalog[i].stride) * 16777619u;
    }

    result[0] = 0x50455249u; /* "PERI" */
    result[1] = INSTANCE_FAMILIES;
    result[2] = instances;
    result[3] = hash;
    result[4] = SYSCTL_DEVID;
    return 0;
}
