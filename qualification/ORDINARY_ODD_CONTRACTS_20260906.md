# Ordinary odd-slice sampled silicon contracts

Fresh ordinary-source builds at `54ddbb5c191b8b48ab786eb93b0d4c462bef42b6` passed the following contracts on AG32/AGRV2K L48 hardware on 2026-09-06 PDT. These builds use experimental source-typed odd support with release-strict graph admission. This record does not promote the experimental option or close any negative fence.

| Design | Observations per repetition | Candidate result | Odd slices | Feedback buffers | Occupied tiles |
|---|---:|---|---:|---:|---:|
| regbank16 | 622 | 3/3 PASS | 30 of 68 | 0 | 16 |
| util20 | 1,024 | 3/3 PASS | 212 of 442 | 0 | 102 |

regbank16 checks its sampled register read/write/reset contract, including word, halfword and byte accesses. util20 checks its sampled wide LFSR handshake contract. Both matched reference runs and all three surrounding known-good controls passed. The SRAM-only runner completed final reset and released board custody. An independent audit reparsed all raw mailboxes and verified the preregistered staged artifact and dependency hashes. Machine-readable session status is `PASS_BOUNDED_CONTRACTS_X3`, with `qualification:false` to avoid implying broader admission.

Candidate image SHA256 values:

- regbank16: `710927189259f78b0d10806d54b2af7b3b7750e97ebaa0496caec2e4876a9bfb`.
- util20: `73b550f4095652f0de4c5cc8bcef083545507aabf3fb3e185fe8c250288a8658`.

These are fresh emitted images, not historical replay outputs. Passing behavior substantiates these exact builds and sampled contracts. It does not establish all-site odd-slice correctness, exhaustive sequential correctness, timing closure, or vendor-comparable density. The compact 42-tile util20 placement still fails to finish routing; the passing image occupies 102 tiles. addsub16 has no emitted candidate and was not tested. The research hardware instrument does not establish release readiness of the independently installed public programming backend.

Fences remain **74 -> 74**, across 18 defect IDs. No graph admission, default option, fingerprint, retained image pin or negative registry changed in this session.

Evidence custody: AG32-Docs commit `06c46abd934e7c773f96a0a31db1852453703036`, `tools/vendor_parity/gpt6_xbar_ordinary_odd_batch_20260906/`, containing immutable preparation, raw logs, terminal `silicon/RESULT.json` and independent `silicon/AUDIT.json`. The auditor is `tools/vendor_parity/audit_gpt6_xbar_ordinary_odd_batch.py`. Vendor references remain in AG32-Docs; this public record contains only bounded outcomes and our candidate identities.

Release work still requires integration, complete installed synthesis/P&R/programming validation, refreshed blockers and support records, and evidence sufficient for each capability's admission. Original retained bytes remain available through the explicit profile described in [Retained image versions](RETAINED_IMAGE_VERSIONS.md).
