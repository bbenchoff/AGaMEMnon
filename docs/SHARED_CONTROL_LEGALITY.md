# Shared register-control legality

AGaMEMnon normalizes slice-shared register control semantics with the routed
attribute `AGRV2K_SHARED_CONTROL_MODE`.  The N4.1 desk-only protocol contains
exactly these active states:

| Mode | Polarity | Value | Required bound port | Physical status |
| --- | --- | --- | --- | --- |
| `NONE` | none | none | none | Existing plain FF behavior |
| `ASYNC_CLEAR_POS_ZERO` | positive | zero | `ARST` | Unsupported; always rejected |

`UNKNOWN` and `MALFORMED` are reserved fail-closed tokens.  An absent
attribute is accepted as legacy `NONE` only when no control port is present.
An active mode requires `FF_USED=1`, the exact port, and a live net.  Attribute
and port disagreement, unsupported or combined control ports, asynchronous
set, clear-to-one, clock enable, synchronous clear/load, and other modes are
rejected.

The synthesis frontend preserves the one bounded oracle verbatim as Yosys
`$_DFF_PP0_` and stamps the normalized mode.  It rejects other fine-grain
controlled-FF families before `dfflegalize` can erase their polarity, value,
or enable semantics.

This protocol is not a physical-support claim.  No async-control BEL pin,
route edge, capacity, selector codeword, or configuration bit is added.  A
well-formed active async-clear register is rejected at nextpnr ingress, cluster
construction, normal/fixed placement, or final pre-route DRC as applicable.
The strict Python emitter performs the same shape validation and rejects it
before creating feature state or claiming any image bit.  Physical admission
remains gated on graph recovery, exact bit ownership, and focused HIL.
