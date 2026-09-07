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

The OpenOCD publication gate completed on 2026-09-07. Workflow 34088837146 passed all four builders and the unconditional source-identity comparison. Its source archive SHA-256 is `b2c7a91f6e456e744cb73b739451156d434e80f541535572f7d44fafe2ff0e49`. All 1,089 Windows runtime files match the hardware-tested package. The exact verified artifacts are published as [OpenOCD 0.1.0](https://github.com/bbenchoff/AGaMEMnon/releases/tag/openocd-v0.1.0), tagged at e913b094ad26aa24165661fcf6e73199cba3eda7. Anonymous installation through the default public URL into fresh Windows and Linux homes passed, including archive hash verification, executable resolution, version and boardless configuration parsing. Linux dynamic dependencies resolved. These installer checks involved no hardware and do not qualify flash programming or a complete SDK archive.

The earlier workflow 34087211060 source-archive mismatch (four CRLF text files and 46 executable modes) remains retained negative packaging evidence; it was corrected before publication. No tested runtime identity was silently replaced.

Private reproducibility evidence remains in AG32-Docs under `tools/vendor_parity/gpt6_release_public_programming_20260906/`: PREPARED.json, silicon/RESULT.json, silicon/AUDIT.json, raw logs and MANIFEST.json. No vendor material is incorporated here.

Publication update, 2026-09-07: complete tagged SDK run `34139873735` and
CI `34139867923` passed. The v0.4.0 assets were published and independently
downloaded; fresh Windows/Linux offline installation and source-build checks
also passed. Earlier statements about pending SDK gates describe the original
hardware-session checkpoint. No new hardware session is claimed.
