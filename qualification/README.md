# Qualification evidence

This directory contains reproducible qualification tools and append-only
evidence for the AGRV2K release boundary. A successful nextpnr route or an
FCB-accepted image is not, by itself, evidence that a physical path conducts.

## Routing evidence

Record an isolated digital-path trial:

```bash
python -m agamemnon.engine.qualification_db record \
  qualification/routing_evidence.jsonl \
  --routed design_routed.json --net top/probe \
  --observed-wire X19Y13_IOMUX00 --verdict pass \
  --trial-id STABLE_ID --bitstream design.bin \
  --expected EXPECTED --observed OBSERVED
```

The recorder traces the unique driver-to-observed-sink path. A pass promotes
the PIPs on that path. A failure identifies a dead edge only when exactly one
path PIP remains unknown and at least two independent isolated failures agree.
Other failures remain inconclusive. Duplicate trial IDs are rejected.

Export state or coverage reports:

```bash
python -m agamemnon.engine.qualification_db export \
  qualification/routing_evidence.jsonl qualification/routing_state.csv
python -m agamemnon.engine.qualification_db report \
  qualification/routing_evidence.jsonl --dev-pips DEVDB/dev_pips.csv
```

Negative isolated evidence has absolute precedence. The checked-in
`agamemnon/chipdb/dead_edges_silicon.csv` contains 14 such edges. Static
whole-design trials and pass/fail route correlations never promote a dead
edge.

## Exact selector recovery

`clean_sel_blocks.py` streams the large selector corpus and attributes active
selectors to each destination node's independent RMUX/IMUX block:

```bash
python qualification/clean_sel_blocks.py sel_dataset.csv sel_edge_pairs.pkl \
  --runtime
```

Runtime output contains only physical keys with one observed pair. Conflicting
keys are excluded rather than majority-voted. The shipped release artifact has
659,759 conflict-free physical keys; bitgen and architecture generation both
enforce the clean-selector boundary.

## Durable hardware queues

Long campaigns use a SQLite queue with atomic leases, retry limits,
stale-worker recovery, and immutable attempts:

```bash
python -m agamemnon.engine.qualification_scheduler seed campaign.sqlite3 candidates.jsonl
python -m agamemnon.engine.qualification_scheduler claim campaign.sqlite3 --worker pico-com6
python -m agamemnon.engine.qualification_scheduler finish campaign.sqlite3 \
  --job-id ID --token LEASE_TOKEN --result pass --observed MEASUREMENT
python -m agamemnon.engine.qualification_scheduler stats campaign.sqlite3
```

Queue completion does not promote a route. Accepted path evidence must still
be recorded through `qualification_db`.

## Randomized RTL

Run the hardware-free matrix:

```bash
python qualification/random_rtl_campaign.py --seeds 0:8 \
  --widths 16,32,64 --modes lfsr,xorshift,mixed --freq 25 \
  --out-dir .tmp/random_matrix \
  --evidence qualification/random_rtl_evidence.jsonl
```

A passing row means synthesis, regional placement, router2, target timing,
strict bitgen, and routed-netlist simulation passed. The checked-in matrix is
72/72. It is software evidence until an exact routed image is run on hardware.

`random_hardware_evidence.jsonl` records exact source, routed-netlist, and
bitstream hashes plus placement/density and observations. Those records retain
earlier SERV placement trials as historical evidence. The current public SERV
result is the true-dual-port example in `example_evidence.jsonl`; static or
superseded alternatives do not classify their component PIPs.

For long-period designs, deterministic AHB stepping is stronger than
free-running polling. `generate_ahb_step()` advances state on a qualified
`hwrite & htrans[1]` event, then firmware reads the result after each explicit
step. The supporting firmware source is `ahb_step_stub.c`.

## Route contrast

`route_contrast.py` produces an experimental correlation set:

```bash
python qualification/route_contrast.py \
  --passing live0.json live1.json \
  --failing static0.json static1.json \
  --min-fail 2 --csv contrast.csv
```

Its output is for isolation planning and copied-device rerouting experiments.
It is never a release blacklist. Five high-confidence correlation candidates
have been isolated and proved live, which is why correlation remains
diagnostic only.

## Timing evidence

`timing_evidence.jsonl` records model, routed-netlist, bitstream, frequency,
nextpnr result, hardware oracle, and hashes. A functional clock smoke proves
that exact image operated at the configured clock; it does not characterize
clock skew, PVT margin, every route delay, or maximum Fmax.

## Carry evidence

`carry_evidence.jsonl` contains qualified single 4- and 8-stage same-tile
chains, two simultaneous 3-stage chains, and a 32-bit chain spanning the exact
recovered 33-site vendor corridor. Promoted images use a physical head seed,
`BYPASSEN=0`, zero predicted/unresolved selectors, SRAM-only loading, and a
post-trial board reset. The 32-bit trial sensitizes both recovered cross-tile
transitions; arbitrary seams are not inferred from it.

## MCU bridge evidence

`mcu_ahb32_read_evidence.jsonl` records a protocol-valid simultaneous 32-bit
fabric-to-MCU read that passed 64/64 exact patterns. The eight records in
`mcu_ahb32_write_evidence.jsonl` cover HWDATA[31:0] in four-bit groups, each
passing 64/64 patterns. Together they qualify every write-data lane, but not a
single simultaneous 32-bit capture or every AHB address/control/burst mode.

## Package IO evidence

`left_edge_output_evidence.jsonl` records the L48 harness fingerprint and the
PIN_25-28 isolated and concurrent output trials. The observed correspondence
is PIN_25/26/27/28 to Pico GP12/GP13/GP16/GP17. This evidence is explicitly
L48-only and must not be applied to another package.

## BRAM evidence

`bram_evidence.jsonl` distinguishes the dynamic archived Port-A x18 corridor,
fresh static builds, and the exact x2 Port-B route qualified on 2026-07-14.
That Port-B image produced four sequential values over 500 samples with zero
predicted or unresolved selectors. It qualifies only the selected read/control
corridor. Other widths, tiles, arbitrary fresh corridors, initialization
packing, and collision modes remain unqualified.

## Evidence files

| File | Scope |
|---|---|
| `routing_evidence.jsonl` | isolated path promotion/classification records |
| `random_rtl_evidence.jsonl` | software randomized build matrix |
| `random_hardware_evidence.jsonl` | randomized and SERV hardware observations |
| `carry_evidence.jsonl` | dedicated-carry hardware trials |
| `mcu_ahb32_read_evidence.jsonl` | simultaneous 32-bit External-AHB read trial |
| `mcu_ahb32_write_evidence.jsonl` | protocol-valid four-lane write groups covering HWDATA[31:0] |
| `left_edge_output_evidence.jsonl` | L48 PIN_25-28 fingerprint and output trials |
| `timing_evidence.jsonl` | timing model and hardware clock trials |
| `bram_evidence.jsonl` | Port-A/Port-B BRAM trials |
| `example_evidence.jsonl` | reproducible build, simulation, and hardware results for shipped examples |
| `serv_compliance_evidence.jsonl` | multi-instruction SERV signature trials, including non-promoted failures |
| `io_evidence.jsonl` | physical-pad routing trials, including dense-design route failures |

Evidence logs are append-only. Corrections add a new record that references
the earlier trial; they do not delete an inconvenient observation.
