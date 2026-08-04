# Supported feature matrix

This page defines AGaMEMnon's supported AGRV2K feature set. "Build supported"
means the public flow completes through strict bitgen. "Silicon-qualified"
means the emitted image was exercised by an electrically observable hardware
oracle. FCB configuration acceptance alone is not functional qualification.

The generated [FPGA parity ledger](FPGA_PARITY_LEDGER.md) tracks the same
boundary by encoding recovery, open-flow implementation, silicon state, and
package. It is currently a family-level inventory, not an exhaustive parameter
catalog.

## Release flow

```text
synthesizable Verilog
  -> Yosys AGRV2K mapping
  -> nextpnr-generic --uarch agrv2k
  -> strict AGaMEMnon bitgen
  -> uncompressed SRAM image + compressed flash image
```

The release flow uses no vendor executable and no routed vendor checkpoint.
The Python generic-architecture adapter is available for small fixtures; the
`agrv2k` Viaduct backend is the supported scalable P&R path.

Baseline provenance: emitted images are assembled onto
`agamemnon/chipdb/fabric_default.bin`, a 2.8 KB compressed raw configuration.
Open-generated logic and routing bits are overlaid on it and residual baseline
slice bits are cleared. The complete 164-byte global/configuration-chain
preamble is now regenerated from declarative fixed, distribution, and
parametric PLL profiles rather than inherited from that canvas. The canvas
still supplies incompletely decoded non-preamble defaults, so removing it
entirely remains tracked work.

See [the provenance notice](../NOTICE.md) for the licensing and redistribution
boundary around the baseline, derived databases, external tools, and vendor
documentation.

## Fabric features

| Feature | State | Supported boundary |
|---|---|---|
| LUT4 and flip-flop RTL | Silicon-qualified | Combinational logic, registered feedback, counters, shifts, state machines, constants, physical-input registers, and large sequential designs |
| General routing | Silicon-qualified subset | Exact conflict-free physical selectors plus unanimous tile-relative selectors; predicted, conflicting, legacy, or unresolved selectors fail closed |
| Global clock | Silicon-qualified subset | Clock distribution to near and far logic tiles using the listed PLL configurations |
| Physical outputs | Silicon-qualified L48 subset | Characterized header outputs and PIN_25, PIN_26, PIN_27, and PIN_28 |
| Physical inputs | Silicon-qualified L48 subset | PIN_10, PIN_11, PIN_15, and PIN_19; PIN_19 also has a qualified registered path |
| MCU GPIO bridge | Silicon-qualified | Four-bit MCU-to-fabric-to-MCU inverter loopback over all input combinations |
| External AHB read | Silicon-qualified | All 32 fabric-to-MCU data lanes in one simultaneous read |
| External AHB write | Silicon-qualified subset | All 32 MCU write-data lanes in protocol-valid four-bit groups |
| External AHB address | Silicon-qualified subset | Registered isolation of `HADDR[4:2]` through `MCU_DIN76:78`; all eight values observed during a 256-address SRAM sweep |
| External AHB bus clock | Silicon-qualified subset | Pure-open default `bus_clk = sys_gck` delivery toggles one direct-D TFF at the qualified X14Y11 slice7 site; both HRDATA[0] states observed. Exact frequency, edge count, deterministic reset, PLL3 BUSCLK, and multiple feedback registers remain unqualified |
| External AHB constant slave | Silicon-qualified | Constant-ready, OKAY-only combinational endpoint; 32-bit reads return `0x4147414d`, writes complete without effect; no wait/error/register-bank claim |
| Fabric local interrupts | Silicon-qualified routing/cause subset | Four distinct sources route simultaneously to `local_int[3:0]`; lanes independently deliver local causes 16–19 with the matching `mip` bit. AHB pending/acknowledge/re-arm remains open |
| Dedicated carry | Silicon-qualified opt-in | Same-tile short chains and one 33-site corridor containing a seed plus up to 32 arithmetic stages |
| BRAM | Silicon-qualified subset | One x18 Port-A path and one x2 Port-B read/control path; the backend represents independent A/B ports |
| ADC/fabric routes | Build-supported, hardware-unqualified | Distinct read-only ADC0 result bits 0/1 and EOC typed corridors; no ADC configuration or electrical claim |
| PLL | Silicon-qualified subset | `(SYSCLK,HSE)` pairs `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, and `(100,16)` MHz |
| Timing | Conservative estimate | LUT/FF/carry arcs and worst wire delay per driving mux family; requested failure is fatal |

## Routing policy

The release selector database contains 659,759 conflict-free physical edge
encodings and 62,044 tile-relative encodings whose physical observations all
agree. Conflicting relative keys are omitted. Architecture generation and
bitgen enforce the same selector boundary.

The device database also contains 14 edges classified by repeated isolated
negative silicon trials. Negative isolated evidence overrides corpus
attribution. Whole-design correlation is not used to classify an individual
edge.

Simultaneous MCU bundles use global source matching and bounded corridor
negotiation rather than greedy per-lane reservation. Recovered vendor paths
that cross `alta_slice` remain logical-cell evidence and are not admitted as
transparent routing PIPs. The L48 constant-slave qualification covers the
corrected 32-lane result and both response controls.

## Dedicated carry

`build --uarch --hard-carry` lowers eligible arithmetic to `AG32_FA`, adds one
physical seed per independent chain, places the chain contiguously, and uses
normal LUT-to-FF capture.

Multiple same-tile chains are accepted when:

```text
sum(arithmetic stages) + number of chains <= 9
```

One chain may instead use the qualified 33-site order through X20Y11,
X20Y12, and X20Y10. Other spill locations, multiple long chains, branches,
and malformed chains fail closed. Dedicated carry is opt-in.

## BRAM

The integrated BRAM model exposes independent A/B clocks, enables, addresses,
data, widths, and write controls. Yosys can infer an `ALTA_BRAM9K` for the
memory pattern used by the SERV example.

Hardware qualification is limited to one characterized x18 Port-A path and
one exact x2 Port-B read/control corridor. The recovered x9 address comparison
builds with exact selectors and active readback, but remains address-static on
silicon even though an isolated `HADDR[4:2]` capture passes and its `INIT_VAL`
matches the vendor control bit-for-bit. Other BRAM tiles, arbitrary fresh
corridors, widths, narrow-mode behavior, write modes, and read/write collision
semantics are unsupported.

## Timing and PLL

`build --freq MHz` selects the emitted fabric PLL, requests timing closure at
that same frequency, and fails if nextpnr misses the target. Cell timing covers
conservative LUT, flip-flop setup/hold/clock-to-Q, and carry arcs. Wire timing
uses the largest decoded delay for each driving mux family. When no frequency
is supplied by the CLI, project, or environment, the qualified default is
10 MHz.

The timing report is not a complete silicon Fmax model. Exact native wire
class binding, clock skew, IO, BRAM, PLL, package, and broad PVT delays are not
modeled.

PLL emission accepts only the listed `(SYSCLK,HSE)` pairs, and `--freq` fails
before synthesis if the corresponding pair is unsupported. The qualified
`examples/firmware/clkcfg_stub.c` temporarily selects HSI for FCB streaming
and restores the selected PLL after lock; `agamemnon sram` itself is a generic
firmware loader and does not perform that transition. Other PLL outputs,
divider ranges, phase, duty-cycle, feedback, and bypass modes fail closed.

## Packages and IO

Package legality and physical `PIN_n` to IOTILE bond maps exist for
`AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and `AGRV2KQ32`. L48 is an exact,
silicon-qualified map. The other three are architecture-recovered and emit an
explicit unqualified-package warning; they do not inherit L48 qualification.

