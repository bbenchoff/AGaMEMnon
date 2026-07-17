# Roadmap

AGaMEMnon prioritizes reproducible first use, recovery safety, and honest
hardware evidence over broad but unqualified device coverage.

Dates are intentionally absent. A milestone is complete when its artifacts and
evidence exist, not when it has been announced.

## Before the public launch

- [x] Confirm every qualified board reference says `AG32VF303CCT6` /
  `AGRV2KL48`.
- [ ] Add a clear photograph of the exact supported board with USB, DAP, boot,
  clock, LED, and qualified fabric pins labeled.
- [ ] Record a short MCU-to-fabric demonstration and terminal transcript.
- [ ] Review `NOTICE.md` and the `fabric_default.bin` redistribution boundary.
- [ ] Enable private vulnerability reporting and GitHub Discussions.
- [ ] Configure the repository description, topics, social preview, and
  documentation homepage.
- [ ] Run the complete hardware-free CI matrix from a fresh Git LFS checkout.
- [ ] Repeat the beginner SRAM path from a clean Windows and Linux host.

## First downloadable SDK

- [ ] Publish a matching tag, changelog entry, archive, SHA-256 file, and
  version manifest.
- [ ] Ship AGaMEMnon, Yosys, AGRV2K nextpnr/runtime, and RISC-V GCC in pinned
  Windows and Linux build bundles.
- [ ] Include compatible OpenOCD only with its exact corresponding GPL source;
  otherwise label the bundle build-only and make DAP diagnostics actionable.
- [ ] Add an automated smoke test that installs the archive in a clean
  environment and runs `agamemnon --version`, `doctor --no-hardware`, offline
  verification, MCU compilation, and FPGA compilation.
- [ ] Publish release checksums and a component/license inventory.

## MCU SDK

- [ ] Complete interrupt-vector and exception examples.
- [ ] Document clock-tree transitions and supported operating points.
- [ ] Add silicon-backed alternate-function and fabric-routing policy.
- [ ] Grow open drivers for watchdog, RTC, CRC, flash, CAN, USB, ADC, DAC,
  comparators, Ethernet, and DMA peripheral requests.
- [ ] Add non-destructive qualification programs per hard peripheral.
- [ ] Keep the external AGM PlatformIO ecosystem pinned and explicitly outside
  the open-HAL licensing boundary.

## FPGA flow

- [ ] Replace the vendor-originated default preamble with an understood,
  from-scratch configuration.
- [ ] Expand package bond maps only with package-specific evidence.
- [ ] Broaden BRAM modes, tiles, initialization, and collision behavior.
- [ ] Expand dedicated-carry corridors and multi-chain placement.
- [ ] Improve timing from conservative mux-family bounds toward native wire,
  clock-skew, hard-block, package, and PVT models.
- [ ] Decompose the engine by subsystem while retaining byte-exact and routed
  graph regression gates.

## Community qualification

- [x] Establish a known-good board/probe/transport table.
- [ ] Keep the table current as independent boards and reproducible OpenOCD
  builds are qualified.
- [ ] Accept append-only evidence from independently reproduced boards.
- [ ] Add a guided qualification command that produces a reviewable report
  without writing persistent state.
- [ ] Track support separately by part, package, board, transport, and feature.
