// ag32fun.h — minimal AG32 (AGRV2K) MCU register map + helpers. Direct hardware, no HAL.
//
// This is the memory map CONFIRMED on real silicon during bring-up (RISC-V core misa=0x40801125,
// DEVICE_ID 0x40200001). IMPORTANT: on the AG32 most peripheral base addresses are assigned by the
// FPGA fabric build — the addresses below are the BOOT/DEFAULT fabric's map. If you build your own
// fabric, you decide where peripherals land; remap here to match. The System Control block, the
// FCB, the flash controller, and the flash/SRAM/AHB regions are fixed by the hard silicon.
//
// Deep detail: AG32-Docs/AG32VF303_Bringup.md (§5 memory map) + the disassembled boot ROM.
#ifndef AG32FUN_H
#define AG32FUN_H

#include <stdint.h>

#define REG32(a)   (*(volatile uint32_t *)(uintptr_t)(a))

// ---- fixed silicon regions -------------------------------------------------------------------
#define SRAM_BASE      0x20000000u          // 128 KB SRAM -> top 0x20020000
#define SRAM_TOP       0x20020000u
#define FLASH_BASE     0x80000000u          // 256 KB SPI flash, XIP
#define FLASH_MCU      0x80000000u          //   MCU reset/code lives here
#define FLASH_LOGIC    0x80008100u          //   factory fabric bitstream (compressed) lives here
#define BOOTROM_BASE   0x00010000u          // 8 KB mask boot ROM (serial bootloader + fabric config)
#define EXT_AHB_BASE   0x60000000u          // External-AHB region: the FABRIC is a memory-mapped slave here

// ---- System Control (clock, resets, ID) — fixed at 0x03000000 --------------------------------
#define SYSCTL_BASE    0x03000000u
#define SYSCTL_CLKCTRL REG32(SYSCTL_BASE + 0x0C)   // [1:0] clock source (0=HSI); &~0x27 -> HSI, safe for FCB config
#define SYSCTL_APBCLK  REG32(SYSCTL_BASE + 0x60)   // APB peripheral clock enables (see bits below)
#define SYSCTL_DEVID   REG32(SYSCTL_BASE + 0x100)  // reads 0x40200001 on AGRV2K
#define  APBCLK_FCB    (1u << 0)
#define  APBCLK_GPIO4  (1u << 8)

// ---- FCB: Fabric Configuration Block — fixed at 0x40010000 -----------------------------------
// Streams a fabric bitstream into the config SRAM. This is how you (SRAM-)configure the fabric at
// runtime without touching flash; the boot ROM uses the same block to auto-load from flash at boot.
#define FCB_BASE       0x40010000u
#define FCB_CTRL       REG32(FCB_BASE + 0x00)       // write (1<<6) = AUTO config mode
#define FCB_DATA       REG32(FCB_BASE + 0x0C)       // write each 32-bit config word here
#define FCB_STAT       REG32(FCB_BASE + 0x10)       // 0x000f0002 = configured/accepted; bit ERR_CRC on bad image
#define  FCB_CTRL_AUTO (1u << 6)
#define  FCB_STAT_OK   0x000f0002u

// ---- Flash controller — fixed at 0x40001000 (STM32-style; used to PROGRAM flash) --------------
// For persistent programming; the SRAM-inject path above needs none of this. Unlock, then erase/
// program per the reference. See the `agamemnon` flasher (`agamemnon flash`/`image`).
#define FLASHC_BASE    0x40001000u
#define FLASHC_KEYR    REG32(FLASHC_BASE + 0x04)    // write KEY1 then KEY2 to unlock the control reg
#define FLASHC_OPTKEYR REG32(FLASHC_BASE + 0x08)    // write KEY1 then KEY2 to unlock the option bytes
#define FLASHC_SR      REG32(FLASHC_BASE + 0x10)    // bit7 = CR locked, bit9 = OPT locked
#define  FLASH_KEY1    0x45670123u
#define  FLASH_KEY2    0xCDEF89ABu

// ---- GPIO (default fabric map: GPIO4 @ 0x40018000, Stellaris-style masked data) ---------------
// Data access is address-masked: reading/writing GPIOx_DATA(mask) touches only the bits in `mask`.
#define GPIO4_BASE     0x40018000u
#define GPIO4_DATA(m)  REG32(GPIO4_BASE + ((uint32_t)(m) << 2))  // masked data read/write
#define GPIO4_DIR      REG32(GPIO4_BASE + 0x400)     // 1 = output
#define GPIO4_AFSEL    REG32(GPIO4_BASE + 0x420)     // 0 = software GPIO (not fabric alt-function)

// ---- helpers ---------------------------------------------------------------------------------

// Bring clocks up for runtime fabric configuration: HSI (avoids overrunning the FCB) + enable the
// FCB and GPIO4 APB clocks. Call before fcb_config().
static inline void ag32_clocks_for_config(void) {
    SYSCTL_CLKCTRL &= ~0x27u;
    SYSCTL_APBCLK  |= APBCLK_FCB | APBCLK_GPIO4;
}

// SRAM-inject the fabric: stream `nwords` 32-bit words of an UNCOMPRESSED fabric image (the 99944-B
// AGaMEMnon `*_uncomp.bin`, i.e. 24986 words) into the FCB in AUTO mode. Returns FCB_STAT
// (== FCB_STAT_OK on success). This is the debugger-free way to load + test a bitstream at runtime.
static inline uint32_t ag32_fcb_config(const uint32_t *img, uint32_t nwords) {
    FCB_CTRL = FCB_CTRL_AUTO;
    for (uint32_t i = 0; i < nwords; i++) FCB_DATA = img[i];
    return FCB_STAT;
}

#endif // AG32FUN_H
