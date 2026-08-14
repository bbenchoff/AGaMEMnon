# Introduction to the AG32

The AGM AG32 is a RISC-V microcontroller and a small FPGA in one package. The
MCU runs ordinary firmware and owns hard peripherals; the programmable fabric
can implement independent logic, route peripheral signals, or appear as
memory-mapped hardware beside the CPU.

This page separates the device itself from what AGaMEMnon currently supports.
For exact toolchain claims, use the [support matrix](STATUS.md). For recorded
silicon results, use [hardware qualification](HARDWARE_VALIDATION.md).

## Mental model


```mermaid
flowchart LR
    FW["RISC-V firmware"] --> MCU["RV32IMAFC MCU"]

    MCU <--> AHB["AHB matrix"]

    AHB <--> AHBP["AHB peripherals<br/>USB OTG · CRC · RCU · flash · SRAM"]
    AHB <--> APB["AHB-to-APB bridge"]
    APB <--> HARD["Hard peripherals<br/>UART · SPI · I²C · CAN · timers · RTC<br/>watchdogs · ADC · DAC · comparator · GPIO"]

    RTL["Your Verilog"] --> FLOW["Yosys → nextpnr → AGaMEMnon bitgen"]
    FLOW --> FABRIC["AGRV2K FPGA fabric<br/>LUTs · FFs · BRAM · routing"]

    AHB <--> PORTS["FPGA AHB<br/>slave + master ports"]
    PORTS <--> FABRIC

    HARD <--> PINS["Package pins"]
    FABRIC <--> PINS

    classDef firmware fill:#2563eb,stroke:#1e40af,color:#fff
    classDef mcu fill:#0f766e,stroke:#115e59,color:#fff
    classDef fabric fill:#7c3aed,stroke:#5b21b6,color:#fff
    classDef tools fill:#c2410c,stroke:#9a3412,color:#fff
    classDef physical fill:#475569,stroke:#334155,color:#fff

    class FW firmware
    class MCU,AHB,AHBP,APB,HARD mcu
    class RTL,FLOW tools
    class PORTS,FABRIC fabric
    class PINS physical
```

The fabric is not a software-configurable GPIO matrix. It is programmable
logic with placement, routing, clocks, and a bitstream. That distinction is
what permits state machines, protocol glue, soft peripherals, custom
memory-mapped registers, and even small soft CPUs.

## Names you will encounter

| Name | Meaning in this repository |
|---|---|
| AG32 | AGM's MCU-plus-programmable-logic product family |
| AG32VF303CCT6 | The LQFP-48 package used in development and testing of this SDK. |
| AGRV2K | The programmable-logic architecture/device family name used by vendor files and AGaMEMnon |
| AGRV2KL48 | The LQFP-48 fabric target used for physical pin routing and current hardware qualification |
| AGaMEMnon | This open SDK, documentation set, FPGA flow, project model, and programmer |

`L48`, `L64`, `L100`, and `Q32` are package variants, QFN-32 to LQFP-100.
AGaMEMnon ships separate legality and physical bond maps for all four. L48 has
exact cross-checks and bench evidence; the Q32, L64, and L100 maps are recovered
from architecture metadata and remain explicitly unqualified on hardware.

## Current reference hardware

The qualified target is the **AG32VF303CCT6 LQFP-48 development board** with
`AGRV2KL48` fabric. The checked-in board definition records:

- 256 KiB main flash and 128 KiB SRAM;
- an 8 MHz HSE input used by the qualified fabric PLL configurations;
- four MCU-visible board LEDs on the vendor-default `GPIO4[1:4]` routes;
- four directly qualified fabric LED pads on package pins 25 through 28;
- DAP, flash-resident USB CDC, and mask-ROM UART transport properties.

The official board page also describes a 50 MHz active FPGA oscillator, an
8 MHz MCU crystal, RTC clocking, buttons, LEDs, flash, USB, and expansion
headers. A board clock being present does not by itself make every clock path
supported by AGaMEMnon.

See the machine-readable
[board definition](../agamemnon/sdk/boards/ag32vf303-l48.toml) and the
[qualification fixture wiring](HARDWARE_VALIDATION.md).

## What the open flow can do

AGaMEMnon's FPGA path is:

```text
Verilog
  -> Yosys technology mapping
  -> nextpnr AGRV2K pack/place/route
  -> AGaMEMnon strict bit generation
  -> volatile SRAM image or compressed flash image
```

The MCU path provides freestanding startup, linker scripts, register headers,
an incremental open HAL, project templates, and RISC-V GCC builds. A project
can contain MCU sources and multiple Verilog sources, with an explicit top
module, PCF, clocks, linker, board, outputs, and flash layout.

Useful starting points:

| Intent | Start with |
|---|---|
| Learn the MCU | `agamemnon new hello --template mcu-blink` |
| Learn the fabric | `agamemnon new hello --template fpga-io` |
| Connect MCU firmware to custom logic | `agamemnon new hello --template mcu-fpga` |
| Build the qualified constant AHB endpoint | `examples/designs/mcu_ahb_constant_slave.v` |
| Route or create serial logic | `agamemnon new hello --template uart` or `examples/serial_mux/` |
| Inspect every demonstrated peripheral boundary | [Peripheral examples](PERIPHERAL_EXAMPLES.md) |
| Route MCU peripherals to pins safely | [MCU pin-routing policy](MCU_PIN_ROUTING.md) |
| Understand the recovered architecture | [Architecture](ARCHITECTURE.md) |

