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

Frequency selection and physical clock reach are separate claims. The campaign
passes one matched PLL/shift point, but a five-site far-region state vehicle
placed and timed cleanly, matched its routed logical evaluator, and returned
zero state on silicon (`VP-AGM-007`). Therefore the qualified HSE=8 output-rate
table does not imply that arbitrary placed registers receive a correct clock or
data path. Clock regions, seams, skew, gating, and far-site delivery remain
open.

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
the core clock. Code that needs a peripheral baud clock must resolve the clock
the part is *actually* running at — see the next two sections.

## Measured default clock on an SRAM-loaded part

**Nothing in the SDK configures the clock tree.** `ag32_pbus_hz()` never did:
it reads the live `PBUS_DIVIDER` field and divides a `SYSCLK` value the *caller*
supplied. Handing it the part's 248 MHz maximum does not make the part run at
248 MHz; it just produces divisors that are wrong by the ratio between 248 MHz
and whatever really clocks the peripheral.

### The UART defect

On 2026-08-14 an SRAM-loaded stub on the L48 bench called
`ag32_pbus_hz(248000000)` and then `ag32_uart_init(UART0, pbus, 9600)`. A logic
analyzer measured **~560 baud, not 9600** — about 17x slow. That is a real,
silicon-observed defect: the value `ag32_pbus_hz()` returned did not describe
UART0's reference clock.

On 2026-08-16 the corrected path used `ag32_uart_ref_hz_measured()` and the same
exact routed PIN_10 output. An independent Pico PIO UART receiver decoded 64/64
bytes of the exact repeating pattern at requested 9600, 38400, and 115200 baud.
An independent receive matrix then routed PIN_31 to UART0_UARTRXD and received
the same 64/64 pattern from the board DAP CDC transmitter at all three rates.
A combined PIN_30/PIN_31 image subsequently transferred 4096 exact bytes in
each direction concurrently at all three rates; each run completed near one
ideal wire duration rather than the sum of the two directions.
At 38400 baud, the same route also passed 7E1, 8E1, 8O1, and 8N2 line modes
in both directions; this broadens framing interoperability without adding an
absolute-frequency measurement.
That qualifies nominal-rate interoperability at those points; it does not turn
the bench back-solve into a universal sub-percent clock calibration.

### The clock tree is not characterized

Three measurements were taken on the **same board in the same SRAM-loaded,
PLL-unconfigured configuration**:

| Domain | Measured | Method |
|---|---|---|
| MTIME | **14.08 MHz** | counted against a host `sleep 1000` over the debug link, repeated, consistent |
| UART0 baud reference | **~14.47 MHz** | back-solving the divisors the PL011 driver programmed (`IBRD`=1614, `FBRD`=37) against the 1786 us measured bit time (560 baud): `560 * 16 * 1614.578` |
| SPI0 shift-clock reference | **UNRESOLVED**; relative divider behavior qualified | The original flat capture was an SDK reset-sequence defect: writing `CTRL.SOFT_RESET` left `CTRL=0x00008202` and discarded the next divider write. With APB reset followed by a direct `CTRL` write, all documented power-of-two divisors 2–256 read back exactly, completed 64/64 one-byte transfers, and produced strictly increasing MTIME latency. This proves relative division, not an absolute reference frequency |

