# Automatic BRAM input bridges and joint allocation

The native implementation now inserts combinational identity bridges for direct
MCU-to-BRAM inputs that are disconnected in the loaded routing graph. This runs
within the existing BRAM pin-packing path. It does not require a user-authored
post-synthesis identity netlist or a per-address list of failing inputs.

The first phase preserves directly reachable connections and inserts a terminal
identity only for a disconnected input. Existing BRAM pin packing chooses that
terminal's output site. The second phase selects an identity input pin and one
or two stages using actual pin-wire reachability and the existing graph-derived
MCU entry corridor. Entry cells remain movable: an early greedy binding passed
free-graph checks but stranded a competing full-depth route. Input topology
changes invalidate the affected corridor cache. Other consumers of the original
net remain connected, and generated cell/net names avoid collisions.

Joint corridor allocation can evict only separately recorded single-sink generic
BRAM branches. Exact saved paths, mandatory ingress and unrecorded owners remain
protected. Multi-sink branches use the prior path and cannot be victims of this
negotiation. A finite 128-eviction budget provides a named refusal rather than an
unbounded loop. The diagnostic switches `AGRV2K_NO_BRAM_AUTOBRIDGE` and
`AGRV2K_NO_BRAM_JOINT` restore the prior paths; neither opt-in prototype switch
is required by ordinary builds.

## Evidence and limits

Small independent fixtures check single and combined disconnected inputs under
different memory names, preservation of an unrelated consumer, direct-input
preservation, joint negotiation, multi-sink protection and bridge disable behavior.
The previous native binary fails ten and passes four. The rebuilt implementation
passes all fourteen (14.14 seconds). An earlier fixture version used sparse bus
declarations whose pack-only serialization compacted the indices; its assertion
failures are retained separately and are not classified as implementation failures.

A fresh strict RTL ROM8192 build with a separately generated devdb reaches
validated routing and bit generation with no prototype opt-in switches. It stops
at the unchanged initialized-read qualification fence after 90.99 seconds.
Its synthesized input and validated route are byte-identical to those of the
separately tested automatic-bridge prototype. Ordinary zero-INIT packing followed
by explicit restoration of the original INIT produces the same witnessed image:

`290a197dd68f80697af6f721d72f0b73d9808935c4175751eb19a1706f22bb97`.

That image passed three L48 silicon repetitions, each checking 32,768 first and
settled reads over sequential and permuted address visits. Each had zero errors,
16,384 matches per read type and signature `0x092f7a0f`. All three public32 controls
passed. Three zero-content negatives matched their complete independent failure
predictions. Final reset and lock release were recorded; no flash writes.
The witness is retained in AG32-Docs commit
`72f104768a9b969eece353da001d8268f1921949`, under
`tools/vendor_parity/gpt6_bram8192_fresh_auto_image_20260905/silicon`.

The original INIT fence is not removed here. A single binary content pattern
cannot distinguish every alias between equal-valued locations; full-depth
address-plane/complement coverage and broader widths/sites/ports/write semantics
remain work. Existing BRAM source-slot and site restrictions are not generalized
by this change. These results do not establish arbitrary-RTL capacity, timing
closure, full ISA compliance or vendor parity. No vendor material is included.

The broader native/synthesis regression passes 281 with one optional source-
overlay check skipped (257.46 seconds). Configuring the actual native source
path and rerunning that check passes separately (1.63 seconds). This covers
BRAM constants and optional prefixes, endpoint legality, carry DRC, soft-ripple
generality and memory synthesis checks, as well as the fourteen new cases.
The compiled native source matches the shipped source byte-for-byte.
No new full Windows suite is claimed by these native results.
