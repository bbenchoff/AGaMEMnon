## What changed

<!-- State the user-visible outcome and why this change is needed. -->

## Evidence level

- [ ] Documentation or diagnostic only
- [ ] Software-tested
- [ ] Build-supported through the strict public flow
- [ ] Implemented but not target-side qualified
- [ ] Silicon-qualified with an electrically observable oracle

## Reproduction

```text
# Exact commands
```

## Hardware boundary

<!-- Exact marking, package, board, revision, clocks, probe, wiring, and transport. Write “none” for hardware-free changes. -->

## Tests

- [ ] `pytest -q`
- [ ] Relevant offline simulation or build
- [ ] `agamemnon doctor --no-hardware`
- [ ] Hardware test, if claimed
- [ ] Backup and readback restoration, if persistent state changed

## Provenance and licensing

<!-- Identify third-party code, generated data, captured vendor output, binary artifacts, and their redistribution terms. -->

- [ ] No secrets, unique factory dumps, personal serial numbers, or unlicensed vendor packages are included.
- [ ] Package-, pin-, route-, and mode-specific results have not been generalized beyond their evidence.
- [ ] User-facing changes are reflected in `CHANGELOG.md` or are intentionally internal.
