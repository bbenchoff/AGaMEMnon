# AGaMEMnon MCU SDK strategy

AGaMEMnon owns an explicitly open, freestanding MCU layer under
`agamemnon/sdk/`. It is the stable substrate used by generated projects:

- the AG32VF303 digital instance map;
- System Control, FCB, GPIO4, and basic-timer accessors already proven by the
  repository examples;
- complete published PLIC source definitions and compile-tested CLINT/PLIC
  helpers;
- published-register polling drivers for UART, the eight-phase SPI master,
  I2C master, memory-to-memory DMA, the hard CRC calculator, and the
  programmable APB watchdog;
- L48 board names and qualified LED mappings;
- startup and SRAM/native-flash/USB-application linker scripts;
- a direct-mode trap entry plus exception, software-interrupt, timer-interrupt,
  and complete PLIC source definitions;
- direct GCC project builds through `agamemnon build`;
- an optional CMake toolchain for editors and larger applications.

The existing `os-q/framework-agrv_sdk` is useful and substantially more
complete, but commit `3c729cb4745330e8cd1c9aac48c73bdf997fc9b0` does not ship
a top-level license file. AGaMEMnon therefore does **not** copy or redistribute
its drivers. Users may install it independently through the pinned PlatformIO
platform when they have reviewed its provenance and licensing.

The policy is incremental: promote a peripheral into the open AGaMEMnon HAL
only with a documented register source, a host test, and preferably silicon
qualification. Compatibility names may be supplied for migration, but the
unlicensed external framework is not a hidden runtime dependency of the open
SDK.

The same rule applies to the clock tree. The published manual leaves important
source-select/PLL programming details incomplete, so the HAL currently
calculates PBUS rate but does not guess a dynamic clock transition. See
[`docs/MCU_CLOCKS.md`](../docs/MCU_CLOCKS.md).

The polling drivers are in `ag32_uart.h`, `ag32_spi.h`, `ag32_i2c.h`,
`ag32_dma.h`, `ag32_crc.h`, and `ag32_watchdog.h`. Interrupt definitions and
helpers are in `ag32_interrupt.h`.
Their source is the AGM **AG32 MCU Reference Manual revision 1.2**, sections
4 (System Control), 6 (interrupts, CLINT, and PLIC), 9.3 (programmable APB
watchdog), 11 (DMA), 16 (CRC), 18 (UART), 19 (I2C), and 21 (Flash-SPI
control). Struct layouts and all public headers are compiled in the host test
suite. The examples under `examples/riscv_mcu/` include non-destructive
interrupt, exception, CRC, and watchdog programs; the CRC known-answer,
watchdog snapshot/supervised reset, and machine-timer interrupt are
silicon-qualified (`qualification/hard_peripheral_evidence.jsonl`).

Qualification is per controller mode and exact fabric-to-pad route, not per
header. The 2026-08-24 campaign qualifies bounded UART0/1/2 TX, SPI0/1 TX, and
I²C0/I²C1 repeated-START contracts on L48. Typed SPI0/SPI1 MISO is
deliberately refused under `VP-AGM-008` after both open duplex compositions
returned `0xffffffff`; TX-only remains available. The campaign did not qualify
UART RX breadth, generic SPI RX/duplex, broad I²C modes, or other packages.

These drivers configure controller registers; they do not guess fabric pin
routing. SPI and UART signals reach package pins only when the loaded fabric
maps them. I2C additionally requires open-drain routing and external pull-ups.
USB remains integrated through the pinned TinyUSB boundary because a useful
USB stack is much larger than a polling register wrapper.
The fail-closed board and alternate-function rules are specified in
[`docs/MCU_PIN_ROUTING.md`](../docs/MCU_PIN_ROUTING.md).

## CMake

```powershell
cmake -S . -B build `
  -DCMAKE_TOOLCHAIN_FILE=C:/path/to/AGaMEMnon/sdk/cmake/ag32-riscv.cmake
cmake --build build
```

Generated projects use the same compiler flags directly, so CMake is optional.
The compiler is resolved from `PATH`, `RISCV_PREFIX`, or PlatformIO's
`toolchain-agrv` installation.

## Full AGM PlatformIO framework

The external integration pins:

- `os-q/platform-agm32` at `71f4c316c849c3e6b117b4830330360bbd61359b`
- `os-q/framework-agrv_sdk` at `3c729cb4745330e8cd1c9aac48c73bdf997fc9b0`
- `os-q/framework-agrv_tinyusb` at `031adf292bdc967a6b5edd800f153b6480f5a4b0`

These pins are recorded in `tools/bundle/manifest.json`. The `usb-cdc`
project template shows the external PlatformIO boundary and points to the
qualified patches rather than silently downloading mutable upstream heads.
