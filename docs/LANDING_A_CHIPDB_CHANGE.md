# Landing a chipdb change

Written 2026-08-21 after two consecutive failed landings. **Neither failed on the data.** Both failed
on requirements that are real, correct, and written down nowhere — a second pin, a manifest, three
count assertions, a stale cache, and an ordering constraint between two of them.

If you are adding, editing or removing anything under `agamemnon/chipdb/`, do all of this. Skipping
one step does not produce a clear error; it produces a confusing failure somewhere else, usually 17
minutes into a full test run.

## The gates, in the order they must be satisfied

### 1. Make the data change
Add / edit / delete the file(s) under `agamemnon/chipdb/`.

### 2. Register any NEW table with its consumer
A new table that nothing reads is inert. For an exact per-position codeword table this is
`EXACT_PIP_CFG_FILES` in `agamemnon/engine/features/mcu_ahb.py`; other kinds have their own lists.
**Find the consumer by matching an existing table of the same shape** — do not invent a new loader.

### 3. Regenerate `research_knowledge_manifest.json`  <-- THE SECOND PIN
`agamemnon/chipdb/research_knowledge_manifest.json` binds **every** file in `chipdb/` by
`sha256` + `bytes` (+ `data_rows` for CSVs). `tests/test_research_knowledge_manifest.py` asserts the
dataset set equals the directory listing exactly, so **a new file needs a new row** and a changed file
needs an updated one.

This is a *separate* pin from the fingerprint pin. Missing it fails 2 manifest tests **and** 8
`pad_pair` byte-identity tests **and** 8 roundtrip tests — 18 failures whose message
(`research knowledge dataset hash mismatch: corpus_conduction.csv`) points at the data, not at the
manifest.

Regenerate programmatically. Verify your generator reproduces the CURRENT manifest byte-for-byte
before trusting it to write a new one.

### 4. Update dependent count AND VALUE assertions
Adding exact pips moves hard-coded counts -- and a data change can move hard-coded VALUES too (2026-08-21: `test_wire_timing.py` asserted `rmux["delay_ns"] == source_max_ns["RMUX"]`, a value, not a count). On 2026-08-21 one 180-row table moved three:
`test_feature_protocol.py` `260 -> 397`, `667 -> 776`, `1060 -> 1131`.
**Write a comment saying why the number moved.** A bare number bump is how the `bbmuxe_fanin`
misfiling survived six weeks.

### 5. Delete the stale `devdb_*` caches
`agamemnon/engine/uarch/agrv2k/devdb_*` are **gitignored generated caches**. They do not update
themselves and `git status` will not tell you they are stale.

### 6. Regenerate `devdb_strict` immediately  <-- DO NOT LEAVE IT DELETED
Four hash-pinned composers (`qualification/compose_mcu_ahb_public*.py`) read `devdb_strict`
**directly** and do not regenerate it. Deleting it without regenerating gives
`FileNotFoundError: devdb_strict/dev_pips.csv` in 8 tests.

```
cd agamemnon/engine && python emit_uarch_db.py --arch arch.py --data ../chipdb \
  --out uarch/agrv2k/devdb_strict \
  --env AGAMEMNON_CONDUCTION_GATE=1 --env AGAMEMNON_HW_CARRY=1 --env AGAMEMNON_LEDPADS=1 \
  --env AGAMEMNON_STRICT_GATE=1 --env AGAMEMNON_XBAR_CONDUCT=1 --env AGAMEMNON_CLEAN_SEL_GATE=1
```

### 6.5 Regenerate the `status_overlay_*` chain if `dev_pips.csv` content changed  <-- THIRD PIN
Found 2026-08-21 by this document's first user. There is a **third** hash-pinned snapshot of
`devdb_strict`, separate from both the fingerprint pin and the research manifest:

- `agamemnon/engine/status_overlay_dev_pips.csv.gz`
- `agamemnon/engine/status_overlay_dev_belpins.csv.gz`
- `agamemnon/engine/status_overlay_devdb_manifest.json`
- a `DEVDB_MANIFEST_SHA256` constant pinned inside `agamemnon/engine/status_overlay.py`

Regenerate with `tools/generate_status_overlay_devdb.py`.

**When does this trigger?** Whenever the emitted `devdb_strict/dev_pips.csv` changes *content*, not
just when you add a pip. Note it carries a **`delay_ns` column** — so a pure timing-table change
alters it. These files are tracked, so `git status` shows them as an unexpectedly-stale diff rather
than as missing, which reads like accidental damage instead of a required step.

### 7. Update `tests/fixtures/chipdb_fingerprint_pin.json` -- AFTER step 3
**Ordering matters.** The manifest lives *inside* `chipdb/`, so regenerating it changes the
fingerprint. Compute the fingerprint last:

```python
import sys; sys.path.insert(0, 'tests'); import conftest
fingerprint, file_count = conftest.compute_chipdb_fingerprint()
```

Write a **dated reason** stating what changed, why it is safe, and **what it does not claim**. The
pin's own text forbids regenerating it mechanically to silence a failing test.

### 8. Full regression -- the only gate that catches everything
```
python -m pytest tests/ -q --no-header -p no:cacheprovider --tb=short -rf
```
~18 minutes. **D0 Rule 2 passing is NOT sufficient** — it verifies retained artifacts rebuild
byte-identically and says nothing about hash bindings or reviewed-composition contracts. It told me
"repack-neutral" on a change that then failed 20 tests.

## Reviewed artifacts: STOP, do not re-pin

If `compose_mcu_ahb_public*.py` reports **"candidate hash does not match reviewed artifact"**, that is
not a stale pin. Those composers *route a design* using `devdb_strict`; growing the strict graph makes
their router pick different paths, changing a **reviewed** artifact. This is the 2026-08-18 incident
class. **Escalate for review; do not update the hash.**

## Reverting

**A revert is not complete until the generated caches are regenerated.** `devdb_*` is gitignored, so
`git status` reports a clean tree while a stale cache silently changes routing and hash-pinned
composer output. On 2026-08-21 this left 3 tests failing for hours after a "clean" revert, and the
failures were mis-attributed to a concurrent agent.

Back up first, into a dated directory: `corpus_conduction.csv`, `mcu_ahb.py`,
`research_knowledge_manifest.json`, `chipdb_fingerprint_pin.json`, `test_feature_protocol.py`.
Then revert **and regenerate `devdb_strict`**.

## Checklist

```
[ ] 1. data change made
[ ] 2. new table registered with a consumer
[ ] 3. research_knowledge_manifest.json regenerated  (generator verified against current first)
[ ] 4. dependent count assertions updated, WITH comments
[ ] 5. stale devdb_* caches deleted
[ ] 6. devdb_strict regenerated
[ ] 6.5 status_overlay_* chain regenerated if dev_pips.csv content changed
[ ] 7. chipdb_fingerprint_pin.json updated AFTER step 3, with a dated reason
[ ] 8. full regression green
[ ] 9. no reviewed-artifact hash was re-pinned
```
