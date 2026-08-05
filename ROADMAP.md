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
   qualifier, and exact HWDATA[0], HWDATA[1], HWDATA[2], HWDATA[3], HWDATA[4], HWDATA[5],
   HWDATA[6], and HWDATA[7]
   registered consumers are qualified. A complete byte-wide posted-storage
   footprint passes all 256 values, immediate write/read, and back-to-back newest-write
   forwarding; a registered HADDR[2] tag also distinguishes writable offset 0
   from ignored offset 4. The complete writable-data byte is therefore closed;
   the full bank now stops at composing its four-register/reset footprint with
   wait-state and error-response classes. The first proposed combinational
   identity root (X14Y12 slice15 for HWDATA6) remains a retained silicon negative.
   Direct HWDATA0 at its lane-zero storage terminal and all four HWDATA5
   terminals at X14Y11 slice5 are live. Direct control delivery to slice5 was
   eliminated across I0/I1/I2, two buffer assignments, and a local qualifier.
   The qualified architecture instead keeps slice5 as the HWDATA5 capture,
   applies commit/hold in a separate next-state LUT, and stores one input at
   slice8. Lane6 folds commit/hold into its exact X14Y12 slice15 consumer
   (I0=HWDATA6, I1=commit, I3=own Q) while the constant HREADYOUT source uses
   a separate strict corridor. Lane7 folds HWDATA7, commit, and own-Q hold
   into the exact X14Y11 slice0/I1 consumer. Immutable ID at offset 0 and the
   writable scratch byte at offset 4 are silicon-qualified. A standalone
   read-only three-bit counter at offset 8 is also silicon-qualified with a
   deterministic modulo-eight sequence, ignored writes, and offset isolation.
   A standalone one-bit W1C status at offset C is silicon-qualified with an
   internal software-set hook, hold/clear/re-arm behavior, and offset
   isolation. All four classes and GPIO4.1-fed synchronous reset are now
   integrated. A separate immutable-ID endpoint also qualifies exactly one
   controlled wait on each single aligned word read or ignored write, while
   preserving ID `0x4d` and OKAY response. Composing that response controller
   with writable lane6 remains a retained negative, not a dead-PIP claim. An
   exact lane6-only commit-stage-F retry also retained bit-6 corruption and
   exculpates combinational commit phase alone. A strict two-wait retry
   reproduced the original signature and exculpates response-release duration;
   restoring own-Q to its pure-open-qualified I3 pin also had no effect and
   exculpates feedback-pin placement; none may be rerun unchanged;
   controlled waits in the writable bank, bursts, and byte/halfword transfers
   remain open. **RETIRED:** treating fabric HRESP as a deterministic MCU
   access fault on the attached L48. An exact two-cycle response and wait were
   electrically active but produced zero load/store traps and contaminated the
   following transfer; the public boundary therefore makes no such claim.
2. **Closed for the integrated one-hot command subset:** One strict AHB image
   selects causes 16–19 with HWDATA[3:2] and applies mask/ack/set commands in
   HWDATA[1:0]. An SRAM-only run counted three exact traps per cause,
   acknowledged each, re-armed twice, held pending behind the mask, and reset
   cleanly. The image deliberately shares one pending/mask state across the
   selected output; simultaneous per-lane pending storage and state readback
   are not claimed. Reads fail closed to zero.
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
   address 0..255 through data bits 0..2. Data bits3 and 4 are independently
   qualified through exact readback corridors. Data bit5 is also qualified
   after correcting its graph from a dead q4-shaped path to the exact
   BufMUX13/RMUX92/RMUX75/RMUX20/BBMUXE07 corridor. HADDR11/AddressA12
   is qualified by alternating word addresses 0 and 512 through its X14Y7
   route-through. Data bits6, 7, and 8 are also qualified by full-width INIT
   projections that match word-address bits0, 1, and 2 respectively for
   256/256 reads. The x9 narrow-width wrapper maps them to physical
   DataOutA15, DataOutA16, and DataOutA7. An exact paired route now also
   qualifies q4 and q5 simultaneously after correcting the source-dependent
   RMUX43-to-BBMUXE06 selector. An atomic reservation of that qualified q4
   corridor now enables the strict-open simultaneous bundle, which returns
   all 256 identity words over HADDR[9:2]. Continue breadth with the remaining high
   address lanes/range, writes, output-register modes, other sites, and
   collision behavior; do not
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
  collision behavior. All nine X13Y4 read-only x9 data bits are qualified over
  their exercised address projections, q4/q5 are qualified simultaneously on
  one exact paired route, and HADDR11/AddressA12 is qualified at word
  addresses 0/512. A simultaneous strict-open output bundle also returns all
  identity values 0..255 exactly once. Next are the remaining high-address
  lanes/range.
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
