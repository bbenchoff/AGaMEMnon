# Retained image versions

The integrated owner-based emitter deliberately preserves the later qualified OMUX/BRAM fixes. Seventeen of the 58 original checkpoint images changed in those earlier migrations; the routed inputs did not change. Default packing uses the migrated registry in `pack_regression.json`. It is not byte-neutral relative to the original registry.

The explicit `pre-owner-v1` replay profile preserves the original image format for the exact original checkpoints. `pack_regression_pre_owner_v1.json` is the unchanged original manifest (SHA256 `88dc725fe2feb5cc64b824e028333c0a98183578be9e9d432df42dca2497c243`). Its installed runtime derivative binds each original routed file, canonical module, environment and expected image hash. This profile cannot accept a new or edited design. The current structural, clock and silicon-negative checks remain active, and final emission must match the selected original hash.

The profile restores the historical OMUX presentation and combinational BRAM-source rules as a versioned renderer. It does not patch images after generation or substitute stored image bytes. Default emission continues to use actual F/Q output ownership.

This remains a diagnostic replay prototype and requires explicit research policy:

```sh
# Also supply the exact environment recorded for the selected checkpoint.
AGAMEMNON_RETAINED_REPLAY=pre-owner-v1 agamemnon pack checkpoint.json original.bin --research-unsafe
```

Two separately registered source-to-image profiles, `mcu-ahb-bank16-read-word0`
and `mcu-ahb-bank16-public-scratch4`, are release-strict exceptions only through
`agamemnon build --qualified-checkpoint`. The CLI first verifies the exact
source/checkpoint hashes and an isomorphic route-transport proof, then emits
from the immutable original checkpoint; `--write-routed` therefore contains the
actual emitted checkpoint and its `.transported-proof.json` sibling retains the
proven transport. The new option accepts no other profile ID, checks the
registry's checkpoint/module/environment/image identity, and is mutually
exclusive with the diagnostic switch above.

Original replay is archival reproduction, not new silicon qualification or permission to program an otherwise refused image. The research-policy sidecar must remain with its artifact. Original and migrated pins are separate immutable expectations; passing one does not count as passing the other.

The wheel includes the replay registry and the routing datasets required by the runtime inventory. Packaging and repack results are recorded in the AG32-Docs `gpt6_xbar_*replay*20260906` evidence. The usable release still requires its full installation, workflow and control-first hardware gates.
