#ifndef AGAMEMNON_AG32_SYSCTL_H
#define AGAMEMNON_AG32_SYSCTL_H

#include "ag32_device.h"

#define AG32_SYSCTL_PBUS_DIVIDER AG32_REG32(AG32_SYSCTL_BASE + 0x38u)
#define AG32_SYSCTL_APB_RESET    AG32_REG32(AG32_SYSCTL_BASE + 0x40u)
#define AG32_SYSCTL_AHB_RESET    AG32_REG32(AG32_SYSCTL_BASE + 0x50u)
#define AG32_SYSCTL_APB_ENABLE   AG32_REG32(AG32_SYSCTL_BASE + 0x60u)
#define AG32_SYSCTL_AHB_ENABLE   AG32_REG32(AG32_SYSCTL_BASE + 0x70u)
#define AG32_SYSCTL_APB_DBGSTOP  AG32_REG32(AG32_SYSCTL_BASE + 0x80u)

#define AG32_APB_FCB0       (1u << 0)
#define AG32_APB_WATCHDOG0  (1u << 1)
#define AG32_APB_SPI0       (1u << 2)
#define AG32_APB_SPI1       (1u << 3)
#define AG32_APB_GPIO(n)    (1u << (4u + (uint32_t)(n)))
#define AG32_APB_TIMER(n)   (1u << (14u + (uint32_t)(n)))
#define AG32_APB_GPTIMER(n) (1u << (16u + (uint32_t)(n)))
#define AG32_APB_UART(n)    (1u << (21u + (uint32_t)(n)))
#define AG32_APB_CAN0       (1u << 26)
#define AG32_APB_I2C(n)     (1u << (27u + (uint32_t)(n)))

#define AG32_AHB_DMAC0      (1u << 0)
#define AG32_AHB_USB0       (1u << 1)
#define AG32_AHB_CRC0       (1u << 2)
#define AG32_AHB_MAC0       (1u << 3)

static inline void ag32_apb_enable(uint32_t mask) {
    AG32_SYSCTL_APB_ENABLE |= mask;
}

static inline void ag32_ahb_enable(uint32_t mask) {
    AG32_SYSCTL_AHB_ENABLE |= mask;
}

static inline void ag32_apb_reset(uint32_t mask) {
    AG32_SYSCTL_APB_RESET |= mask;
    AG32_SYSCTL_APB_RESET &= ~mask;
}

static inline void ag32_ahb_reset(uint32_t mask) {
    AG32_SYSCTL_AHB_RESET |= mask;
    AG32_SYSCTL_AHB_RESET &= ~mask;
}

static inline uint32_t ag32_pbus_hz(uint32_t sysclk_hz) {
    return sysclk_hz / ((AG32_SYSCTL_PBUS_DIVIDER & 0x0fu) + 1u);
}

#endif
