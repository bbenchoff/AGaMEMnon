# MCU/fabric integration roadmap

This file lists only unfinished work at the boundary between the AG32 MCU
subsystem and the AGRV2K fabric. Current support is recorded in
[STATUS.md](STATUS.md), and completed experiments belong in qualification
ledgers rather than this roadmap.

A boundary feature is not complete until its route, encoding, public
interface, offline regression, protocol behavior, package scope, and any
electrical claim are independently qualified.

## Interface-model closure

- [ ] Publish one machine-readable manifest for every MCU/fabric signal,
  including direction, width, clock domain, hard BEL, recovered corridor,
  encoding table, public wrapper, software state, silicon state, and
  provenance.
- [ ] Generate consistency checks across the manifest, chip database, packer,
  bit generator, simulator, support matrix, and documentation.
- [ ] Replace any remaining instance-name parsing or experiment-only binding
  with stable typed primitives or wrappers.
- [ ] Make unsupported widths, flattened offsets, routes, and package claims
  fail before placement or image generation.

## External AHB slave

### Clock, reset, and stop

- [x] Isolate the registered-slice field that left the strict-open
  bus-clocked design static. The pure-open flow now uses qualified direct-D
  self-feedback at X14Y11 slices 4 through 7. An explicit three-bit counter
  observes all eight HRDATA[2:0] states under the default
  `bus_clk = sys_gck` topology.
- [x] Qualify default-topology bus-clock frequency and edge count with a
  silicon state source. A 16-bit LFSR advances exactly one step per undivided
  10 MHz MTIME tick across 45 intervals in three runs.
- [x] Qualify a deterministic synchronous reset state and re-arm path. An
  explicit GPIO4.1-fed reset held all 16 LFSR bits at zero for 36/36 reads in
  three runs; both releases advanced and both reassertions returned to zero.
  This does not qualify the hard reset boundary or post-release phase equality.
- [ ] Qualify bus-clock gating.
- [ ] Qualify `resetn` polarity and assertion/deassertion timing against the
  recovered bus clock.
- [ ] Characterize `sys_clock` and `stop` polarity, gating, wake behavior, and
  ownership separately from `bus_clock`.

### Request phase

- [ ] Qualify every request control and address lane in one protocol-valid,
  bus-synchronous endpoint rather than isolated route probes.
- [ ] Verify runtime behavior of `HADDR[31:0]`, `HWRITE`, `HWDATA[31:0]`,
  `HREADY`, `HTRANS`, `HSIZE`, and `HBURST` across the supported aligned
  transfers.
- [ ] Establish fixed-window behavior for address bits outside the directly
  exercised range without inferring semantics from static routing.
- [ ] Recover a simultaneous logic-input corridor for `HADDR[0]` before
  enabling byte access in the hard-port wrapper.

### Sequential register bank

- [x] Qualify an isolated HADDR[5]-to-logic ingress corridor. The pure-open
  HADDR[5:4] XOR passes 256/256 addresses; this is a route/logic claim, not a
  register-bank or protocol claim.
- [ ] Close a strict build of the full bus-clocked register bank. A strict
  two-bit HADDR2-tagged posted-storage image now routes with zero unmapped PIPs
  and passes all four values, immediate write/read, back-to-back newest-write
  forwarding, and offset isolation; extend that complete footprint lane by
  lane without reverting to hard-input fanout.
- [ ] Expand beyond the current 8-bit writable-data boundary only after a
  simultaneous wider HWDATA logic capture routes and encodes exactly.
- [ ] Qualify reset, aligned halfword/word reads and writes, back-to-back
  transfers, a controlled wait state, and an error address on silicon.
- [ ] Qualify the ID, writable scratch, read-only counter, and write-one-to-
  clear status behavior without relying on a package pin.

## Fabric-to-MCU interrupts

- [x] Route four independent `local_int[3:0]` sources simultaneously without
  shared-source assumptions or corridor conflicts. Four non-overlapping paths
  delivered causes 16–19 independently on L48; exact path fields also emit
  through one strict-open all-low route smoke.
- [ ] Characterize pre-configuration/reset state and clock-domain requirements.
- [ ] Place pending, mask, acknowledge, and re-arm registers behind the
  External-AHB slave.
