# Installed public SRAM programming contracts — 2026-09-06

The isolated installed 0.4.0 candidate passed five control-first SRAM arms through the actual public `agamemnon sram` CLI: reference control before, rebuilt public OpenOCD control, regbank16, util20, and reference control after. Each arm ran once. Regbank16 completed 622 observations; util20 completed 1,024 steps. Every requested mailbox word matched its preregistered vector. Final reset succeeded and board custody was released. Flash writes: **0**; option-byte writes: **0**; negative fences: **74 before, 74 after**.

This is bounded installed-programming evidence, not general silicon qualification, flash-programming validation, or qualification of other binary builds. The independent boardless audit compared all raw mailbox vectors with the preregistration, CLI output and terminal result, and verified 2,343 immutable input bindings. Raw logs do not independently store subprocess return codes; final-reset success also relies on the runner's checked terminal record.

## Exact identities

| Component | SHA-256 |
|---|---|
| Installed wheel, source a99f96588d0dd8a8a547a4106cc9048f2941cae6 | `8581891d9f09206199a853cdcf8fd781fa661a15080ee9c06a06f144cd704624` |
| Candidate Windows OpenOCD, workflow 34087211060 | `a79cdc458795aa683af21152753231d007570b337d87d40af3572d2cfde3714f` |
| Reference public Windows OpenOCD | `982c1b62d1398bf5d7402f6a40bf98c3ff1220c1a626bdcdbef224bea0869009` |
| Installed public agrv2k.cfg | `95214035cdc7bd2e26be9cacfba3dbdb3bb00414b5ec892414884d1e50ce61f4` |
| Fresh regbank16 image | `710927189259f78b0d10806d54b2af7b3b7750e97ebaa0496caec2e4876a9bfb` |
| Fresh util20 image | `73b550f4095652f0de4c5cc8bcef083545507aabf3fb3e185fe8c250288a8658` |

Both images were rebuilt from ordinary sources using an isolated installed wheel and independently matched the earlier sampled silicon batch. The native P&R executable and system Yosys were supplied separately; a complete SDK archive has not yet passed its release gate.

The OpenOCD publication gate remains open. Workflow 34087211060 built all four platforms, but its Windows corresponding-source archive differs by four text files' line endings and 46 executable modes. Compiled-source bytes agree. Corrective workflow 34088837146 must pass its unconditional source-identity comparison. A rebuilt executable must match the tested runtime identities or receive fresh bounded validation before inheriting this evidence. The public `openocd-v0.1.0` download was absent at this checkpoint.

Private reproducibility evidence remains in AG32-Docs under `tools/vendor_parity/gpt6_release_public_programming_20260906/`: PREPARED.json, silicon/RESULT.json, silicon/AUDIT.json, raw logs and MANIFEST.json. No vendor material is incorporated here.