MTIME and UART0 agree with each other to within ~3%, which is *consistent* with
the documented model at `PBUS_DIV + 1 == 1` (MTIME counts the system clock;
UART0's reference is an APB clock derived from it). SPI0's absolute reference is
still **unknown**: the repaired divider sweep used MTIME as a relative timebase,
so whether SPI0 shares the ~14 MHz domain or runs from another source remains an
open question.

> **The clock tree is uncharacterized, not demonstrably non-uniform.** A "not
> uniform", "three domains ~18x apart" reading would rest entirely on an SPI0
> reference of ~258 MHz, computed as `measured SCK x programmed divider 200`.
> **That figure does not hold** because divisor 200 was never latched, and with
> it goes the evidence for non-uniformity. The two *measured* references agree
> and do not contradict the single-APB model, so the tree is **uncharacterized**
> rather than demonstrably non-uniform. The operational point is that you cannot
> compute a peripheral's rate from a datasheet number — only UART0's reference
> has been measured at all.

**Honest summary: the UART's reference clock is not the value `ag32_pbus_hz`
returns; it measured ~14.5 MHz here while SPI0's could not be determined. The
clock tree is not yet characterised — not proven non-uniform, just unmeasured
outside UART0 and MTIME.**

Caveats on the numbers themselves:

- Each is a MEASURED OBSERVATION of one peripheral on one board in one
  configuration. None is a datasheet constant, and the `CLK_CNTL` /
  `PBUS_DIVIDER` / `MTIME_PSC` state that produced them was not captured — which
  is why the examples now publish those three registers in their mailboxes.
- The two old SCK estimates disagree because both were oversample-limited and,
  more importantly, the broken init sequence left the hardware at its reset
  divider. They are retained as historical observations, not rate calibration.
- The repaired `ag32_spi_init` accepts only the documented powers of two 2–256.
  `qualification/spi_divider_evidence.jsonl` binds the monotonic MTIME sweep;
  odd and non-power-of-two values remain deliberately unsupported.

One clock side effect worth knowing regardless: `ag32_fcb_config()` clears the
`CLK_CNTL` source select plus the HSE and PLL enables before streaming a fabric
image (the historical `&= ~0x27`), and nothing in this SDK switches back. Note
also that the MCU PLL's *rate* is established by the fabric configuration — the
project's `(SYSCLK,HSE)` pair emitted into the bitstream — not by an MCU-side
multiplier register.

## Resolving the real peripheral clock

`ag32_sysctl.h` exposes the documented, readable part of the clock registers plus
the per-domain measurements, so firmware can state what it is assuming instead of
inventing a rate:

| Helper | Meaning |
|---|---|
| `ag32_sysclk_source()` | live source select: `AG32_CLK_SOURCE_HSI`/`HSE`/`PLL`/`EXT` |
| `ag32_clk_hse_ready()`, `ag32_clk_pll_ready()` | documented ready bits |
| `ag32_pbus_divider()` | live APB divisor, 1..16 |
| `ag32_mtime_divider()` | live MTIME divisor, 1..65536 |
| `ag32_uart_ref_hz_measured()` | the measured UART0 reference (~14.47 MHz) — the only APB reference actually measured |
| `ag32_sysclk_hz(&sources)` | source select resolved against a board profile |
| `ag32_pbus_hz_actual(&sources)` | the above divided by the live PBUS divider — documented model, not yet silicon-confirmed |
| `ag32_pbus_hz(sysclk_hz)` | unchanged legacy divide of a caller-supplied rate |

Silicon can report *which* source drives `SYSCLK` and by what divider; it cannot
report the absolute frequency of a crystal or an untrimmed RC oscillator, so an
`ag32_clk_sources_t` profile supplies those and any entry left 0 makes the
helpers return 0 rather than invent a rate.

Per-domain constants are named for the domain they were measured in.
`AG32_MTIME_HZ_MEASURED` and `AG32_UART_REF_HZ_MEASURED` are current
measurements. `AG32_SPI0_RESET_SCK_HZ_HISTORICAL` (and its compatibility alias
`AG32_SPI0_SCK_HZ_MEASURED`) is only the upper old analyzer estimate at the
accidentally retained reset divider; it is not current SCK calibration. No SPI0
reference constant is published because none is known.
`AG32_HSI_HZ_VENDOR_NOMINAL` (10 MHz) is kept only for contrast.
None of these is accurate enough for a link that must interoperate with another
device's baud clock; that needs a real frequency measurement.

`i2c_probe.c` and `can_selftest.c` currently borrow the UART figure. That is
labelled in both sources as an explicit, unverified **cross-domain assumption** —
no APB reference other than UART0's has been independently measured. SPI0's
relative divider now works, but its absolute reference is still unresolved. Both
examples report the assumed clock plus the three clock registers so a bench run
can derive the truth.

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
the two flash-divider fields, the PBUS divider, and the two-bit `SYSCLK`
source-select field (`0` HSI, `1` HSE, `2` PLL, `3` external/fabric). It does
not describe a programmable PLL multiplier/divider register on the MCU side at
all — the PLL rate is fixed by the fabric configuration.

The open HAL therefore **reads** those documented status/divider fields and
intentionally does **not** offer a runtime clock-switch API. Reading a field to
report the truth is not the same as shipping an unqualified switch sequence, and
copying an implementation from the separately pinned, unlicensed AGM PlatformIO
framework would violate the SDK's provenance policy either way.

## Supported operating points

For the **MCU**, the current open-SDK support claim is deliberately narrow:

- execute at the clock state inherited from reset, the resident USB loader, or
  the user's existing boot firmware;
- read the live source select and PBUS/MTIME dividers, and resolve the PBUS
  frequency against a caller-supplied board profile;
- do not perform a dynamic HSI/HSE/PLL transition through AGaMEMnon's HAL yet.

A runtime clock-switch setter is still deliberately absent even though the
source-select encoding is now readable: the transition sequence is unqualified
on this fixture, the PLL rate is not an MCU-side programmable, and an unverified
setter can strand the part. Making callers state (or measure) their clock is the
safer trade.

The 248 MHz figure is a part maximum, not the default frequency promised by
the open startup — the measured SRAM/no-PLL default is ~17x below it. HSI is
also not a precision baud-rate source across its full electrical range.

For the **fabric**, byte-exact and silicon-backed `(SYSCLK,HSE)` tiers are
documented separately in [STATUS.md](STATUS.md). Fabric PLL emission is a single
closed-form divider equation, differentially validated byte-exact on all 53
points of a vendor `(SYSCLK,HSE)` sweep; on the board's 8 MHz HSE it is
silicon-frequency-qualified across `SYSCLK` 4-248 MHz (two-window MTIME solve).
`(100,16)` and `(100,12)` remain preamble/timing-only and do not expand the
silicon tier. None of these fabric profiles is evidence for the MCU clock.

## External-AHB bus clock

The MCU-to-fabric External-AHB `bus_clock` is a third boundary and must not be
conflated with either frequency selection above. The qualified default
topology aliases it to `sys_gck`. Pure-open silicon evidence runs direct-D
self-feedback at X14Y11 slices 4 through 7, observes all eight states of an
explicit three-bit counter, and observes 500 distinct states of a 16-bit XNOR
LFSR through HRDATA[15:0].

The LFSR was correlated against MTIME with both the MCU and MTIME undivided.
Three runs covering 45 intervals each measured exactly one fabric state
transition per MTIME tick. **What that qualifies is the 1:1 ratio, not an
absolute frequency.**

> **Open question — the "10 MHz bus clock" figure.** The "10 MHz" label takes
> MTIME to be running at the vendor-nominal 10 MHz HSI rate. The direct
> measurement in the section above puts MTIME at **14.08 MHz** in an SRAM-loaded,
> PLL-unconfigured configuration — the same kind of configuration these runs use. The two cannot
> both be right. The 1:1 ratio is unaffected either way, and every derived
> tick-count result ("21 MTIME ticks per set/acknowledge", "40 ticks for
> synchronous reset clear", "one LFSR step per tick") is a *tick count* and is
> also unaffected. Only the absolute-frequency label is in doubt, and it is not
> resolved here: the `CLK_CNTL` / `MTIME_PSC` state of the bus-clock
> runs was not captured. Other pages that print "10 MHz bus clock" are
> inheriting that unverified inference — read them as "one bus clock per MTIME
> tick".

A separate pure-open oracle uses
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
