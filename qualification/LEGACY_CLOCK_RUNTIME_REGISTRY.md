# Installed legacy clock admission

The source-only clock gate opened `qualification/pack_regression.json` and its
referenced routed checkpoints at runtime. An installed wheel has neither, so
legacy admission failed before it could distinguish qualified and unqualified
inputs.

`export_legacy_clock_registry.py` produces the packaged
`agamemnon/chipdb/clock_legacy_pack_registry.json` from that exact 58-artifact
manifest. Each row adds the canonical module hash computed from the verified
checkpoint. The runtime pins the derivative's digest and the source manifest's
digest, checks the schema and count, rejects duplicate identities, and requires
both the supplied routed-file hash and actual in-memory module hash to match.
Changing a caller's module while retaining an old file hash still fails closed.
The separate extra-clock-leaf quarantine remains unchanged.

This is a packaging repair, not a wider legacy allowance. Fresh designs still
require typed clock metadata. The old `tests/fixtures/counter_ahb_routed.json`
is not in the retained registry and remains rejected. Installed-wheel smoke
coverage checks that negative case and then packs `counter8_carry_routed.json`
to its already-qualified hash, using the installed engine and tables only.

The generator and derivative-equality test retain the source-to-runtime link;
the relocated-registry test checks admission without a source checkout, module
tampering, and registry digest drift. Qualification routes are not copied into
the runtime registry. No vendor binaries or raw reverse-engineering material
are added to the package.
