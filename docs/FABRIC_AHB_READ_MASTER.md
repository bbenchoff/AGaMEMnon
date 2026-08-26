# Fabric AHB read-master core

`agamemnon/rtl/fabric_ahb_read_master.v` is a vendor-independent, synthesizable
single-transfer AHB-Lite read master. It starts in IDLE after reset, issues
only word-sized `NONSEQ` reads, reports `HRESP`, and ends a stalled transfer
after `TIMEOUT_CYCLES` rather than hanging. `HWRITE` and `HWDATA` are hard-tied
low, so the core cannot issue writes.

`examples/designs/tb_fabric_ahb_read_master.v` covers a successful read with
inserted wait states, an error response, and a bounded timeout.

`agamemnon/rtl/fabric_ahb_read_master_ag32.v` is the complete hard-boundary
wrapper. It binds the core to the hard bus clock/reset, all 11 request-control
ports, all 64 address/write-data sinks, both response controls, and all 32
read-data sources without permitting a write. The standalone hard-primitive
simulation model provides an always-ready, zero-data slave, and the wrapper
test confirms reset-idle and zero-wait read behavior. Both RTL files ship as
package data.

This is protocol and integration logic, not a claim that the AG32
fabric-master boundary is ready on silicon. The request payload has a strict
64-lane shared safe-low route using the guarded dual-output source. One exact
registered route now makes only `HADDR[2]` dynamic from `X18Y9_SLICE15` while
the other 63 payload lanes remain safe-low. Its five-edge route and four
configurable fields were decoded from one retained wide-boundary build, all 40
selector bits were checked against that bitstream, and a strict-graph open
replay emitted with zero unmapped or predicted pips. The packer requires the
exact source BEL, all 64 endpoints, and the 63-lane safe-low remainder; it does
not admit arbitrary dynamic payload placement or another address/data lane.

One further exact desk profile presents the SRAM base bit by sharing
`HADDR[29]` with the exact `HSEL` register at `X14Y7_SLICE14`. The retained
routes share their first edge and then branch to the two hard endpoints.
`HADDR[0]` and `HADDR[1]` similarly branch from the retained `HSIZE[0]` and
`HSIZE[2]` backbones, resolving two otherwise conflicting route owners without
inventing a path; the other 60 payload endpoints stay on the safe-low tree.
The emitted route contains all 68 expected exact edges, and its 265 data pips
contain 190 mapped configurable pips, 75 fixed endpoints, zero unmapped pips,
and zero predicted pips. A negative with `HADDR[29]` moved off the HSEL net
fails in packing before placement. The retained `HADDR[29]` fields agree 29/29
with their source bitstream, and the two HADDR/HSIZE suffixes reuse 29 selector
states already checked in the retained shared-payload oracle.

The strict packer admits
request controls either from the exact pinned, combinational shared-low oracle
or from one retained composition of 11 distinct registered sources at exact
BELs and over exact paths. A 13-build route campaign decoded 143/143 boundary
selectors without disagreement, and a strict-open replay emitted with zero
unmapped or predicted pips. This is desk route qualification for that one
request-control composition and the bounded request-side profiles above, not a
completed AHB transaction, SRAM access, or silicon behavior. Other dynamic
request-control and payload shapes still fail before placement. The generic
wrapper remains the complete logical API and is not itself a whole-wrapper
route claim.

`agamemnon/rtl/fabric_ahb_read_master_ag32_sram_base.v` is the first exact
structural lowering. It composes the retained request sources into a read-only,
word-sized `NONSEQ` presenter for exactly `0x20000000` and `0x20000004`. The
hard HREADY input is held high, so the transaction cadence is zero-wait only.
The response side uses the simultaneously witnessed routes for HREADYOUT,
HRESP, and HRDATA[0] into one LUT at `X14Y9_SLICE0`; its output is the XOR
signature of those three signals. That one bit makes all three inputs
observable but does not expose independent error status or 32-bit read data.

The reset-idle whole-wrapper desk build uses:

```text
agamemnon build examples/designs/mcu_slave_ahb_sram_base_read_master_route_smoke.v \
  --source agamemnon/rtl/fabric_ahb_read_master_ag32_sram_base.v \
  --top top --uarch --research-unsafe --require-clean-selectors
```

The research policy is required only because the retained dual-output constant
source is still registered experimental. `--require-clean-selectors` keeps that
primitive opt-in from admitting selector predictions. The qualifying build
contains all 54 exact independent-control edges, all five HADDR[2] edges, all
four HADDR[29] edges, both HADDR[0:1] retained suffixes (five edges total), and
all six exact response edges. It emits 253 routed data pips: 178 configurable
mappings, 75 fixed endpoints, zero legacy-absolute, zero predicted, and zero
unmapped. Simulation covers both bounded addresses and the registered physical
presentation cycle.

This closes a hardware-free composition step only. There is no silicon SRAM
transaction witness, holdout sample, inserted-wait behavior, independent
HRESP capture, or full-width HRDATA capture yet.
