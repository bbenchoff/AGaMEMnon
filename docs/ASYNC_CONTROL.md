# Asynchronous register controls

The ordinary frontend supports active-high asynchronous clear to zero.
Native placement allocates two controllers per LogicTile, sharing equal reset
signals and reserving ground for inactive registers in a mixed tile. Routing
keeps controller DIN and DOUT separate and connects DOUT to local ARST leaves.

Configuration emission is experimental. Set these environment variables for
an explicitly requested configuration experiment:

```
AGAMEMNON_ASYNC_CONTROL_CONFIG=1
AGAMEMNON_STRICT_POLICY=experimental-strict
AGAMEMNON_EXPERIMENTAL_FEATURES=AGAMEMNON_ASYNC_CONTROL_CONFIG
```

Use the ordinary `build --uarch --release-strict` flow to retain the filtered
routing graph. The CLI's `--release-strict` selects strict routing; the
environment policy above identifies the experimental configuration claim.
Default release-policy emission rejects this option. No release or silicon
qualification is claimed by successful emission.

The emitter requires a validated device graph, checks the reset driver and
all ingress/leaf PIPs, and derives controller and slice selections from those
routes. Supported ingress is the modeled local/right RMUX bank. Each selected
CtrlMUX owns its complete twelve-bit field. Different signals cannot share a
routed control wire. Explicit controller configuration owns the inactive-reset
default otherwise written by the clock feature; other clock fields cannot be
silently displaced.

The encoding has differential configuration evidence. Tests cover route and
signal ownership, field geometry, and set/clear behavior. This does not prove
electrical conduction, reset timing, recovery/removal constraints or behavior
with the clock stopped. Other reset polarities/values, further input banks,
and broad capacity/composition qualification remain open.

On September 6, 2026, one fresh ordinary-source image passed 144 output
observations across three SRAM loads and 36 input steps, with four passing
controls. Data capture and positive clear were tested with the clock running.
The oracle explicitly cannot distinguish synchronous from asynchronous clear.
Raw image SHA-256:
`94335d9f14a33349371b495e5c68eb0c040f04bde7f96fdd388e9d50ba7bc0c8`.
Detailed build, encoding, control and silicon evidence is retained in
AG32-Docs under `tools/vendor_parity/gpt6_async_emission_session_20260906/`
and `gpt6_async_emission_source_20260906/`. This bounded result does not promote
general asynchronous-control release admission.
