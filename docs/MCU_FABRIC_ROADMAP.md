# MCU/fabric integration roadmap

This document tracks the boundary between the AG32 MCU subsystem and the
AGRV2K programmable fabric. It is narrower and more implementation-oriented
than the project-wide [roadmap](../ROADMAP.md).

Dates are intentionally absent. Reverse-engineering milestones close when
their route data, open-flow support, tests, and hardware evidence are
reproducible. A recovered vendor route is evidence, but it is not by itself a
supported feature.

## Current baseline

The MCU/fabric interface is more complete than the original four-bit inverter
prototype, but it is not yet a general peripheral interface.

| Boundary | Current state | Important limitation |
|---|---|---|
| MCU GPIO bridge | Four-bit GPIO4 loopback is silicon-qualified; one GPIO5 data/OE/input unit has exact L100/L48 strict-open routes | The L48 open image leaves the GPIO5 data LUT input stuck low on silicon; neither result is a general GPIO matrix |
| External AHB read (`fabric -> MCU`) | All 32 `HRDATA` lanes are silicon-qualified; fixed `HREADYOUT` and `HRESP` routes build in the strict open flow | Response behavior and a protocol-valid silicon endpoint are not qualified |
| External AHB write (`MCU -> fabric`) | All 32 `HWDATA` lanes are silicon-qualified in four-bit groups; all 32 `HADDR` lanes, `HWRITE`, and all remaining request-control routes build in the strict open flow | The new controls/address lanes and a bus-synchronous endpoint are not silicon-qualified |
| Fabric AHB master | Response `HREADYOUT`, `HRESP`, and all 32 `HRDATA` lanes have typed exact strict-open routes in bounded groups | Simultaneous full-width ingress, all requests, protocol logic, and silicon qualification are open |
| Fabric interrupts | All four `local_int` lanes have exact open-flow support and differential L48 qualification; a shared safe-low image clears all four simultaneously | Four independent simultaneous source nets and AHB acknowledgement/re-arm remain open |
| Fabric DMA requests | All 16 request endpoints have exact typed shared-safe-low strict-open routes; all eight `DMACCLR`/`DMACTC` response lanes route independently and simultaneously | Independent request sources, semantics, and silicon qualification remain open |
| Hard analog blocks | ADC0 result bits 0/1 and EOC have distinct exact typed read-only strict-open routes; broader ADC/DAC/comparator capability and package pins are documented by AGM | No register driver, ownership model, board qualification, electrical evidence, or driven fabric cross-link is supported |

The checked-in `examples/firmware/loop_macro.v` is the interface contract to
investigate. It names:

- the MCU-master/fabric-slave `mem_ahb_*` port;
- the fabric-master/system-slave `slave_ahb_*` port;
- four direct `local_int` lines; and
- four channels each of DMA request, last-request, clear, and terminal-count
  sidebands.

Signal names establish hypotheses, not physical mappings. Every signal still
needs a route oracle and a silicon test.

## Evidence gate for every recovered signal

A signal is complete only when all of these artifacts exist:

1. A minimal vendor-oracle design that holds or toggles only the target signal,
   with tool version and source recorded.
2. A logical-to-physical manifest entry: direction, width, internal lane/BEL,
   complete route corridor, configuration fields, and provenance.
3. Open architecture exposure with exact placement and fail-closed selector
   handling.
4. A stable RTL-facing name or wrapper that does not depend on accidental
   placement.
5. Bitgen support and hardware-free regression tests.
6. A protocol-aware silicon test with artifact hashes and an append-only
   evidence record.
7. A support-matrix and user-documentation update that states the exact
   package, board, clock, and behavioral boundary.

Broad correlation is useful for discovery. Promotion requires isolated or
protocol-valid evidence.

## Milestone 0: freeze the interface inventory

Create one machine-readable manifest for every known MCU/fabric signal. Seed
it from the existing AHB lane CSVs and the vendor wrapper. Record unknown
signals explicitly instead of assigning guessed BEL numbers.

Deliverables:

- logical names, directions, widths, clock domains, vendor wrapper names, and
  current evidence state;
- a generated consistency test covering the chip database, packer bindings,
  bitgen maps, simulator, and documentation;
- typed RTL wrappers or attributes for fixed hard-interface lanes, replacing
  instance-name parsing as the public contract; and
- a small oracle-generation convention so contributors can investigate one
  lane without changing the test methodology.

Definition of done: the manifest can answer which lanes are absent, recovered,
build-supported, and silicon-qualified without reading C++, Python, and CSVs
side by side.

## Milestone 1: complete the External AHB slave

This is the highest-value milestone. It lets MCU firmware use ordinary FPGA
register banks and small peripherals at the `0x60000000` window.

### 1A. Recover the clock and reset boundary

