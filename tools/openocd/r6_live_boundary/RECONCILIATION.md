# R6 Phase1C current-main reconciliation

Status: **desk-only reconciliation candidate; OpenOCD not executed; hardware not contacted**.

This child reconciles the independently accepted historical Phase1C tip
`a8f7598c59ec1a9c3e01c81b382e83f0f99b4b8e` (tree
`74ddbd324ce9c1eaf7c1179f1cf4bf8e87fc664c`) onto current public parent
`2af1ffb445f28a6dc54965d08618348b0d9b3d09` (tree
`1bd837172961782020c5ddd10a02beccb8138315`). The historical branch remains a
separate lineage and is not merged, squashed, or cherry-picked.

The promotion surface is deliberately bounded:

- the 32 historical `tools/openocd/r6_live_boundary/**` files are imported
  with their exact accepted Git blobs;
- the historical base-to-Phase1C changes to `tools/openocd/manifest.json` and
  `tools/openocd/release.py` are applied to the current versions without
  discarding later compiler-line changes;
- the one `*.patch text eol=lf -whitespace` rule is composed into the current
  `.gitattributes`, preserving every later N5.8 rule; and
- the 19 older observer/HIL source, RTL, qualification, example, and test paths
  from the historical branch are excluded as superseded.

Builder gates on the reconciled tree:

- Phase1C focused tests: `31 passed`;
- retained Phase0/1A/1B/1C plus OpenOCD-bundle matrix: `252 passed, 1 skipped`;
- two fresh frozen-UCRT64 builds each ended
  `PASS_PHASE1C_BUILD_COMPLETE_OPENOCD_NOT_EXECUTED`;
- both fresh static audits ended
  `PASS_PHASE1C_DESK_ONE_SHOT_BOUNDARY_OPENOCD_NOT_EXECUTED`; and
- both audits reproduced the frozen PE, archive, object, import, normalized
  configure/link, and disassembly identities in `phase1c_manifest.json`.

The safety boundary is unchanged. `openocd_execution_authorized` and
`hardware_contact_authorized` remain false. Module/API-set attestation,
namespace custody, external GO provenance, two independent live-readiness
audits, and a fresh one-shot board GO remain unresolved. This reconciliation
does not authorize executing the PE, USB enumeration, a board lock, HIL, or
hardware contact. A fresh detached audit must accept the exact frozen child
before canonical promotion.
