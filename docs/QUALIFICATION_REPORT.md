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
It enumerates serial devices but does not open a DAP, USB uploader, UART bridge,
or AG32 target. Supplying `--output` writes only the requested host-side JSON
file; without it the report goes to standard output.

This is an intake record, not proof that an observation occurred. A hardware
qualification submission must add the observable result, exact target marking
and board revision, wiring, transport, restoration result, and any generated
logic or firmware needed to reproduce it. Accepted evidence remains
append-only under `qualification/`.

The packaged `agamemnon/sdk/support_matrix.json` deliberately tracks five
dimensions separately:

- part marking;
- package and physical bond map;
- board/fixture;
- programming or recovery transport;
- feature-level capability.

A success in one dimension does not silently qualify another package, board,
transport, or feature.