- [ ] Run an SRAM-only MCU program that independently counts, clears, and
  re-arms all four causes.
- [ ] Treat `EXT_INT0..7` as unconnected hypotheses until a wrapper or oracle
  proves a fabric path.

## Fabric AHB master

- [ ] Route dynamically independent sources for all request qualifiers,
  `HADDR[31:0]`, and `HWDATA[31:0]`.
- [ ] Prove simultaneous full-width response consumption rather than combining
  bounded per-lane route evidence.
- [ ] Bind the protocol core to a strict AG32 boundary wrapper with reset-idle
  behavior, bounded timeout, and error reporting.
- [ ] Qualify read-only reserved-SRAM transactions under zero wait, inserted
  wait, error response, and timeout.
- [ ] Permit writes only after read-only qualification, initially to a bounded
  initialized SRAM window with canaries on both sides.
- [ ] Qualify bounded writes with no canary damage under zero-wait,
  inserted-wait, and error-response cases.

## DMA sidebands

- [ ] Derive request/clear/terminal-count polarity, pulse timing, channel
  association, and handshake semantics from firmware or vendor code.
- [ ] Route at least two independent request sources without relying on the
  shared safe-low tree; record any irreducible corridor conflict.
- [ ] Qualify every request and response channel on silicon.
- [ ] Deliver a small fabric FIFO plus MCU DMA example with synchronization,
  timeout, terminal-count, clear, overrun, and recovery reporting.

## GPIO and hard-peripheral routes

- [x] Close the L48 GPIO5 hard-boundary fault. A differential lane-0 oracle
  and lane-1 bisection proved zero-filled inactive `BBMUXS` terminals unsafe.
  Pure-open data/OE lanes 0 and 1 now emit terminal 8 on the seven inactive
  groups, preserve the active input-2 route, and both return `[0,0,1,0]`.
- [ ] Qualify additional GPIO input, output, and output-enable paths plus
  simultaneous multi-lane use on the exact L48 bench before generalizing a
  GPIO matrix.
- [ ] Recover a fourth independently sourced left-edge OE trunk, then
  electrically qualify the four-link node. Offline controls expose three
  shared trunks for four enables; terminal alternatives alone do not remove
  that ownership conflict, so the unchanged build remains fail-closed.
- [x] Model the L48 hard-HSE package input as a PCF-bindable clock resource
  without treating it as an ordinary fabric IOB.
- [ ] Recover and qualify named UART and SPI routes, followed by open-drain I2C
  and externally transceived CAN paths.
- [ ] Bind each interface to its required IO electrical modes and keep package
  qualification separate.

## Analog blocks and cross-links

- [ ] Add independent MCU register definitions, open drivers, package pin
  tables, and non-destructive tests for ADC, DAC, and comparators.
- [ ] Extend exact typed routing beyond the initial ADC0 read-only lanes while
  preserving distinct hard-pin identities.
- [ ] Determine ownership, reset state, and safe idle behavior before driving
  an analog hard-block input from fabric or loading a board image.
- [ ] Recover and qualify ADC clocks, DAC data, comparator outputs, RTC clocks,
  and timer/trigger cross-links.
- [ ] Expose only connections with exact selector evidence and qualified
  electrical behavior.

## Next bounded contribution units

Units 1 through 5 gate the 16-node hypercube board tracked at the top of
[ROADMAP.md](../ROADMAP.md).

1. Strict sequential register-bank build and SRAM-only trial; deterministic
   GPIO-fed reset state and exact default rate are closed, while hard
   `MCU_RESETN` remains separate.
2. Recover and qualify hard `MCU_RESETN` polarity and timing.
3. AHB-backed `local_int` pending/mask/acknowledge/re-arm behavior; independent
   four-source routing and causes 16 through 19 are already qualified.
4. Fabric-driven output-enable and open-drain pad oracle on one L48 pad
   pair.
5. Named hard-UART TX/RX route recovery, or a register-bank soft-UART
   loopback trial as the supported alternative.
6. Read-only fabric-master boundary wrapper and reserved-SRAM trial.
7. One complete DMA request/response handshake channel.
8. Broaden GPIO5 beyond qualified data/OE lanes 0 and 1 plus input lane 2;
   preserve the explicit inactive-terminal emission policy.
9. One MCU-only analog driver and non-destructive bench record.
