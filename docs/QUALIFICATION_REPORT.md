# Qualification intake reports

`agamemnon qualify` captures the information needed to start a reproducible
support claim without touching an AG32:

```powershell
agamemnon qualify `
  --artifact build/hello.bin `
  --artifact build/hello.routed.json `
  --notes "AG32VF303CCT6, L48 board, Windows 11, DAP disconnected" `
  --output qualification-report.json
```

The command runs the host-only doctor path, records exact AGaMEMnon and host
versions, embeds the current support matrix, and hashes each supplied artifact.
Artifact labels are kept relative to the invocation directory when possible or
reduced to a basename otherwise. Windows, Linux, and macOS user-home paths in
diagnostics and notes are replaced by `<HOME>` so reports are portable and do
not disclose workstation identities.
It enumerates serial devices but does not open a DAP, USB uploader, UART bridge,
or AG32 target. Supplying `--output` writes only the requested host-side JSON
file; without it the report goes to standard output.

This is an intake record, not proof that an observation occurred. A hardware
qualification submission must add the observable result, exact target marking
and board revision, wiring, transport, restoration result, and any generated
logic or firmware needed to reproduce it. Accepted evidence remains
append-only under `qualification/`.

Checked evidence ledgers are declared in
`qualification/evidence_manifest.json`. The CI release gate verifies their
existing byte prefixes, permits only appended JSON objects, validates schema-1
records and SHA-256-shaped fields, rejects undeclared ledgers and duplicate
records, and applies the home-path leak policy.

The packaged `agamemnon/sdk/support_matrix.json` deliberately tracks five
dimensions separately:

- part marking;
- package and physical bond map;
- board/fixture;
- programming or recovery transport;
- feature-level capability.

A success in one dimension does not silently qualify another package, board,
transport, or feature.
