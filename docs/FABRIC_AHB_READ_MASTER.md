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
64-lane shared safe-low route using the guarded dual-output source, but dynamic
independent payload driving remains unqualified. The release packer admits
request controls only when they use the exact pinned, combinational shared-low
oracle. The new wrapper's dynamic request is therefore intentionally rejected
before placement today: it is the exact integration surface to qualify, not a
way around the evidence gate.
