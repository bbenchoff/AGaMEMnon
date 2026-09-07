# Default odd-site source reproduction — 2026-09-07

Candidate `236bcb54a7794669af1d139be466a51d91534fb1` enables source-typed ordinary slice ownership by default. Explicit `AGRV2K_SOURCE_TYPED_XBAR=0` selects legacy placement behavior; malformed values fail. Historical routed checkpoints retain their serialized ownership semantics. This change does not add graph edges, widen direct-D admission, remove negative fences or repin retained images.

An isolated installed wheel built from this commit rebuilt both ordinary sources with no `AGRV2K_SOURCE_TYPED_XBAR` environment variable, fresh per-design device databases, `--uarch --release-strict --cap 16 --freq 10`, separately supplied native nextpnr and system Yosys. Both raw and compressed images match the earlier hardware-tested builds exactly.

| Source | Raw image SHA-256 | Compressed identity |
|---|---|---|
| regbank16 | `710927189259f78b0d10806d54b2af7b3b7750e97ebaa0496caec2e4876a9bfb` | Exact match |
| util20 | `73b550f4095652f0de4c5cc8bcef083545507aabf3fb3e185fe8c250288a8658` | Exact match |

Wheel SHA-256: `b8701dbda3f7e666f4a784d6f437b228cba00e3571c46891b62815642346d25e`.
Native binary SHA-256: `c00ad2b929f9714ddaeb1c0ca821592f67a8eef4309655da4592156779969f12`.
Native source SHA-256: `7c8487f051e524274a0286c522f85290d4290890d520bafdd97e2d8b5cfa1777`.

This is a boardless default-flow reproduction result, not a new silicon session or full SDK archive test. The exact silicon contracts are recorded in [ordinary odd contracts](ORDINARY_ODD_CONTRACTS_20260906.md) and [installed public SRAM programming](INSTALLED_PUBLIC_SRAM_20260906.md). Native behavioral cases pass for unset/default, explicit legacy-off and malformed values. The endpoint suite reported 119 passes, one skip and two obsolete even-only assertions; those two assertions were corrected and passed targeted reruns. The current complete retained-image rerun remains a separate gate. Broad odd-site compositions, compact util20 routing, addsub16 and timing closure remain unqualified. Fences remain 74.

Private logs, immutable inputs and output manifests are banked in AG32-Docs commit `689d50efb`, under `tools/vendor_parity/gpt6_release_installed_odd_default_20260907/` and `gpt6_release_odd_default_native_20260907/`.
