# BRAM saved-path lookup — 2026-09-05

The generic native architecture asserts when a routing-edge name is absent;
its name lookup does not return an empty PipId. BRAM saved-path replay had
called that API and then tested for an empty result. Consequently a path table
containing an edge excluded from the current gated graph could abort packing
before the intended fallback or named refusal.

The repair gathers the edge names requested by the BRAM path tables and
resolves those names against the actually loaded PIPs. Missing names now return
an empty result to the existing policy: optional paths can fall back; mandatory
paths retain their explicit refusal. No graph resource is added and no absent
edge is considered routable. Optional prefixes are collected completely before
any of their edges are bound.

## Verification

The new native regression has a complete-prefix control and an otherwise
similar prefix with a real first edge followed by an absent edge. Before the
repair, the control passes and the missing-edge case aborts. After repair both
tests pass: the complete-prefix completion diagnostic is retained, and the
incomplete optional prefix is not applied. Pack-only JSON does not serialize
routing attributes, so the test uses the native completion diagnostic rather
than making claims from absent JSON fields.

Broader native/synthesis regression: **268 passed, no skips**, 235.84 seconds.
The native source matches the checked implementation byte-for-byte:

- Source SHA256: `ad4f08407f8b0a0020ddd6f65b671d9b108bed6f50fe08faa9e529e6ab2b1a90`
- Native executable SHA256: `8ac57c0f26c2d53b6485121552c835706dce10ec44f1a16bcf4dff2eb39c2a03`

A separate research ROM256 experiment with explicitly inserted identity buffers
now finishes packing. One-stage buffering is rejected by MCU-entry placement
legality; two stages complete routing. Neither constitutes a fresh-source
buffering implementation, an initialized-read admission change, or a silicon
claim. General address buffering and its output encoding remain further work.