Status: the vendor wrapper's `bus_clock == sys_gck` alias and per-tile clock
tree are recovered, and typed `MCU_BUS_CLOCK`/`MCU_SYS_CLOCK` sources pass a
strict open-flow sequential smoke. A typed `MCU_RESETN` source now reaches
ordinary fabric logic and passes combinational and sequential strict smokes.
The typed observational `MCU_STOP` source reproduces its isolated six-edge
vendor loopback with five exact mapped fields and zero unmapped. A native L48
vendor TFF toggles in traffic-assisted SRAM trials, but the equivalent open TFF
and a six-stage open divider are stuck high. Silicon reset, typed clock support,
stop polarity, clock gating, and wake behavior remain open.

Time-box record: the vendor positive control produces 34 high and 30 low
GPIO4.2 samples in two repeated runs while issuing one through four reads at
`0x60000000`. The strict-open TFF produces 64 high and zero low twice with the
same firmware; FCB status, read completion, sentinel, and DAP recovery pass.
The next experiment is a full named-field diff with vendor and open TFFs forced
onto one slice, covering global/SeamMUX/TileClkMUX and registered-slice mode.
Do not retry equivalent images before isolating one unexplained field.

Map and qualify `bus_clock` and `resetn`; characterize `sys_clock` and `stop`
separately. Do not clock an AHB endpoint from the fabric PLL merely because a
simple test happens to work across the clock boundary.

Deliver a bus-clock primitive, reset behavior, clock/reset simulation model,
and a silicon counter that proves deterministic reset and one update per bus
clock.

### 1B. Recover the remaining request controls

Status: physical routes, exact selectors, fixed public bindings, and strict
hardware-free route smokes are complete for every request control and all 32
HADDR bits. Protocol behavior and silicon qualification remain open.

Map and qualify:

- `mem_ahb_hready`;
- both `mem_ahb_htrans` bits;
- `mem_ahb_hsize[2:0]`; and
- `mem_ahb_hburst[2:0]`.

Reconfirm the already recovered `HADDR`, `HWRITE`, and `HWDATA` lanes in the
same bus-clocked endpoint. Determine whether address bits outside `[27:2]` are
hard-decoded, constant, or physically available rather than guessing them.

The full-width HADDR oracle proves distinct physical roots for `[1:0]` and
`[31:28]`. Their compact six-lane promotion routes in strict mode, and 172
field bits match the vendor image. Runtime values at the fixed fabric window
remain a silicon qualification item.

The promoted control table covers all ten request-control bits. Two lanes
cross their recovered combinational buffer sites; the strict smoke constrains
those sites explicitly and builds without vendor routing artifacts.

### 1C. Recover the response controls

Status: physical routes, exact selectors, fixed public bindings, and the
simultaneous hardware-free route smoke are complete. Wait/error semantics and
silicon qualification remain open.

Map and qualify:

- `mem_ahb_hreadyout`; and
- `mem_ahb_hresp`.

Start with a constant-ready, OKAY-only endpoint. Then add controlled wait
states and an error address. A stuck default in the baseline image does not
count as a mapped fabric output.

A reusable full-port wrapper and constant-ready, OKAY-only endpoint pass
behavioral simulation. The integrated strict build remains follow-up work:
shared constants route all 32 HRDATA lanes over 219 strict pips, and dedicated
HREADYOUT/HRESP sources route individually, but the current greedy packer does
not yet find a joint allocation. Control-first routing strands HRDATA[18],
while HRDATA-first routing strands HRESP. This is recorded as a packer
source/path-allocation gap; the endpoint is not approved for hardware yet.

### 1D. Ship a reusable register-bank endpoint

Provide an RTL wrapper and MCU header generator for word, halfword, and byte
registers. Use the existing Python and synthesizable AHB models as the oracle,
but bind them to the real hard-interface wrapper.

Status: the vendor-independent protocol core, real hard-interface wrapper, and
C header generator are implemented. Hardware-free RTL tests cover the required
ID, scratch, counter, and W1C registers, aligned subword/word transfers,
inserted waits, back-to-back writes, reset, and explicit error responses. The
tests also fixed a model deadlock in which the wait counter was incorrectly
gated by the slave's own low `HREADY`. Full strict packing and silicon remain
open at the response-source allocation gap described above. See
[MCU_AHB_REGISTER_BANK.md](MCU_AHB_REGISTER_BANK.md).
A fresh bounded full-port strict build exhausted its 180-second allocation
budget without a routed result; no additional seeds were attempted. The next
experiment is the joint allocator, not more greedy seed retries.

Definition of done: silicon passes aligned byte/halfword/word reads and writes,
back-to-back transfers, a programmed wait state, and an error response. The
example must expose at least an ID register, writable scratch register,
read-only counter, and write-one-to-clear status register.

