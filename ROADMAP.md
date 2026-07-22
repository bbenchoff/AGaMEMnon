# Roadmap

AGaMEMnon prioritizes reproducible first use, recovery safety, and honest
hardware evidence over broad but unqualified device coverage.

Dates are intentionally absent. A milestone is complete when its artifacts and
evidence exist, not when it has been announced.


## Downloadable SDK

- [ ] Ship AGaMEMnon, Yosys, AGRV2K nextpnr/runtime, and RISC-V GCC in pinned
  Windows and Linux build bundles.
  The two-host candidate workflow, exact download pins, clean-wheel gate, and
  archive smoke test are implemented; this remains open until both hosted
  artifacts pass and are published.
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
  CRC and the programmable APB watchdog are now present; the remaining listed
  blocks and DMA request routing keep this milestone open.
- [ ] Add non-destructive qualification programs per hard peripheral.
  SRAM-safe candidates now cover core/interrupts, UART loopback, memory DMA,
  CRC, and a read-only watchdog snapshot; this remains open until every hard
  peripheral has a suitable program and evidence record.
- [x] Keep the external AGM PlatformIO ecosystem pinned and explicitly outside
  the open-HAL licensing boundary.

## FPGA flow

- [x] Replace inherited preamble bytes with understood, declarative generated
  profiles; continue decoding the remaining baseline tile-grid defaults.
- [x] Ship distinct L100, L64, L48, and Q32 bond maps with provenance and
  qualification state; hardware qualification beyond L48 remains open.
- [ ] Broaden BRAM modes, tiles, initialization, and collision behavior.
- [ ] Expand dedicated-carry corridors and multi-chain placement.
- [ ] Improve timing from conservative mux-family bounds toward native wire,
  clock-skew, hard-block, package, and PVT models.
- [x] Decompose bitstream inspection, preamble generation, safe runtime-data
  loading, routing selectors, and AHB simulation behind regression gates.

## Community qualification

- [x] Establish a known-good board/probe/transport table.
- [ ] Keep the table current as independent boards and reproducible OpenOCD
  builds are qualified.
- [ ] Accept append-only evidence from independently reproduced boards.
- [x] Add a guided qualification command that produces a reviewable report
  without writing target persistent state.
- [x] Track support separately by part, package, board, transport, and feature.
