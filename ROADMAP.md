# Roadmap

AGaMEMnon prioritizes reproducible first use, recovery safety, and honest
hardware evidence over broad but unqualified device coverage.

Dates are intentionally absent. A milestone is complete when its artifacts and
evidence exist, not when it has been announced.


## Downloadable SDK

- [ ] Ship AGaMEMnon, Yosys, AGRV2K nextpnr/runtime, and RISC-V GCC in pinned
  Windows and Linux build bundles.
  The two-host candidate workflow, exact download pins, clean-wheel gate, and
  archive smoke test are implemented. Locally assembled Windows and Linux
  candidates now pass the entire offline smoke, including MCU and strict FPGA
  builds. The Windows candidate additionally passes from a path containing
  spaces and non-ASCII text. This remains open until both hosted artifacts pass
  and are published.
- [x] Build and install AGaMEMnon's qualified OpenOCD from pinned official
  source, ship its exact patched GPL source and SBOM, and keep OS-Q only as an
  oracle.
- [x] Add an automated smoke test that installs the archive in a clean
  environment and runs `agamemnon --version`, `doctor --no-hardware`, offline
  verification, MCU compilation, and FPGA compilation.


## MCU SDK

- [x] Complete interrupt-vector and exception examples.
- [x] Document clock-tree transitions and supported operating points.
- [x] Add silicon-backed alternate-function and fabric-routing policy.
- [ ] Grow open drivers for watchdog, RTC, CRC, flash, CAN, USB, ADC, DAC,
  comparators, Ethernet, and DMA peripheral requests.
  CRC and the programmable APB watchdog are now present. All DMA boundary
  endpoints have narrow strict-open route support, but handshake semantics,
  drivers, and silicon transfers remain open alongside the other listed blocks.
- [ ] Add non-destructive qualification programs per hard peripheral.
  SRAM-safe candidates now cover core/interrupts, UART loopback, memory DMA,
  CRC, and a read-only watchdog snapshot; this remains open until every hard
  peripheral has a suitable program and evidence record.
- [x] Keep the external AGM PlatformIO ecosystem pinned and explicitly outside
  the open-HAL licensing boundary.

## FPGA flow

- [x] Establish a machine-validated family-level parity ledger separating
  encoding, open-flow, silicon, and package state; exhaustive primitive and
  parameter *domains* remain open in the
  [FPGA parity ledger](docs/FPGA_PARITY_LEDGER.md). The six AGRV2K-present
  families and all 136 of their declarations/defaults are now machine-readable
  without treating declared widths as legal-value claims. BRAM width is the
  first bounded parameter domain: on both ports, the ledger separates six
  model candidates, permissive backend acceptance, five fail-closed open direct
  modes, and the still-smaller silicon-qualified subset. Both physical
  five-bit fields are decoded byte-exactly across all repeated matrix images.
  RIO drive current plus the isolated pull-up/open-drain Booleans are the first
  populated legal domains, while open emission and electrical qualification
  stay explicitly absent. Slew remains unknown after its no-delta attempt.
- [x] Replace inherited preamble bytes with understood, declarative generated
  profiles; continue decoding the remaining baseline tile-grid defaults.
- [x] Ship distinct L100, L64, L48, and Q32 bond maps with provenance and
  qualification state; hardware qualification beyond L48 remains open.
- [ ] Broaden BRAM modes, tiles, initialization, and collision behavior. The
  emitter now rejects arbitrary five-bit width codes and direct x36 before bit
  generation. An inferred x9 image now builds strictly after unused-Port-B
  trimming, while a fresh SERV build proves live Port B remains intact; x9
  stayed all-ones in three volatile trials. The native L48 vendor x9 control
  passes, but matching its clock/reset field groups does not fix the open
  image. Its complete 21-hop `HADDR[2:5]` to `AddressA[3:6]` corridor is now
  recovered and promoted into the strict graph and bit generator; a fresh open
  functional retry remains unqualified.
- [ ] Expand dedicated-carry corridors and multi-chain placement.
- [ ] Improve timing from conservative mux-family bounds toward native wire,
  clock-skew, hard-block, package, and PVT models.
- [x] Decompose bitstream inspection, preamble generation, safe runtime-data
  loading, routing selectors, and AHB simulation behind regression gates.
- [ ] Complete the MCU/fabric boundary: the External AHB slave, fabric AHB
  master, interrupt and DMA sidebands, broader MCU GPIO routes, and documented
  analog cross-links. The dependency-ordered work and evidence gates are in
  [the MCU/fabric integration roadmap](docs/MCU_FABRIC_ROADMAP.md).

## Community qualification

- [x] Establish a known-good board/probe/transport table.
- [ ] Keep the table current as independent boards and reproducible OpenOCD
  builds are qualified.
- [ ] Accept append-only evidence from independently reproduced boards.
- [x] Add a guided qualification command that produces a reviewable report
  without writing target persistent state.
- [x] Track support separately by part, package, board, transport, and feature.