The strict open flow now routes all 32 External-AHB read-data outputs together
with independent ready/OKAY response sources. The qualified combinational
endpoint returns `0x4147414d` and accepts no-effect writes on L48. Separate
oracles qualify distinct HADDR[3]/HADDR[5] logic ingress, four direct-D sites,
an eight-state counter, and a 16-bit LFSR under the default External-AHB bus
clock. Timer correlation measures that default clock at exactly one bus clock
per undivided MTIME tick; the absolute rate, long reported as 10 MHz on the
assumption that MTIME ran at the nominal HSI rate, is an
[open question](MCU_CLOCKS.md#external-ahb-bus-clock) now that MTIME has been
measured at 14.08 MHz. A strict combined register-bank image
qualifies ID/scratch/counter/W1C behavior, and a second image integrates the
GPIO4.1-fed synchronous reset with all state classes. Neither qualifies hard
`MCU_RESETN`; see
[MCU External AHB](MCU_AHB_REGISTER_BANK.md).

## Boot and programming paths

| Transport | Works on untouched board | Recovery when main flash is bad | Extra hardware |
|---|---|---|---|
| SWD/DAP | Yes, with AGaMEMnon's qualified OpenOCD | Yes | CMSIS-DAP probe |
| Flash-resident USB CDC uploader | No; install it first | No | USB cable only after installation |
| UART0 mask ROM through Pico | The ROM supports it, but the present board harness does not expose every needed signal | Yes | Pico 2 and the documented five-wire board addition |

The AG32 USB connector does not imply a factory USB bootloader. AGaMEMnon's
qualified USB transport is an application installed in main flash. The
flash-independent recovery path discovered so far is the UART0 mask ROM with
`BOOT0=1` and `BOOT1=0`. The hardware half of that path is a Raspberry Pi
Pico 2 running the checked-in
[AG32 UART programmer](../pico/ag32_uart_programmer/README.md) — a fixture
that began as the bring-up logic analyzer and grew into the mask-ROM
programming bridge.

Install and verify the qualified SWD/DAP tool with:

```sh
agamemnon install-openocd
agamemnon doctor --probe-dap
```

Read [Programming](PROGRAMMING.md), [USB CDC uploader](USB_CDC_UPLOADER.md), and
[UART bootloader](UART_BOOTLOADER.md) before writing persistent state.

## Clocks and programmable IO

AGaMEMnon currently accepts 45 fabric `(SYSCLK,HSE)` pairs: the seven byte-exact
vendor-oracle profiles `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, `(100,16)`,
`(60,8)`, `(100,12)` MHz, plus 38 further HSE=8 `SYSCLK` rates that were
measured on silicon. The silicon-measured span is HSE=8, `SYSCLK` 4-248 MHz.
This is a fail-closed evidence list, not the theoretical capability of the PLL;
`(100,16)` and `(100,12)` in particular have **not** been exercised on the
reference board, which has an 8 MHz HSE.

These are fabric clock points, not RISC-V core frequencies. The hard-MCU
sources, transition invariants, vendor limits, and intentionally narrow open
HAL policy are documented in [MCU clocks](MCU_CLOCKS.md).

Hard-peripheral signals do not automatically appear on arbitrary pins.
Firmware configures the peripheral controller; the loaded fabric must provide
the matching route to package pins. I2C also requires open-drain behavior and
external pull-ups. Check the loaded fabric before assuming a vendor-default
UART, SPI, I2C, USB, or LED route remains present.

## Documentation map

Vendor information is real but fragmented across AGM domains, Chinese-language
pages, downloadable archives, and several naming conventions. These are the
best primary starting points known to this project:

- [AGM AG32 product site](https://www.ag32mcu.com/)
- [AG32 development tools](https://www.ag32mcu.com/dev-tools-category/dev_tools_fpga/)
- [AG32VF303CCT6 development board](https://www.ag32mcu.com/aum-product/products_board_ag32vf303cct6/)
- [AG32 MCU Reference Manual, 2025-05-15 revision](https://www.agm-micro.com/upload/userfiles/files/AG32%20MCU%20Reference%20Manual%2820250515%E4%BF%AE%E8%AE%A2%E7%89%88%EF%BC%89.pdf)
- [AGRV2K data sheet, revision 3.0](https://www.agm-micro.com/upload/userfiles/files/AGRV2K_Rev_3_0.pdf)
- the separate `AG32-Docs` research workbench, which is not currently public;
  derived workbench artifacts are cited by repository path when they are not
  redistributed here

AGM's site currently lists AG32 SDK and Supra downloads for Windows and Linux.
That does not make the vendor programmable-logic format open or the complete
workflow easy to reproduce. AGaMEMnon's narrower claim is an inspectable,
testable flow whose supported boundary is recorded in this repository.

## Evidence vocabulary

- **Build supported**: the public strict flow completes without a vendor
  executable or routed vendor checkpoint.
- **Silicon-qualified**: the emitted design was exercised through an
  electrically observable hardware oracle.
- **Vendor-documented**: a primary vendor source describes the feature, but
  AGaMEMnon may not implement or qualify it.
- **Implemented, unqualified**: code or a protocol exists and has software
  tests, but its target-side behavior has not crossed the stated silicon bar.

These labels are deliberately not interchangeable.
