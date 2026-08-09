# MCU clock tree and current operating policy

The AG32 has two clock domains that are easy to confuse:

- **MCU `SYSCLK`** drives the hard RISC-V system, flash interface, buses, and
  hard peripherals.
- **Fabric `SYSCLK`** is the clock emitted in the programmable-logic
  configuration by AGaMEMnon.

`build --freq` and a project's `[fabric].freq` select the second one and use
the same value for timing closure. `AGAMEMNON_SYSCLK` remains an override when
no build frequency is supplied; otherwise the qualified 10 MHz setting is the
default.
They do not re-clock the RISC-V core.

## Vendor-documented MCU tree

The AGM AG32 MCU Reference Manual (2025-05-15 revision), chapters 1 and 3 and
the electrical tables, documents:

| Source or derived clock | Documented boundary |
|---|---|
| HSI | selected after reset; RC oscillator 10-40 MHz, 20 MHz typical |
| HSE crystal/resonator | 4-24 MHz |
| HSE bypass input | up to 100 MHz |
| PLL input | 4-50 MHz |
| PLL output | 2-300 MHz electrical range |
| RISC-V CPU | 248 MHz maximum |
| external/fabric clock | listed as a fourth system-clock source |
| APB/PBUS | `SYSCLK / (PBUS_DIV + 1)`, divider 1 through 16 |
| flash SPI clock | `SYSCLK / (SCLK_DIV + 1)`, divider 1 through 16; high and low fields must match |
| USB | manual requires a 60 MHz PLL output when USB is used |

Those are vendor limits, not a claim that every combination is safe, reachable,
or qualified by AGaMEMnon. In particular, the PLL electrical maximum is above
the CPU maximum.

The exact reference board has an 8 MHz HSE. AGaMEMnon MCU examples currently
inherit the clock state established before entry; they do not silently switch
the core clock. Code that needs a peripheral baud clock must read the PBUS
divider and supply the actual inherited `SYSCLK` to `ag32_pbus_hz()`.

## Safe transition invariant

The manual specifies these ordering rules:

1. reset starts on HSI;
2. enable the desired oscillator or PLL;
3. wait for `HSE_RDY` or `PLL_RDY`;
4. switch only after the target reports ready;
5. never disable the source currently driving `SYSCLK`;
6. when increasing `SYSCLK`, set both flash SPI divider fields to a safe equal
   value before the switch;
7. switch back to HSI before disabling HSE or PLL.

The published register description identifies HSE/PLL enable and ready bits,
the two flash-divider fields, and the PBUS divider. It does not completely
describe the source-select encoding or a programmable PLL multiplier/divider
register. The open HAL therefore exposes the documented status/divider
registers but intentionally does **not** yet offer a runtime clock-switch API.
Copying an implementation from the separately pinned, unlicensed AGM
PlatformIO framework would violate the SDK's provenance policy.

## Supported operating points

For the **MCU**, the current open-SDK support claim is deliberately narrow:

- execute at the clock state inherited from reset, the resident USB loader, or
  the user's existing boot firmware;
- calculate PBUS frequency from a caller-supplied known `SYSCLK`;
- do not perform a dynamic HSI/HSE/PLL transition through AGaMEMnon's HAL yet.

The 248 MHz figure is a part maximum, not the default frequency promised by
the open startup. HSI is also not a precision baud-rate source across its full
electrical range.

For the **fabric**, byte-exact and silicon-backed `(SYSCLK,HSE)` tiers are
documented separately in [STATUS.md](STATUS.md). Byte-exact emission is limited
to `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, `(100,16)`, `(60,8)`, and
`(100,12)` MHz; the last two do not expand the existing silicon tier. None of
these fabric profiles is evidence for the MCU clock.

## External-AHB bus clock

The MCU-to-fabric External-AHB `bus_clock` is a third boundary and must not be
conflated with either frequency selection above. The qualified default
topology aliases it to `sys_gck`. Pure-open silicon evidence runs direct-D
self-feedback at X14Y11 slices 4 through 7, observes all eight states of an
explicit three-bit counter, and observes 500 distinct states of a 16-bit XNOR
LFSR through HRDATA[15:0].

The LFSR was correlated against MTIME with both the MCU and MTIME undivided
from the 10 MHz HSI reference. Three runs covering 45 intervals each measured
exactly one fabric state transition per MTIME tick, qualifying the default bus
clock at 10 MHz relative to that reference. A separate pure-open oracle uses
the qualified GPIO4.1 MCU ingress as a synchronous reset: 36/36 asserted-reset
reads across three runs were zero, both release phases advanced, and
reassertion re-armed the state. This qualifies deterministic reset state, not
the hard `MCU_RESETN` boundary or equal phase after differently timed release.
Unrestricted direct-D placement, the fourth binary carry cone, hard reset,
and explicit BUSCLK/PLL3 remain fail-closed work tracked in
[MCU_FABRIC_ROADMAP.md](MCU_FABRIC_ROADMAP.md).

## Qualification needed before an MCU clock API

A future open transition API needs:

- a primary-source or independently recovered source-select encoding;
- an understood PLL programming model, if it is programmable outside the
  fabric configuration;
- measured source frequencies and register snapshots on the L48 fixture;
- flash execution/readback while transitioning up and down;
- PBUS/UART/timer measurements at each claimed point;
- USB operation at its required clock;
- bounded ready timeouts and an HSI fallback.

Until those records exist, failing to expose a setter is the safe SDK behavior.

Primary source: [AG32 MCU Reference Manual, 2025-05-15 revision](https://www.agm-micro.com/upload/userfiles/files/AG32%20MCU%20Reference%20Manual%2820250515%E4%BF%AE%E8%AE%A2%E7%89%88%EF%BC%89.pdf).
