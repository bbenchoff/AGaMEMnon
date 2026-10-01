# Typed register-input legality

`GENERIC_SLICE` cells carry `AGRV2K_REGISTER_INPUT_MODE` from packing through
routed JSON and strict bitstream emission. The supported semantic values are:

| Mode | Physical register input |
|---|---|
| `NONE` | No active FF (`FF_USED=0`) |
| `LUT_COMPUTE_TO_FF` | The configured LUT function drives the FF |
| `LUT_FEEDTHROUGH_I0` | Exact identity LUT (`INIT=0xAAAA`) passes I0 to the FF |
| `REGISTERED_PAD_I3` | Existing tagged registered-pad identity path on I3 |
| `DIRECT_D_I3` | Explicit protocol mode or existing tagged own-Q feedback path on I3 |
| `CARRY_SUM_TO_FF` | Dedicated carry sum drives the FF |
| `UNKNOWN`, `MALFORMED` | Explicit fail-closed states; never admitted |

The placer and mandatory pre-route DRC use one common shape/resource validator.
The strict Python emitter validates the same routed metadata before claiming or
emitting any LUT or OMUX bit. Cell names do not participate in admission.

## Evidence boundary

E1 is the public architecture-graph fact used for general placement: an
ordinary feedthrough-capable site is a `GENERIC_SLICE` BEL with actual I0, CLK,
and Q pin wires. This applies across the ordinary graph and is not restricted
to two status-overlay sites.

E5 is narrower retained qualification evidence: the status-overlay checkpoint
contains exact `LUT_FEEDTHROUGH_I0` shapes at `X8Y2_SLICE0` and
`X8Y2_SLICE4`. E5 verifies those two checkpoint placements and their pinned
emitted image; it is not a device-wide site allowlist and does not broaden the
separate registered-pad, direct-D, or carry scopes.

Routed qualification artifacts created before the attribute existed are
accepted only when their complete public netlist shape determines an exact
mode. An untagged legacy LUT that computes next state from its own Q on I3
remains `LUT_COMPUTE_TO_FF`; a presentation option cannot silently upgrade it
to `DIRECT_D_I3`. Actual `DIRECT_D_I3` cells must be placed in the same
qualified direct-D site set used to provide their output presentation.
Explicit unknown tokens or metadata/shape disagreement are always rejected.
This compatibility rule changes no LUT or selector emission; the retained
pack-regression image hashes remain the byte-identity gate.
