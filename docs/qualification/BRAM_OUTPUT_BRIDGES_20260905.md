# BRAM output bridges: work-branch implementation

The native packer now discovers single-sink BRAM outputs that cannot reach
their consumer, or conflict with another output's necessary routing wires.
It inserts identity LUTs at graph-selected available sites. Address/constant
corridor allocation also protects destination-reaching mandatory output
chains. The saved paired-output reservation applies only to its actual source
and consumer endpoints.

This is not width-, content-, cell-name-, or fixed-BEL allowlisting. The
`AGRV2K_NO_BRAM_OUTPUT_AUTOBRIDGE` switch disables automatic output insertion
for diagnosis. Failure to find a one-stage bridge preserves the original net
and leaves downstream native legality/routing checks in force.

## Evidence and limitations

An unchanged synthesized full-word x18 input previously fails routing. The
new engine inserts two identity LUTs and completes native routing. Independent
checks preserve all eighteen lane endpoints, complete BRAM parameters and
INIT, both identity truth tables and unique serialized wire ownership.
Routed artifact SHA256:
`47d3620683e002a6c4707c05dfa8b926d3b8c5d77d3c077aea4a45ba52c27e81`.

Ten independent output-buffer fixtures exercise renamed memories, disconnected
and competing outputs, unchanged direct nets and opt-out behavior. The prior
engine fails six and passes four; the candidate passes ten. Twelve endpoint
fixtures, fourteen input-bridge fixtures and one native-legality fallback
fixture separately pass with the candidate.
From the public worktree, all 37 configured native checks pass in 31.06 seconds.
The BRAM-filtered Windows suite passes 195 tests with 131 skips and 2,446
deselections in 35.85 seconds. Skips are not native or silicon qualifications.

This is a native-routing result, not an emitted x18 bitstream or silicon
qualification. Wider initialized-ROM admission remains unchanged. Multi-sink
outputs, unresolved consumers, broader site/clock coverage, joint placement
completeness and timing remain open. One-stage graph feasibility does not
guarantee simultaneous routing; normal routing checks still decide success.

The complete 2,265-pass/484-skip regression predates this output-bridge change
and must not be presented as its full regression result. No release or main
promotion is implied by this work-branch implementation.