## Milestone 2: fabric-to-MCU interrupts

Status: all four lanes have complete nine-edge vendor corridors, eight exact
configuration fields per lane, typed `MCU_LOCAL_INT0..3` bindings, strict
high/low open-flow smokes, and differential L48 silicon qualification. They
are active-high and level-sensitive, map in order to `mie/mip[19:16]`, and
report causes 19:16. A shared constant-low source also routes to every sink in
one strict image and clears all four pending bits simultaneously.

The isolated routes share most of one physical source corridor. Consequently,
individual-lane behavior and a shared safe-low tie-off are supported, while
four independent simultaneous source nets remain an explicit routing task.

Time-box record: a four-source vendor oracle using four distinct HADDR-derived
functions and four GPIO observations assigned every LUT to `(14,12:0)` and
failed with three duplicate-slice errors before routing. No further unplaced
variants were attempted. The next experiment needs explicit source placement
or a joint open-flow corridor allocator; this failure is not evidence of a
physical four-lane conflict.

Recover `local_int[3:0]` before investigating other interrupt hypotheses. The
official MCU documentation identifies these as direct core-local interrupts
controlled by `mie[19:16]`; the vendor fabric wrapper exposes the same four
lanes.

Deliverables:

- exact routes and fixed fabric-output bindings for all four lanes;
- polarity, level/edge behavior, reset state, and clock-domain characterization;
- an interrupt source block with pending, mask, and write-one-to-clear
  registers behind the External AHB slave; and
- an SRAM-only MCU qualification program that counts, clears, and re-arms each
  source without relying on a package pin.

Investigate `EXT_INT0..7` only as a separate follow-up. They are PLIC sources
37 through 44, but the current fabric wrapper does not prove that they are
fabric-connected.

Definition of done: each local interrupt is independently generated by fabric,
handled once by the MCU, acknowledged through the AHB register block, and
re-triggered on silicon.

## Milestone 3: recover the fabric AHB master

This port permits FPGA logic to access MCU-visible SRAM and peripherals. It is
also the highest-risk interface because a bad route or state machine can issue
unintended writes.

Status: the read-only response routes are mapped per lane. `HREADYOUT`,
`HRESP`, and all 32 `HRDATA` lanes have typed exact bindings. Eight bounded
groups cover lanes 1–31 with 85 exact fields and 732 matching vendor selector
checks; every strict group build has zero unmapped. This is hardware-free
routing evidence; it does not authorize or claim a fabric-master silicon
transaction.

A full 32-lane forced-LUT oracle is time-boxed because the vendor placer fixes
all 32 LUTs at `(1,1,0)` and over-packs one tile. Direct/unary variants expose
only hard-to-hard paths. Bounded reductions completed the per-lane map, but
the isolated groups reuse LUT ingress sites and do not prove a simultaneous
32-bit consumer. Recover that allocation with explicitly placed multi-LUT
oracles rather than retrying the failed form.

Recover the vendor `slave_ahb_*` signals in this order:

1. response inputs: `HRDATA[31:0]`, `HREADYOUT`, and `HRESP`;
2. request qualifiers: `HSEL`, `HREADY`, `HTRANS`, `HSIZE`, `HBURST`, and
   `HWRITE`;
3. address and write data: `HADDR[31:0]` and `HWDATA[31:0]`.

Qualification must initially be read-only. After that passes, allow writes
only to a reserved, initialized SRAM window with canaries on both sides. Never
use flash, option bytes, clock control, GPIO, or an active peripheral as the
first write target.

Deliverables:

- a synthesizable single-transfer master with timeout and error reporting;
- a behavioral system-slave model covering wait and error responses;
- arbitration/backpressure tests and an explicit reset-to-idle guarantee; and
- a silicon example that copies a bounded block between fabric BRAM/registers
  and reserved MCU SRAM.

Definition of done: deterministic SRAM reads and bounded SRAM writes pass with
zero canary damage under zero-wait, inserted-wait, and error-response cases.

## Milestone 4: DMA request sidebands

Status: all 16 fabric-to-MCU request endpoints have a narrow shared-source
strict-open promotion. A bounded oracle reconstructs 128 signal-expanded
edges and 23 exact configuration fields; all 214 named selector bits match the
vendor image. One constant-low source routes to all 16 typed sinks with 39
data pips, 23 mapped configurable pips, and zero unmapped.

All eight MCU-to-fabric `DMACCLR[3:0]` and `DMACTC[3:0]` response lanes also
have exact typed support. Four independent clear/terminal-count pairs route
simultaneously into fixed observation LUTs through 26 exact mapped pips with
zero unmapped; all 204 named selector bits match the vendor image.

The request oracle used one source net, so this does not prove independently
routable request bits. No polarity, pulse width, channel
association, or DMA protocol behavior is qualified. The vendor request image
is unsafe for hardware; silicon work must start with a bounded SRAM-only
single-request harness after the handshake is derived.

