# Fabric AHB read-master core

`agamemnon/rtl/fabric_ahb_read_master.v` is a vendor-independent, synthesizable
single-transfer AHB-Lite read master. It starts in IDLE after reset, issues
only word-sized `NONSEQ` reads, reports `HRESP`, and ends a stalled transfer
after `TIMEOUT_CYCLES` rather than hanging. `HWRITE` and `HWDATA` are hard-tied
low, so the core cannot issue writes.

`examples/designs/tb_fabric_ahb_read_master.v` covers a successful read with
inserted wait states, an error response, and a bounded timeout.

This is protocol logic, not a claim that the AG32 fabric-master boundary is
ready on silicon. The request payload now has a strict 64-lane shared safe-low
route using the guarded dual-output source, but dynamic independent payload
driving and a protocol wrapper remain unqualified. The release packer admits
request controls only when they use the exact pinned, combinational shared-low
oracle. Any non-idle, constant-high, or independently sourced request control
is rejected before placement, so this core cannot silently become a hardware
master through the unqualified boundary.
