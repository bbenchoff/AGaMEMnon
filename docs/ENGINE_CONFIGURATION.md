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

## Research-unsafe recovered-knowledge profile

`agamemnon build --research-unsafe` is a deliberately separate third policy.
It exists for reverse engineering, routing exploration, and hardware probes
where refusing every unqualified fact is less useful than preserving its exact
origin and risk. It enables the broad enumerated graph, completed RMUX-to-IMUX
crossbar, soft preferences for conducting and clean-selector edges, decoded
mesh-template fallback, and the vendor-derived selector conflict atlas.

The profile may emit a corpus-majority, conflicted, decoded, or predicted
selector. It never silently calls those rows clean or independently derived.
Every image writes a mandatory `.policy.json` sidecar binding the routed JSON,
output, registry, `research_knowledge_manifest.json`, and counts of the actual
selector evidence classes used by that image. Standalone routed JSON can be
packed with `agamemnon pack --research-unsafe`.

The profile does **not** make incomplete configuration acceptable: an
unresolved routed selector still stops emission. It also cannot resurrect a
checked-in silicon-dead edge; negative evidence remains a hard architecture
blacklist. Release support, package qualification, behavior, timing accuracy,
and vendor parity are unchanged. The equivalent low-level gate is:

```text
AGAMEMNON_STRICT_POLICY=research-unsafe
AGAMEMNON_RESEARCH_UNSAFE=1
```

`agamemnon/chipdb/research_knowledge_manifest.json` inventories and hashes the
normalized public chip database. `selector_conflict_atlas.agdb` retains all
74,103 conflicted physical edge keys from 733,862 parsed observed keys,
including every observed pair/count distribution. Its source hash is retained;
the 1.7 GiB parsed vendor-derived corpus and all raw vendor artifacts remain in
the workbench and are not shipped.

`qualification/claim_policy_dry_run.json` applies the default policy to every
retained A0 artifact without emitting bytes. Regenerate both policy artifacts
with `python tools/generate_claim_policy_ledger.py --write`; CI uses `--check`.

The V6 BRAM differential campaign admits 39 configuration-encoding rows in
`agamemnon/chipdb/bram_config_admission.json`. That metadata records exact
selector encodings; the admission itself does not claim BRAM behavior or
silicon qualification, and it is unchanged by the 2026-08-15 measurement below.
The existing release BRAM surface is unchanged. Separately from the admission,
one field of that set now has measured behaviour: `PORTA_OUTREG` adds exactly
one BRAM clock of Port-A read latency at `X13Y4` in the one exercised read mode
(x18 Port-A read, identity ROM, 4-bit fabric address, Port-B unused, single
clock domain), while `PACKEDMODE` and `CLKMODE` showed no observable effect in
that same mode — a bound, not a characterization, since neither has been
exercised on the write path or in dual-port operation. That measurement was a
single-config-byte differential against a qualified base image, not an image
emitted through this gate, so it changes no admission or emission behaviour
here. Note also that the
`X13Y1`–`X13Y4` gate range below is the CONFIG surface; the PLACEMENT surface
(`chipdb/bram9k_bel.csv`, `chipdb/bram_cell.csv`) is `X13Y4` only. The newly admitted x36 width,
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

Routing-wave selectors use a separate contract at
`agamemnon/chipdb/routing_selector_admission.json`; they are never appended to
the blanket release-qualified `sel_edge_pairs.agdb` table. The contract contains
six individually reviewed AGRV2KL48/L48 RMUX30 rows. Each row binds one exact
route, one exact IOTILE `CFG_RMUX3` transition, its authenticated holdout
evidence, the two retained terminal exclusions, and its approval artifact.
Rows can supplement only their named architecture pips and emit only their
set/clear selector difference. An enabled experiment that uses none of the six
routes remains byte-identical to the release path.

The activation boundary is deliberately three-part:

```text
AGAMEMNON_STRICT_POLICY=experimental-strict
AGAMEMNON_EXPERIMENTAL_FEATURES=AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT
AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT=1
```

Release-strict rejects the option, and either missing experimental setting
fails closed even when the manifest contains a row. Every row must bind one
absolute routed edge, its exact physical owner, complete set/clear selector
surface, L48 scope, `differentially_validated` evidence, retained-negative state,
and a reviewed source/dossier identity. The contract can admit an encoding for
an observed LogicTILE RMUX-to-RMUX edge already present in the independently
generated routing graph; it cannot manufacture topology. Checked-in silicon-dead,
exit-feeder, and BRAM-corridor filters retain precedence, and graph-modifying
options are incompatible with this experiment. Same-owner and cross-owner
encodings use the same exact owner record rather than destination-derived mux
arithmetic. Experimental policy sidecars bind the canonical admission-manifest
identity and ordered row identities, including the empty list in the bootstrap
state.

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
qualified 1:1 bus-clock-to-MTIME ratio.

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
