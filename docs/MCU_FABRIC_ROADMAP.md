# MCU/fabric integration roadmap

This file lists only unfinished work at the boundary between the AG32 MCU
subsystem and the AGRV2K fabric. Current support is recorded in
[STATUS.md](STATUS.md), and completed experiments belong in qualification
ledgers rather than this roadmap.

A boundary feature is not complete until its route, encoding, public
interface, offline regression, protocol behavior, package scope, and any
electrical claim are independently qualified.

## Campaign rebase (2026-08-24)

The broad campaign changes the order of this roadmap. X13Y12 ingress coverage
is no longer the immediate blocker, but fresh width is still not closed:

- `regbank16` remains a bounded no-image result downstream of the recovered
  ingress;
- `addsub16` reaches the density policy and exposes placement divergence;
- a 256-bit user-state design routes only after 12 failed attempts and then
  diverges on silicon at transaction two; its structural form does not route;
- a five-region state composition evaluates correctly from the routed netlist
  but returns zero state on silicon;
- the retained public32 map remains exact evidence and its composer now
  reproduces that reviewed checkpoint without accepting a new candidate.

Therefore the next boundary milestone is not “add another lane.” It is a
generalized placement/routing improvement plus an independently controlled
physical-correctness explanation for wide state. Do not use route pins,
research selector admission, timeout-only retries, or a reviewed-hash repin as
closure. AHB master/DMA work remains behind this gate.

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
- [x] Qualify default-topology bus-clock advance ratio and edge count with a
  silicon state source. A 16-bit LFSR advances exactly one step per undivided
  MTIME tick across 45 intervals in three runs (a 1:1 ratio; the
  absolute rate is an open question, see
  [MCU_CLOCKS.md](MCU_CLOCKS.md#external-ahb-bus-clock)).
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
- [x] Recover a simultaneous logic-input corridor for `HADDR[0]` before
  enabling byte access in the hard-port wrapper. The resettable sticky
  discriminator qualified simultaneous HADDR0 ingress, and the aligned
  byte/halfword record enabled gated byte access in the wrapper.

### Sequential register bank

- [x] Qualify an isolated HADDR[5]-to-logic ingress corridor. The pure-open
  HADDR[5:4] XOR passes 256/256 addresses; this is a route/logic claim, not a
  register-bank or protocol claim.
- [x] Close a strict build of the full bus-clocked register bank. The
  complete-byte waited bank composes ID/scratch/counter/W1C with GPIO reset,
  one controlled write wait, exact zero-extended 32-bit reads, and aligned
  byte/halfword semantics, all silicon-qualified per the register-bank ledger.
- [x] Expand the writable-data boundary to the exact retained scratch16 at +4;
  its word/halfword/independent-byte semantics compose with the public32 map.
- [ ] Generalize beyond that pinned 16-bit state only after a simultaneous
  wider HWDATA logic capture routes and encodes exactly.
- [x] Qualify reset, aligned halfword/word reads and writes, back-to-back
  transfers, and a controlled wait state on silicon. Deterministic error
  signaling stays retired: HRESP completes protocol-correctly but raises no
  MCU access fault on the attached L48.
- [x] Qualify the ID, writable scratch, read-only counter, and write-one-to-
  clear status behavior without relying on a package pin.

## Fabric-to-MCU interrupts

- [x] Route four independent `local_int[3:0]` sources simultaneously without
  shared-source assumptions or corridor conflicts. Four non-overlapping paths
  delivered causes 16–19 independently on L48; exact path fields also emit
  through one strict-open all-low route smoke.
- [x] Characterize pre-configuration/reset state and clock-domain
  requirements. Post-reset/pre-load local `mip` is zero with `mie` clear and
  armed; set/acknowledge each take exactly 21 MTIME ticks at the default
  bus clock. Those are tick counts, not a frequency. Not a POR or
  alternate-clock claim.
- [x] Place pending, mask, acknowledge, and re-arm registers behind the
  External-AHB slave. Per-lane and integrated one-hot command banks qualify
  mask/ack/set with re-arm and masked hold; state readback remains open.
- [ ] Qualify four simultaneously retained per-lane pending/mask stores and
  state readback; the integrated one-hot command bank already counts, clears,
  and re-arms all four causes in one SRAM-only run with shared selected-lane
  state.
- [ ] Treat `EXT_INT0..7` as unconnected hypotheses until a wrapper or oracle
  proves a fabric path.

## Fabric AHB master

- [x] Provide a vendor-independent, reset-idle, read-only single-transfer core
  with bounded timeout and explicit response/error reporting.
- [x] Fail closed before placement on every request-control topology except the
  exact pinned shared-safe-low oracle; this is containment, not a transaction
  qualification.
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
- [x] Recover four independently sourced left-edge OE trunks (the strict node
  image composes them at 102/102 mapped PIPs) and electrically qualify
  release/drive-low and active-high OE polarity through the four distinct
  PIN_25..PIN_28 corridors (retained vendor-routed quad oracle, 2026-08-16).
- [ ] Qualify ordinary open-flow source ingress to the PIN_26..PIN_28 OE
  presentation LUTs, active drive-high, and the complete node's sequential
  phase/readback/UART behavior.
- [x] Model the L48 hard-HSE package input as a PCF-bindable clock resource
  without treating it as an ordinary fabric IOB.
- [x] Recover and qualify named UART, SPI, and open-drain I2C routes. Exact
  L48 images qualify UART0 TX/RX/full-duplex at three nominal rates plus
  7E1/8E1/8O1/8N2 line modes, SPI0 SCK/CSN/MOSI/IO1 against an active slave,
  and I2C0 SDA/SCL against an active open-drain slave including repeated
  START.
- [ ] Qualify an externally transceived CAN path; CAN0 remains
  register-level/self-test only with no bits observed on a wire.
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

## Hard MCU peripherals (MMIO)

These are manufactured hard blocks operated over MMIO by firmware; they consume
no fabric. Qualified results below are SRAM-only, non-destructive runs of the
`examples/riscv_mcu` firmware, recorded in
[`hard_peripheral_evidence.jsonl`](../qualification/hard_peripheral_evidence.jsonl).

- [x] CRC-32/MPEG-2 hard unit: known-answer of `123456789` == `0x0376E6E7`.
- [x] `DMAC0` memory-to-memory single-channel 4-word copy.
- [x] UART0 internal (`LBE`) loopback echoed byte `0xA5`.
- [x] `WATCHDOG0` register snapshot and supervised timeout reset (warm reset,
  `RST_CNTL` bit30 `SYS_RSTF_WDOG` set exclusively).
- [x] CLINT/MTIME machine-timer interrupt taken with `mcause` `0x80000007`.
- [ ] RTC counter advance / timekeeping. The register/config path is confirmed
  (`BDCR` `RTCEN`+LSI-select stick, backup domain writable), but the counter
  does not advance: no low-speed clock runs on this board (an LSI enable or an
  LSE 32 kHz crystal is absent). The driver and probe example ship; timekeeping
  is not claimed.
- [ ] CAN 2.0 on-wire framing (needs an external transceiver) and the Ethernet
  MAC (needs a board PHY) stay hardware-gated; CAN0 has register-level
  configuration and self-test transmit-completion evidence only, with no bits
  observed on a wire.
- [ ] USB host/OTG stays hardware-gated (no host present); the hard USB device
  path is separately exercised by the CDC uploader in
  [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).
- [ ] ADC, DAC, and comparators are fabric-analog blocks (analog IP plus
  routing), not MCU-MMIO peripherals; they remain tracked under
  [Analog blocks and cross-links](#analog-blocks-and-cross-links) above.

## Next bounded contribution units

Units 1 through 5 gate the 16-node hypercube board tracked at the top of
[ROADMAP.md](../ROADMAP.md).

1. Strict sequential register-bank build and SRAM-only trial; deterministic
   GPIO-fed reset state and the exact 1:1 bus-clock-per-MTIME-tick ratio are
   closed (the absolute rate is an open question, see
   [MCU_CLOCKS.md](MCU_CLOCKS.md#external-ahb-bus-clock)), while hard
   `MCU_RESETN` remains separate.
2. Recover and qualify hard `MCU_RESETN` polarity and timing.
3. AHB-backed `local_int` pending/mask/acknowledge/re-arm behavior; independent
   four-source routing and causes 16 through 19 are already qualified.
4. Exact PIN_25 combined-cell constant/local-toggle output enable and ordinary
   stepped external PIN_10 control with simultaneous readback are qualified.
   Next isolate high-rate readback and broader generic/registered OE/open-drain
   behavior; the divergent RMUX20 ingress branch remains unqualified.
5. The register-window soft-UART core passes offline loopback and fail-closed
   protocol regression; compose it with exact L48 routes and run the SRAM-only
   loopback trial before exposing it as the supported alternative.
6. Read-only fabric-master boundary wrapper and reserved-SRAM trial.
7. One complete DMA request/response handshake channel.
8. Broaden GPIO5 beyond qualified data/OE lanes 0 and 1 plus input lane 2;
   preserve the explicit inactive-terminal emission policy.
9. One MCU-only analog driver and non-destructive bench record.
