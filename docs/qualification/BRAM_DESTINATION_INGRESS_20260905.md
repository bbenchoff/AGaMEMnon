# Destination-aware BRAM ingress allocation

The corridor allocator now protects mandatory fixed-MCU escape chains using
their possible destinations. Raw source outdegree is insufficient: a source
may have several exits but only one can reach a feasible bridge-entry input.

For movable two-stage BRAM input bridges, packing records a superset of input
pins satisfying the existing MCU corridor and terminal-reach constraints.
The allocator reverse-traverses from these pins, stopping at the source, then
protects a unique forward chain within that reachable subgraph. It stops at a
possible consumer or a branch. Bound single-consumer MCU nets use their actual
input pin; unresolved and shared consumers are not reduced to one destination.
No graph edges, design-name rules, or fixed bridge-entry BEL are introduced.

## Verification and limits

The diagnostic-free native build passes 44 BRAM/input/output allocation tests.
The added full-address x4 fixture passes with two independent memory names,
preserves all 11 address origins and four observed data lanes, and fails to
route on the preceding implementation. The test also checks any intervening
output buffers are combinational identity LUTs.

A saved synthesized 2048x4 ROM input now routes where the preceding engine
fails. This is native routing evidence, not fresh end-to-end emission, timing
closure, silicon qualification, or a guarantee for other widths/memory modes.
Those qualification gates remain open. The full-suite result for the previous
revision does not apply automatically to this change.

No initialized-memory admission fence is changed by this repair.
