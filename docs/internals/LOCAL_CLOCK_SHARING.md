# Local clock sharing: supported scope and qualification

Ordinary CLI builds compare isolated, mixed and dual native-enable placements
and retain a sharing candidate only when it improves slice/tile counts. The
qualified scope is positive-edge, active-high enables on the MCU bus clock.
No new release is created; existing v0.4.0 binaries remain unchanged.

- Mixed: one native-enable group uses one local line; ordinary registers use
  the other, idle line.
- Dual: two independent native-enable groups use the two lines. Ordinary
  registers cannot share that tile.

These are separate profiles, never combined. Two occupied lines leave no idle
line, including when both roots carry the same enable net. Placement preserves
register/input legality, fixed endpoints, native-group membership and existing
routing predicates. Emission independently checks line ownership.

A line-1 consumer needs both its per-slice line selection and the second tile
clock selector/seam. The emitter supplies both. Native identity-LUT FFs retain
cleared BYPASSEN bits; ordinary register input-mode bits are preserved when
changing their local clock line. The earlier claim that BYPASSEN alone exempts
ordinary neighbours is withdrawn. This qualification does not establish other
clock profiles, arbitrary clock rates or combined asynchronous controls.

## Fresh ordinary-source evidence, September 9

The aligned two-bank fixture uses 96 slices in ten isolated tiles. Both mixed
and dual profiles route and emit in nine tiles. The mixed profile wins their
exact metric tie because it is evaluated first, not because its name sorts
before the dual profile. See [selection and candidate budgets](CONTROL_SHARING_SELECTION.md).

The qualified mixed image is:
`c9c7cf6dcfd893ef684f55aff8e56afe8b5842cb28234f0492ac6566dd54ca75`.
The dual image is:
`ffd80e894456e09b6416748ef240961a372944fb33e42baa79d849d40df95fcc`.
Its X16Y10 tile contains sixteen native registers in two independent groups
and zero ordinary registers. Routed ownership and emitted line/bypass bits
pass audit, including rejection tests for missing, duplicate and empty roots.

The unchanged aligned firmware distinguishes independent update, hold and
resume, checks scratch state and observes progress in both ordinary banks.
The SRAM batch passed mixed 3/3 and dual 3/3, both bracketing controls and the
retained reference. The independent raw-mailbox and temporal-state audit passed.
Final reset and custody release were verified, with zero flash/option writes.
Fences remain 74. Private evidence is retained in AG32-Docs at
`tools/vendor_parity/routing_aware_packing_20260908/dual_enable_batch_20260909/`.
Silicon RESULT SHA256:
`a664372d138b469d0b0ca929d06f3e7a701e8e26d3a6209492ab657fe04c3d8e`.

Source `95d3f63` reproduces these fixture images and the already-qualified
regbank16 68/6, addsub16 151/12 and util20 434/39 images (slices/tiles).
All 58 retained images remain byte-identical (60 regression tests passed).
Sharing does not improve those three selected width images in this comparison;
there is no physical speed claim or general vendor-density claim.
