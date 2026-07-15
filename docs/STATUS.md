# Supported feature matrix

This page defines AGaMEMnon's supported AGRV2K feature set. "Build supported"
means the public flow completes through strict bitgen. "Silicon-qualified"
means the emitted image was exercised by an electrically observable hardware
oracle. FCB configuration acceptance alone is not functional qualification.

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
| Dedicated carry | Silicon-qualified opt-in | Same-tile short chains and one 33-site corridor containing a seed plus up to 32 arithmetic stages |
| BRAM | Silicon-qualified subset | One x18 Port-A path and one x2 Port-B read/control path; the backend represents independent A/B ports |
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
one exact x2 Port-B read/control corridor. Other BRAM tiles, arbitrary fresh
corridors, widths, narrow-mode initialization layouts, write modes, and
read/write collision semantics are unsupported.

## Timing and PLL

`build --freq MHz` requests timing closure and fails if nextpnr misses the
target. Cell timing covers conservative LUT, flip-flop setup/hold/clock-to-Q,
and carry arcs. Wire timing uses the largest decoded delay for each driving
mux family.

The timing report is not a complete silicon Fmax model. Exact native wire
class binding, clock skew, IO, BRAM, PLL, package, and broad PVT delays are not
modeled.

PLL emission accepts only the listed `(SYSCLK,HSE)` pairs. The SRAM loader
temporarily selects HSI for FCB streaming and restores the selected PLL after
lock. Other PLL outputs, divider ranges, phase, duty-cycle, feedback, and
bypass modes fail closed.

## Packages and IO

Package legality data exists for `AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and
`AGRV2KQ32`. Only L48 has a physical `PIN_n` to IOTILE bond map. Physical PCF
builds for the other packages fail closed.

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
| Boot from an existing compressed-config pointer | Silicon-qualified |
| New option-pointer programming | Implemented as explicit opt-in; unsupported for deployment |

Hardware commands require a CMSIS-DAP probe and an OpenOCD executable that
implements AGM's `target create riscv -dap` extension. Stock upstream and OSS
CAD Suite OpenOCD builds do not provide that target. UART bootloader and native
USB DFU transports are not implemented.

## SERV scope

The shipped SERV examples use a true-dual-port x2 BRAM register file. Hardware
qualification covers continuing instruction fetch/store operation and a
signature workload containing dependent `addi`, `slli`, `xori`, not-taken
`bne`, taken `beq`, `sw`, and repeated backward `jal`.

This is not full RV32I compliance. Other instructions, R-type ADD, exceptions,
CSRs, interrupts, and complete trap behavior are outside the supported claim.
