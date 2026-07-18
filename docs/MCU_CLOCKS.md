# MCU clock tree and current operating policy

The AG32 has two clock domains that are easy to confuse:

- **MCU `SYSCLK`** drives the hard RISC-V system, flash interface, buses, and
  hard peripherals.
- **Fabric `SYSCLK`** is the clock emitted in the programmable-logic
  configuration by AGaMEMnon.

`AGAMEMNON_SYSCLK` and a project's `[fabric].sysclk` select the second one.
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

For the **fabric**, byte-exact and silicon-backed `(SYSCLK,HSE)` pairs are
documented separately in [STATUS.md](STATUS.md). At present those are
`(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, and `(100,16)` MHz. They must not be
used as evidence for the MCU clock.

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
