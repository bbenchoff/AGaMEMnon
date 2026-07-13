# Silicon qualification evidence

This directory holds append-only, hardware-backed evidence for the conservative
AGRV2K routing graph.  A route is not promoted merely because nextpnr completed
or the configuration engine accepted its bitstream.

Record an isolated digital-path trial with:

```text
python -m agamemnon.engine.qualification_db record qualification/routing_evidence.jsonl \
  --routed design_routed.json --net top/probe \
  --observed-wire X19Y13_IOMUX00 --verdict pass \
  --trial-id <stable-id> --bitstream design.bin \
  --expected <expected-behaviour> --observed <measured-behaviour>
```

The recorder traces only the unique driver-to-observed-sink path.  A passing
trial proves the PIPs on that path.  A failing trial identifies a suspect only
when exactly one path PIP was not already proven live; it takes at least two
independent isolated failures before that PIP is classified dead.  Other
failures remain inconclusive.  Duplicate trial IDs are rejected.

Generate a reviewable state table or a device coverage report with:

```text
python -m agamemnon.engine.qualification_db export \
  qualification/routing_evidence.jsonl qualification/routing_state.csv
python -m agamemnon.engine.qualification_db report \
  qualification/routing_evidence.jsonl --dev-pips <devdb>/dev_pips.csv
```

Negative evidence has absolute precedence in the architecture.  Checked-in
dead edges live in `agamemnon/chipdb/dead_edges_silicon.csv`; conflicts with
legacy positive corpora are removed before the device graph is emitted.

## Durable campaign scheduling

Long hardware campaigns use a SQLite queue with atomic leases, retry limits,
stale-worker recovery, and an immutable attempt history.  Seed it with JSONL:

```json
{"target_pip":"X2Y3_OMUX01.X2Y3_RMUX04","exact_path":["X2Y3_LUT_OUT.X2Y3_OMUX01","X2Y3_OMUX01.X2Y3_RMUX04","X2Y3_RMUX04.X3Y3_IMUX02"],"routed_sha256":"<sha256>","bitstream_sha256":"<sha256>","oracle":{"kind":"digital_toggle","pin":6,"minimum_edges":2},"board":"ag32-l48-001","port":"COM6"}
```

Then lease and finish jobs with:

```text
python -m agamemnon.engine.qualification_scheduler seed qualification/campaign.sqlite3 candidates.jsonl
python -m agamemnon.engine.qualification_scheduler claim qualification/campaign.sqlite3 --worker pico-com6
python -m agamemnon.engine.qualification_scheduler finish qualification/campaign.sqlite3 \
  --job-id <id> --token <lease_token> --result pass --observed <measurement>
python -m agamemnon.engine.qualification_scheduler stats qualification/campaign.sqlite3
```

The scheduler controls ownership and preserves every attempt.  Workers still
record accepted path evidence with `qualification_db`; queue completion alone
does not promote a PIP into the trusted routing graph.
