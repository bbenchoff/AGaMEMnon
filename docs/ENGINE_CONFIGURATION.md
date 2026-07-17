# Engine configuration and evidence registry

The AGRV2K architecture generator and bit generator have accumulated switches
used by routing experiments and silicon-isolation campaigns. They are now
registered in `agamemnon/engine/registry.py`. That registry is the source of
truth for each variable's default, type, consumer, maturity, evidence, and
short meaning.

The maturity labels are deliberate:

- `release`: used by or compatible with the supported build path;
- `archival`: retained to replay an older or predictive build, never enabled by
  the normal CLI;
- `experimental`: useful for a bounded routing or silicon campaign but not a
  support claim;
- `diagnostic`: prints or isolates behavior without changing release policy.

Boolean variables preserve the historical shell convention: absence or an
empty value means false and every non-empty value means true. In particular,
`AGAMEMNON_FOO=0` is **true**. Use `Remove-Item Env:AGAMEMNON_FOO` in
PowerShell or `unset AGAMEMNON_FOO` in a POSIX shell to disable one.

## Supported build profile

The CLI owns the release profile. A normal uarch build enables exact-selector,
strict-edge, conduction, crossbar-conduction, carry, and pad capabilities as
needed. A user should not need to set engine flags directly. The supported
user-facing clock inputs are `AGAMEMNON_SYSCLK` and `AGAMEMNON_HSE`; package,
PCF, carry, and MCU-bridge choices have CLI/manifest fields.

`EngineOptions.digest()` provides a stable digest of the registered inputs for
generated device-database provenance. Tests reject any `AGAMEMNON_*` switch
used by `arch.py` or `bitgen_seq.py` that is missing from the registry.

## Silicon constants

The same registry names high-impact fitted constants: LUT width, the MCU-edge
coordinate, the clock-seam selector, left-edge output slices, BRAM Port-B OMUX
presentations, raw/CRC sizes, CRC polynomial, and HSE input-enable bit. Each
entry points to an in-repository qualification record, chip-database artifact,
or format document. This does not turn inferred values into silicon claims;
the maturity and evidence fields preserve that boundary.

The large CSV/JSON/pickle chip-database files remain the canonical bulk data.
The registry is for configuration and scalar/short-tuple facts, not a second
copy of the routing database.

## Entry points

`arch.py` now exposes `build_arch(ctx, Loc, environ=None)` and executes it only
when nextpnr (or the CSV emitter) injects `ctx` and `Loc`. `bitgen_seq.py`
exposes `main(argv=None, environ=None)` and executes only as a program. Both can
therefore be imported by tests and maintenance tools without constructing the
entire device graph, parsing a routed design, or writing a bitstream. Explicit
environment mappings make isolation tests possible without mutating process
state.
