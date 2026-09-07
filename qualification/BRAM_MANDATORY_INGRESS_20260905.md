# Mandatory BRAM input ingress

Greedy corridor reservation let a flexible address branch consume another
terminal's sole ingress. The sixteen-word inferred ROM reproducer failed at
AddressA[11] in packing even though a simultaneous strict-graph solution exists.
Moving its ground source among 48 nearby BELs did not repair the ordering
conflict. A controlled order change routed the identical netlist and graph.

The implementation does not hardcode that order. Before reserving BRAM
corridors it records each live input's mandatory single-predecessor chain from
the loaded graph. A flexible search or exact corridor cannot use a different
net's mandatory wire. Two nets requiring the same mandatory wire receive a
named refusal. The graph, bit encodings and ordinary reservation order are
unchanged; there is no experimental runtime switch.

## Verification

- The native regression reproduces failure with four dynamic address bits;
  its three-bit control passes. After repair, focused native coverage passes
  73 without skips.
- Broader native/synthesis coverage passes 266 without skips.
- Fresh inferred ROM16 parity and asymmetric-content designs both route at
  default settings. Explicit original INIT restoration after normal zero-INIT
  emission produces research images that each pass their complete board
  oracle three times.
- The asymmetric truth table has no nonidentity signed address-bit permutation
  symmetry, avoiding the permutation blind spot in parity-only tests.
- Positive rig/vendor controls pass. An aliasing eight-word image and zero
  contents are independently rejected by each sixteen-word oracle.
- A fresh build of the earlier eight-word ROM preserves its routed checkpoint
  and its witnessed research image byte-for-byte.

These witnesses do not qualify all memory depths, widths, ports or writes.
The initialized-read admission boundary remains unchanged. The research-only
INIT restoration is not represented as an ordinary admitted source build.
