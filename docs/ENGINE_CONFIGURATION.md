# Engine configuration and evidence registry

The AGRV2K architecture generator and bit generator have accumulated switches
used by routing experiments and silicon-isolation campaigns. They are now
registered in `agamemnon/engine/registry.py`. That registry is the source of
truth for each variable's default, type, consumer, maturity, evidence tier,
evidence, and short meaning. The generated [D0 claim-policy ledger](CLAIM_POLICY_LEDGER.md)
shows both independent axes for every option, constant, and emitted feature.

The same registry can be serialized into a stable manifest for tests and
downstream tooling, which makes it a practical foundation for both the refactor
and the parity program.

`agamemnon manifest` emits that snapshot as stable JSON, with `--scope`
filtering the option half down to `arch` or `bitgen` while always including the
constant set.

The maturity labels are deliberate:

- `release`: used by or compatible with the supported build path;
- `archival`: retained to replay an older or predictive build, never enabled by
  the normal CLI;
- `experimental`: useful for a bounded routing or silicon campaign but not a
  support claim;
- `diagnostic`: prints or isolates behavior without changing release policy.

The independent evidence tiers are `decoded`, `differentially_validated`,
`statistically_silicon_validated`, and `individually_qualified`. The D0
backfill records already-approved V4 release scope as individual qualification;
it does not promote an experiment or widen a support claim.

Bit generation defaults to `AGAMEMNON_STRICT_POLICY=release-strict`, which
fails before emission unless every emitting surface has release maturity,
reviewed statistical or individual evidence, and conflict-free metadata.
`experimental-strict` additionally requires a comma-separated explicit ID list
in `AGAMEMNON_EXPERIMENTAL_FEATURES`; each admitted experiment must already be
differentially validated or higher. It always creates a hash-bound non-release
sidecar next to the image. `AGAMEMNON_POLICY_SIDECAR` can select that sidecar's
path. These controls grant no promotion: current decoded-only experiments are
still rejected.

`qualification/claim_policy_dry_run.json` applies the default policy to every
retained A0 artifact without emitting bytes. Regenerate both policy artifacts
with `python tools/generate_claim_policy_ledger.py --write`; CI uses `--check`.

The V6 BRAM differential campaign admits 39 configuration-encoding rows in
`agamemnon/chipdb/bram_config_admission.json`. That metadata records exact
selector encodings; it does not claim BRAM behavior or silicon qualification.
The existing release BRAM surface is unchanged. The newly admitted x36 width,
`PACKEDMODE`, `DLYTIME`, `PORTA_OUTREG`, `PORTB_OUTREG`, `PORTA_WRITETHRU`,
`PORTB_WRITETHRU`, and `RSEN_DLY` encodings are fail-closed behind all three of
these settings:

```text
AGAMEMNON_STRICT_POLICY=experimental-strict
AGAMEMNON_EXPERIMENTAL_FEATURES=AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG
AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG=1
```

That gate is limited to the AGRV2KL48 BRAM column X13Y1 through X13Y4. Invalid
values, other packages/sites, and `RSEN_DLY=3` are rejected rather than inferred.
Each BRAM cell may select at most one newly experimental nonbaseline row: one
x36 port width or one nonzero experimental field/value. Simultaneous new-field
unions and x36 on both ports are untested compositions and fail closed. A
multi-bit value admitted as one row, such as `DLYTIME=3`, remains one selection.

Boolean variables preserve the historical shell convention: absence or an
empty value means false and every non-empty value means true. In particular,
`AGAMEMNON_FOO=0` is **true**. Use `Remove-Item Env:AGAMEMNON_FOO` in
PowerShell or `unset AGAMEMNON_FOO` in a POSIX shell to disable one.

## Supported build profile

The CLI owns the release profile. A normal uarch build enables exact-selector,
strict-edge, conduction, crossbar-conduction, carry, and pad capabilities as
needed. A user should not need to set engine flags directly. The supported
user-facing clock inputs are `--freq`/`[fabric].freq`,
`AGAMEMNON_SYSCLK`, and `AGAMEMNON_HSE`; package, PCF, carry, and MCU-bridge
choices are expressed by the project/board manifest and build fields. Direct
one-off builds default to L48; `AGAMEMNON_DEVICE` is the registered lower-level
package selector used by the project loader. Fabric frequency defaults to the
qualified 10 MHz ratio.

`EngineOptions.digest()` provides a stable digest of the registered inputs for
generated device-database provenance. Tests reject any `AGAMEMNON_*` switch
used by `archgen.py` or `bitgen_seq.py` that is missing from the registry.

## Silicon constants

The same registry names high-impact fitted constants: LUT width, the MCU-edge
coordinate, the clock-seam selector, left-edge output slices, BRAM Port-B OMUX
presentations, raw/CRC sizes, CRC polynomial, and HSE input-enable bit. Each
entry points to an in-repository qualification record, chip-database artifact,
or format document. This does not turn inferred values into silicon claims;
the maturity and evidence fields preserve that boundary.

The large CSV/JSON/AGDB chip-database files remain the canonical bulk data.
AGDB is a versioned, compressed JSON data container and does not execute code
while loading. The registry is for configuration and scalar/short-tuple facts,
not a second copy of the routing database.

## Entry points

`archgen.py` exposes `build(ctx, Loc, environ=None)`. The nextpnr-facing
`arch.py` is a shim that calls it only when nextpnr (or the CSV emitter)
injects `ctx` and `Loc`. `bitgen_seq.py` exposes `main(argv=None,
environ=None)` and executes only as a program. All can therefore be imported
by tests and maintenance tools without constructing the entire device graph,
parsing a routed design, or writing a bitstream. Explicit environment mappings
make isolation tests possible without mutating process state.