The qualified L48 harness maps PIN_25/26/27/28 to Pico
GP12/GP13/GP16/GP17. That mapping is package- and board-specific; it is not a
claim about identically numbered pins on L100, L64, Q32, or another board.

## Bitstreams and programming

| Capability | State |
|---|---|
| LZW decode/encode | Byte-exact for canonical images |
| Raw configuration and CRC | Supported; 99,936-byte raw image with CRC-32/BZIP2 |
| `.agasc` | Lossless named-feature and sparse-raw round trip |
| LUT editing | Supported without rerouting |
| SRAM configuration | Silicon-qualified |
| Main-flash backup, erase, program, and readback verify | Silicon-qualified |
| RV32 MCU-only SRAM execution | Silicon-qualified; signature, DEVICE_ID, misa, and SRAM PC read back over SWD |
| RV32 native/separate flash applications | Silicon-qualified subset; freestanding startup/linkers included, USB-loaded LED app executed at `0x80010000` and its sector was restored byte-exact |
| Pico 2 UART0 ROM programmer firmware and host protocol | Implemented; Pico USB-smoke-tested, target wiring pending |
| Flash-resident USB CDC uploader | Silicon-qualified on L48 for enumeration, identify, read, page erase, write, full readback verification, restoration, and reset |
| Native `--transport usb` CLI | Silicon-qualified for loader 2.1 identify/DEVICE_ID and direct flash read; write/GO use the same unit-tested loader protocol and retain the earlier independent silicon evidence |
| Boot from an existing compressed-config pointer | Silicon-qualified |
| New option-pointer programming | Implemented as explicit opt-in; unsupported for deployment |

SWD hardware commands require a CMSIS-DAP probe and an OpenOCD executable that
implements AGM's `target create riscv -dap` extension. Stock upstream and OSS
CAD Suite OpenOCD builds do not provide that target. Use
`agamemnon install-openocd`, then verify the probe and target with
`agamemnon doctor --probe-dap`. The pinned build and qualification evidence
are documented in [Programming](PROGRAMMING.md).

The UART bootloader uses a Pico 2 and needs no OpenOCD. Its software and
Pico-side bridge are tested, but the target UART link is not silicon-qualified
until the documented harness wires are installed. Native USB ROM boot and USB
DFU class are not implemented. A separate flash-resident CDC ACM uploader is
silicon-qualified on the L48 bench; it is not a recovery path when main flash
is corrupt.

## SERV scope

The shipped SERV examples use a true-dual-port x2 BRAM register file. Hardware
qualification covers continuing instruction fetch/store operation and a
signature workload containing dependent `addi`, `slli`, `xori`, not-taken
`bne`, taken `beq`, `sw`, and repeated backward `jal`.

This is not full RV32I compliance. Other instructions, R-type ADD, exceptions,
CSRs, interrupts, and complete trap behavior are outside the supported claim.
