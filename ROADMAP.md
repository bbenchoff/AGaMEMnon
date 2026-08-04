# Roadmap

This file lists open work only. Current public support belongs in
[docs/STATUS.md](docs/STATUS.md); completed experiments and artifact hashes
belong in the append-only qualification ledgers.

AGaMEMnon prioritizes reproducible first use, recovery safety, and bounded
hardware evidence over broad but unqualified coverage.

## Immediate priorities

The near-term driver is the first integration target: a 16-node hypercube
board whose AG32 nodes remap one UART across four single-wire, half-duplex
fabric links under a global TDMA phase clock. Items 1 through 7 gate that
board and are ordered by dependency.

1. Close and exercise the sequential register-bank endpoint. The pure-open
   `bus_clk = sys_gck` subset now produces 500 distinct states from a 16-bit
   LFSR, measures exactly one LFSR step per undivided 10 MHz MTIME tick across
   45 intervals, and has a qualified GPIO-fed synchronous reset-to-zero and
   re-arm path. Hard `MCU_RESETN`, explicit PLL3 BUSCLK, and unrestricted
   direct-D lowering remain open. HADDR[3:5], the paired HWRITE/HTRANS1
   qualifier, and exact HWDATA[6:7] registered consumers are qualified. The
   unchanged full bank now stops at HWDATA fanout; the first proposed
   combinational identity root (X14Y12 slice15 for HWDATA6) is a retained
   silicon negative. Recover a one-per-lane conducting buffer tree or pipeline
   the data boundary with a separate protocol-timing qualification.
2. Add AHB-backed pending, mask, acknowledge, and re-arm behavior for the four
   `local_int` sources. Simultaneous independent routing and causes 16–19 are
   qualified; the register-bank dependency remains.
3. Qualify fabric-driven output-enable and open-drain pad behavior on L48 so
   one pad can alternate between driving and listening on a shared wire.
4. Extend the qualified L48 pin set to a complete node pinout: four
   bidirectional link pads plus control-UART, TDMA phase-clock, and HSE
   inputs.
5. Recover and qualify hard-UART TX/RX fabric routes, or qualify a fabric
   soft-UART behind the register bank as the supported alternative.
6. Confirm the QFN32 part (AG32VF303KCU6) against the recovered AGRV2K
   device identity, then silicon-qualify the Q32 package on a breakout
   board before any multi-node board is committed.
7. Complete target-side qualification of the Pico UART mask-ROM programmer,
   including interrupted erase/program recovery, as the node programming
   tree.
8. **Closed for the qualified subset:** the apparent x9 terminal/read-control
   fault was incomplete readback-boundary emission. Reverse clone descent
   proved X22Y4 `CFG_IOMUX11[9]` necessary, then localized the remaining
   projection-width loss to six named IMUX/RMUX footprint bits at the two
   characterized route-through sites. Pure-open x9 now returns the expected
   initialized data, and three projections reconstruct every exercised word
   address 0..255. Continue breadth with upper data lanes, addresses 256..1023,
   writes, output-register modes, other sites, and collision behavior; do not
   rerun the eliminated additive field permutations.
9. Publish Windows and Linux SDK candidates with SHA-256 sidecars, then obtain
   independent download/build reproduction.
10. Remove the remaining inherited non-preamble configuration canvas and prove
    a from-scratch image.
11. Complete the fabric AHB master, DMA handshake, wider MCU GPIO/peripheral
    boundary, and analog-driver workstreams. Exact L48 GPIO5 data/OE lanes 0
    and 1 plus input lane 2 are qualified with coherent inactive-terminal
    defaults; broaden beyond that characterized subset next.

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
  collision behavior. The first x9 breadth units are upper data lanes and
  addresses 256..1023; the 0..255 read-only low-three-bit subset is qualified.
- [ ] Expand dedicated-carry seed/spill corridors and multi-chain placement.
- [ ] Replace conservative mux-family timing bounds with native wire, skew,
  IO, BRAM, hard-block, package, and PVT models.
- [ ] Hardware-qualify Q32 first (the 16-node board package), then L100 and
  L64 independently.
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
