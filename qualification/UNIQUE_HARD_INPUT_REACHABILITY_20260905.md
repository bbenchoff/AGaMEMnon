# Unique hard-input placement reachability

An unbound hard input with exactly one physical BEL of its exact cell type
has a known source location. Input reachability checks now use that location
before the placer binds the hard cell. The lookup is populated once while
loading the chipdb; repeated types are marked ambiguous. Bound locations take
precedence. This does not reserve a route, bind a cell, or add graph edges.

## Verification

- Compiled endpoint, carry, and soft-ripple suites: **174 passed, zero skipped,
  zero failures**, 196.68 seconds (JUnit).
- Controlled placement-only comparison: identical synthesized regbank input
  and identical diagnostic graph, baseline fails its final hard-input
  reachability check; candidate completes placement in 14.69 seconds.
- A 310-cell reduction preserves that baseline-fail/candidate-pass result.
- Small disconnected, connected-chain, and fixed-location controls do not
  reproduce the full placement-order failure and are not claimed as red tests.
- On the unrestricted graph, both engines still fail the same HTRANS1 arc.
  Thus this change does **not** resolve shared-ingress contention or qualify
  a new regbank image.

Candidate source SHA-256:
`b6baa8174e4a1e8ecc68320436401a46871c70133970ba50bfad1a1c1b3851db`.
Compiled binary SHA-256:
`1c1ad6ca56be4316ff108a3aaef2237e6fd2e318fa0ee777a3651f8e679e77f1`.
Standard graph PIP table SHA-256:
`22636e6c4fc3c958fa199fc94236db41e2e53983362aca1798a1c0288da5c722`.

The diagnostic graph removes one existing HSIZE0 first-hop edge to isolate
reachability. That restriction is not a product change or evidence of a
hardware route. Detailed commands and research artifacts remain in the
separate research ledger. This change has not received a fresh full-suite run
or silicon qualification; the prior full-suite result belongs to the preceding
engine revision. Vendor parity and public-main promotion remain unclaimed.
