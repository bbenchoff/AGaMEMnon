# Optional saved address-path fallback

Saved AddressA routes are hints over the active strict graph, not additional
graph resources. A missing edge or discontinuous saved path now falls back to
the existing graph allocator, just as an occupied path does. The complete
saved candidate is validated before any of its pips are bound.

The native regression covers missing and discontinuous optional paths with
two memory names. All six positive cases fail on the previous implementation
and pass with this change. Two disconnected-graph negatives still refuse the
design with an explicit missing two-stage bridge diagnosis. The preceding
44 native BRAM allocation tests also pass with this change.

The full-depth x9 synthesized input now routes. Full-depth x2/x4 route JSON
remains byte-identical, and ordinary repacking reproduces the images already
witnessed on silicon. No graph edges or initialized-memory admission rules
change. This does not itself qualify fresh x9 CLI emission or silicon behavior.

The preceding revision's complete Windows suite passed 2265 tests with 514
skipped; it is not automatically a full-suite result for this revision.