Independent-source recovery is time-boxed. If a bounded two-source oracle
cannot avoid corridor conflicts, retain the shared-low tie-off as the supported
boundary, document the conflict, and continue with response channels 1–3 or a
different roadmap unit.

Recover the four external DMA channels after the bus clock and interrupt paths
are trustworthy:

- fabric outputs: `DMACBREQ`, `DMACLBREQ`, `DMACSREQ`, and `DMACLSREQ`;
- fabric inputs: `DMACCLR` and `DMACTC`.

The qualification design must obey the documented request/clear handshake and
must include synchronization when the fabric source is outside the DMA clock
domain.

Deliver a small fabric FIFO plus MCU DMA example. Start with single requests,
then burst requests, then last-transfer semantics.

Definition of done: all four channels independently transfer deterministic
patterns to or from reserved SRAM, observe clear/terminal-count responses, and
report overrun or timeout rather than hanging.

## Milestone 5: broaden MCU GPIO and package routing

Separate two questions that are easy to conflate:

1. Which MCU or hard-peripheral signal crosses the MCU/fabric boundary?
2. Which fabric IO cell and package pin does the active image route it to?

Build an inventory for GPIO banks and useful hard peripheral signals from
minimal vendor designs. Qualify routes on one exact L48 board first. Promote
other packages only with their own evidence.

One additional internal boundary unit is promoted with exact L100/L48 routing:
`gpio5_io_out_data[1]` and `gpio5_io_out_en[1]` independently feed a fixed XOR
LUT and return through `gpio5_io_in[2]`. The strict open build routes the same
nine edges, maps all eight configurable fields, leaves zero pips unmapped, and
matches all 65 vendor selector bits. The typed surface is deliberately limited
to those three exact signals. The vendor L48 image passes the SRAM-only
reachable XOR sweep, but three open-image runs return `!out_en`; the LUT data
input is effectively stuck low despite matching the vendor LUT mask,
`CFG_CARRY_CRL[0]`, and route selectors. Silicon qualification is deferred.
The next bounded experiment is a named-field diff around tile `(9,4)` and its
MCU boundary, then one single-variable oracle for the first unexplained
data-ingress field. Equivalent image retries are explicitly skipped.

Deliverables:

- input, output, and output-enable paths for additional MCU GPIO bits;
- board/fabric manifests pairing named peripheral routes with an image hash;
- safe UART and SPI routes, followed by open-drain I2C and externally
  transceived CAN; and
- IO electrical-mode support needed by those routes: tri-state/open-drain,
  pull-up, drive strength, slew, and Schmitt settings where recovered.

Definition of done: firmware plus a named fabric image can request a supported
board route without implying that the same pin number works on another package
or image.

## Milestone 6: analog hard blocks and fabric cross-links

Do not model ADCs, DACs, or comparators as LUT-synthesizable FPGA cells. Split
the work into two layers.

### 6A. MCU-controlled analog support

Add open register definitions and polling drivers for ADC, DAC, and comparator
blocks. Add package-specific analog pin tables, clock/reset setup, VDDA/VREF
requirements, and non-destructive qualification programs.

A suitable bench can loop a DAC through a resistor to an ADC input and use a
known threshold for comparator tests. Qualification must record voltage range,
reference, load, and package pin.

### 6B. Fabric/analog cross-links

Treat the documented fabric relationships as separate reverse-engineering
targets: ADC clocking from the interconnect, DAC digital data from the fabric,
comparator outputs into the fabric, RTC local clocking, and any timer/trigger
paths. Determine which are fixed connections and which require fabric
configuration.

Expose only confirmed connections as typed hard-block sideband primitives.

Definition of done: the MCU drivers work independently first; each advertised
fabric cross-link then has an isolated route, an electrical or digital silicon
oracle, and a precisely scoped support entry.

## Suggested contribution units

The roadmap is intentionally divisible. Good independent issues are:

1. interface manifest and generated consistency checks;
2. `bus_clock` and `resetn` oracle/recovery;
3. remaining External AHB request controls;
4. `HREADYOUT`/`HRESP` response controls;
5. reusable AHB register-bank wrapper and MCU header generator;
6. one `local_int` lane followed by the remaining three;
7. read-only fabric-master response path;
8. bounded SRAM fabric-master writes;
9. one complete DMA request/acknowledge channel;
10. one additional MCU GPIO or named hard-peripheral route; and
11. MCU-only ADC, DAC, or comparator driver and bench record.

Contributors should open an issue with the target signal, oracle source, exact
part/package/board, and intended observation before beginning a large recovery
campaign. This keeps architecture integration and silicon work from being
duplicated while allowing oracle mining to proceed independently.
