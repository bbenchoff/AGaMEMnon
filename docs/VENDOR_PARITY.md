# Vendor-parity status

This page answers a narrower question than [Status](STATUS.md): how close is
AGaMEMnon to accepting everything the vendor flow accepts? The answer is **not
close to full parity yet**. The current tool is a useful, reproducible,
fail-closed L48 subset; campaign completion and recovered encodings must not be
confused with default build support or silicon qualification.

## What works today

On the AG32VF303CCT6 L48 development board, the public flow can take ordinary
synthesizable Verilog through Yosys, the AGRV2K nextpnr Viaduct backend, strict
bit generation, and documented programming paths. Supported examples exercise
LUT4/FF logic, bounded carry, selected physical IO, fixed clock profiles, a
bounded MCU/fabric boundary, one BRAM read subset, and retained SERV designs.
Unsupported selectors, packages, clock pairs, direct-D placements, and feature
compositions are rejected rather than guessed.

The runtime flow does not invoke the vendor executable and does not consume a
vendor-routed checkpoint. It does include reverse-engineered databases and a
disclosed vendor-origin `fabric_default.bin` canvas. Therefore “no vendor
executable at runtime” is accurate; “fully vendor-free/from-scratch image” is
not.

## Parity gaps

| Surface | Public state | Gap to vendor parity |
|---|---|---|
| RTL/synthesis | Ordinary synthesizable LUT/FF designs and bounded documented structures work | The vendor primitive/parameter library is much broader; unsupported families, modes, constraints, and lowering patterns remain |
| Placement and routing | Exact admitted selectors, 659,759 conflict-free physical corpus keys, and 62,044 unanimous relative encodings | These counts describe an observed corpus, not device coverage. The measured baseline had at least one clean edge in 159 of 322 grid tiles. Many tiles/mux inputs and arbitrary vendor-routable designs remain unavailable |
| V5 R2 routing campaign | 71,697/71,697 frozen live target rows have exact vendor-authored occupancy witnesses; 42,297 phantom and 14 silicon-dead rows are terminal. The public research manifest records this closure | Witnessing is not selector admission, edge-specific encoding, or silicon conduction. Only six RMUX30 rows are reviewed under `experimental-strict`; `research-unsafe` may use broader vendor-derived/predicted knowledge without promoting it |
| Bitstream generation | Codec, CRC, 164-byte preamble, and supported feature overlays are open and regression-tested | Non-preamble defaults still come from `fabric_default.bin`; exhaustive bit ownership and a fully from-scratch image are open |
| BRAM | Behavior-qualified X13Y4 read subset: x18 Port A, x2 Port B, and documented x9 projections/bundle | The 39 B4 rows across X13Y1..Y4 are experimental config encodings only. General writes, byte enables as behavior, output registers, width/mode combinations, independent clocks, collisions/read-during-write, high-address breadth, and other-site behavior remain unqualified |
| PLL and clocks | Seven fixed byte-exact `(SYSCLK,HSE)` preambles; a narrower set has L48 silicon observations | No arbitrary dividers, phase/duty, feedback/bypass, other outputs, general HSI/oscillator-source selection, or complete silicon/timing qualification |
| Timing | Conservative fatal timing closure with 542 exact local OMUX-to-IMUX patterns covering 9,375 L48 route pips | 226,540 ordinary route pips use conservative family fallback. No complete native wire classes, clock skew, hard-block/IO/BRAM/PLL/package/PVT model, or sign-off Fmax model |
| IO and packages | Selected L48 pins and static input/output behavior; recovered maps for L48/Q32/L64/L100 | Only L48 is silicon-qualified. Dynamic OE/open-drain/bidirectional electrical behavior, broad electrical attributes, full pinouts, and other packages need hardware qualification |
| MCU External AHB | Public main has full HRDATA route recovery, a constant slave, posted complete-byte bank, separate seven-bit waited bank, bounded address/control paths, and one-hot interrupt commands | A workbench branch silicon-closed a complete-byte waited bank, exact 32-bit reads, and aligned subword behavior, but that implementation is not in current public main. Hard reset, alternate bus clocks, generic direct-D, wider state, complete protocol/error behavior, AHB master/DMA, and broader peripherals remain |
| Hard blocks | Selected MCU/BRAM/PLL paths and three ADC read corridors | General ADC configuration/analog behavior, hard UART integration, DMA/master surfaces, oscillator modes, and other hard-block modes are absent or bounded |
| SERV | Retained silicon-running instruction-signature subset | Not RV32I compliance; R-type ADD, CSRs, exceptions, traps, interrupts, and general fresh-source closure remain outside the claim |
| Programming and boot | SRAM, flash backup/erase/program/verify, patched-OpenOCD DAP, bounded USB-CDC loader, and existing-pointer boot paths | New option-pointer deployment is opt-in/unsupported; fully from-scratch boot images and stock-tool recovery parity remain open |

## Numbers that must not be conflated

- `659,759 / 733,862` is the clean share of **observed recovery-corpus edge
  keys** (90%), not a percentage of all device routing.
- `71,697 / 71,697` is the terminal live-row denominator of the frozen R2
  **workbench witnessing ledger**, not public release coverage.
- Six RMUX30 rows are the only new R5 routing-population rows admitted to the
  public database, and only under `experimental-strict`.
- The separate research profile retains all 74,103 conflicted physical-key
  distributions and broad predicted/majority fallbacks. “Present in
  AGaMEMnon” therefore does not mean “release admitted.”
- BRAM `54/54` and PLL `63/63` mean their frozen collection ledgers have no
  unobserved targets. They do not mean all BRAM or PLL behavior is supported.
- The timing overlay has 542 normalized pairs and 9,375 exact route pips out
  of 235,915 ordinary route pips in the strict L48 graph; the remaining
  226,540 use fallback timing.

## Release status

Annotated `v0.1.0` and `v0.1.1` tags exist, and current main is a `0.1.2`
candidate. Tags and clean CI prove reproducibility; they are not themselves
downloadable publication. The Releases page is authoritative for published
archives, and the package index is authoritative for a published wheel.

For exact supported behavior, see [Status](STATUS.md), [Hardware
qualification](HARDWARE_VALIDATION.md), and the machine-readable
`agamemnon/sdk/support_matrix.json`.

## Research availability is not parity

The opt-in `--research-unsafe` profile makes substantially more recovered
knowledge executable for experiments: the full normalized topology inputs,
completed crossbar, conflict distributions, context/absolute majorities, and
selector predictors. Its mandatory sidecar reports what a particular image
used. It does not change any gap above: vendor occupancy is not conduction,
prediction is not decoding, configuration is not behavior, and an L48 corpus
does not qualify another package.
