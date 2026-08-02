# Roadmap

This file lists open work only. Current public support belongs in
[docs/STATUS.md](docs/STATUS.md); completed experiments and artifact hashes
belong in the append-only qualification ledgers.

AGaMEMnon prioritizes reproducible first use, recovery safety, and bounded
hardware evidence over broad but unqualified coverage.

## Immediate priorities

1. Isolate the BRAM terminal/read-control fault that leaves the exact-routed
   x9 image address-static on silicon.
2. Recover and qualify the External-AHB bus clock/reset path, then close and
   exercise the sequential register-bank endpoint.
3. Route four independent `local_int` sources and add AHB-backed pending,
   mask, acknowledge, and re-arm behavior.
4. Publish Windows and Linux SDK candidates with SHA-256 sidecars, then obtain
   independent download/build reproduction.
5. Remove the remaining inherited non-preamble configuration canvas and prove
   a from-scratch image.
6. Complete the fabric AHB master, DMA handshake, wider MCU GPIO/peripheral
   boundary, and analog-driver workstreams.

## Downloadable SDK

- [ ] Publish pinned Windows and Linux archives containing AGaMEMnon, Yosys,
  AGRV2K nextpnr/runtime, RISC-V GCC, examples, licenses, and SBOMs.
- [ ] Publish SHA-256 sidecars and exact source/build provenance for each
  hosted artifact.
- [ ] Independently download and reproduce the offline diagnostic, MCU build,
  strict FPGA+MCU build, bitgen, and hardware-free programming-plan smoke on
  both hosts.
- [ ] Decide and state whether each archive is build-only or includes the
  paired qualified OpenOCD programming tool.

## MCU SDK

- [ ] Grow open drivers for RTC, flash, CAN, USB, ADC, DAC, comparators,
  Ethernet, and fabric/DMA request use cases.
- [ ] Add non-destructive qualification programs and evidence for each
  supported hard peripheral.
- [ ] Qualify supervised watchdog behavior and the existing DMA/CRC candidates
  before promoting their runtime claims.

## FPGA flow

- [ ] Decode and emit every required non-preamble reset/default field instead
  of inheriting the remaining tile-grid canvas.
- [ ] Broaden BRAM modes, sites, initialization, writes, output registers, and
  collision behavior; first resolve the current x9 terminal/control failure.
- [ ] Expand dedicated-carry seed/spill corridors and multi-chain placement.
- [ ] Replace conservative mux-family timing bounds with native wire, skew,
  IO, BRAM, hard-block, package, and PVT models.
- [ ] Hardware-qualify L100, L64, and Q32 independently.
- [ ] Complete the unfinished MCU/fabric items in
  [docs/MCU_FABRIC_ROADMAP.md](docs/MCU_FABRIC_ROADMAP.md).

## Persistent deployment and recovery

- [ ] Qualify option-byte programming with complete backup, power-cycle,
  readback, restoration, and flash-independent recovery evidence.
- [ ] Prove uncompressed boot from a fully open-generated image on a blank or
  restored device.
- [ ] Complete target-side qualification of the Pico UART mask-ROM transport,
  including interrupted erase/program recovery.
- [ ] Keep the flash-resident USB uploader explicitly separate from recovery
  transports in every command and document.

## Community qualification

- [ ] Add independently reproduced boards, probes, transports, clocks, and
  tool versions to the qualification records.
- [ ] Replace the historical malformed PIN_26 hash exception with a fresh
  retained-artifact qualification record rather than editing history.
- [ ] Keep support claims, packaged behavior, README, status matrix, and all
  active roadmaps synchronized for each release candidate.
