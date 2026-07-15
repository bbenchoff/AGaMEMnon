# Qualification data

This directory contains reproducible software checks, routed artifacts,
hardware oracles, hashes, and append-only observation records for AGaMEMnon's
supported feature set.

A successful route or FCB-accepted image is not, by itself, proof that a
physical path conducts. Software and silicon evidence are recorded separately.

## Isolated routing evidence

Record a source-to-observed-sink trial:

```bash
python -m agamemnon.engine.qualification_db record \
  qualification/routing_evidence.jsonl \
  --routed design_routed.json --net top/probe \
  --observed-wire X19Y13_IOMUX00 --verdict pass \
  --trial-id STABLE_ID --bitstream design.bin \
  --expected EXPECTED --observed OBSERVED
```

The recorder traces the unique routed path. A pass qualifies its unknown PIPs.
A dead-edge classification requires at least two independent failures with
exactly one unknown PIP. Other failures remain inconclusive. Duplicate trial
IDs are rejected.

```bash
python -m agamemnon.engine.qualification_db export \
  qualification/routing_evidence.jsonl qualification/routing_state.csv
python -m agamemnon.engine.qualification_db report \
  qualification/routing_evidence.jsonl --dev-pips DEVDB/dev_pips.csv
```

Negative isolated evidence has precedence over corpus attribution. The release
database contains 14 isolated dead-edge classifications. Whole-design
correlation is not a release blacklist.

## Selector table generation

```bash
python qualification/clean_sel_blocks.py sel_dataset.csv sel_edge_pairs.pkl \
  --runtime
```

The runtime table includes only physical keys with one observed selector pair.
Conflicting keys are excluded. The shipped artifact contains 659,759
conflict-free physical keys; architecture generation and bitgen enforce it.

## Hardware job queue

Long hardware runs can use the SQLite scheduler:

```bash
python -m agamemnon.engine.qualification_scheduler seed campaign.sqlite3 candidates.jsonl
python -m agamemnon.engine.qualification_scheduler claim campaign.sqlite3 --worker pico-com6
python -m agamemnon.engine.qualification_scheduler finish campaign.sqlite3 \
  --job-id ID --token LEASE_TOKEN --result pass --observed MEASUREMENT
python -m agamemnon.engine.qualification_scheduler stats campaign.sqlite3
```

The scheduler supplies atomic leases, retry limits, stale-worker recovery, and
immutable attempts. Queue completion does not qualify a route; accepted path
results must be recorded through `qualification_db`.

## Randomized RTL

```bash
python qualification/random_rtl_campaign.py --seeds 0:8 \
  --widths 16,32,64 --modes lfsr,xorshift,mixed --freq 25 \
  --out-dir .tmp/random_matrix \
  --evidence qualification/random_rtl_evidence.jsonl
```

Each accepted row completes synthesis, placement, router2, requested timing,
strict bitgen, and routed-netlist simulation. `random_hardware_evidence.jsonl`
ties selected source, routed JSON, and bitstream hashes to silicon observations.

For long-period designs, the AHB-step generator advances state on a qualified
`hwrite && htrans[1]` event so firmware can observe one deterministic step at a
time. Its firmware source is `ahb_step_stub.c`.

## Dedicated feature evidence

| File | Accepted scope |
|---|---|
| `carry_evidence.jsonl` | same-tile short carry and one 32-bit chain through the qualified 33-site corridor |
| `mcu_ahb32_read_evidence.jsonl` | simultaneous 32-bit fabric-to-MCU read |
| `mcu_ahb32_write_evidence.jsonl` | protocol-valid four-lane groups covering HWDATA[31:0] |
| `left_edge_output_evidence.jsonl` | L48 PIN_25 through PIN_28 harness mapping and output behavior |
| `timing_evidence.jsonl` | exact image, configured clock, model result, and hardware oracle |
| `bram_evidence.jsonl` | one x18 Port-A path and one x2 Port-B read/control corridor |
| `example_evidence.jsonl` | reproducible SERV and serial-mux build/simulation/hardware records |
| `serv_compliance_evidence.jsonl` | named SERV instruction-signature workload |
| `io_evidence.jsonl` | physical-pad routing observations |

The accepted scope is deliberately narrower than the hardware block's full
theoretical feature set. Evidence for one package, tile, width, route, or mode
does not qualify another.

## SERV signature workload

`serv_rv32i_smoke.S` is the source for the instruction words in
`serv_rv32i_smoke.v`. It computes signature 19 using dependent `addi`, `slli`,
and `xori`, checks not-taken `bne` and taken `beq`, stores the result, and loops
with backward `jal`. The failure path stores zero.

The signature and heartbeat observers use the same program, CPU, and
true-dual-port register-file source:

```bash
agamemnon build qualification/serv_rv32i_smoke.v --uarch \
  --pcf qualification/serv_rv32i_smoke_L48.pcf --freq 10 --verify \
  --write-routed qualification/serv_rv32i_smoke_L48_routed.json \
  -o serv_rv32i_smoke_L48.bin
agamemnon build qualification/serv_rv32i_heartbeat.v --uarch \
  --pcf qualification/serv_rv32i_smoke_L48.pcf --freq 10 --verify \
  --write-routed qualification/serv_rv32i_heartbeat_L48_routed.json \
  -o serv_rv32i_heartbeat_L48.bin
```

On the L48 fixture, PIN_10 is reset and PIN_25 is the observation output. The
signature image is low in reset and high on success. The heartbeat image is
low in reset and toggles while repeatedly returning to the success block.

This qualifies only the named instructions and true-dual-port register-file
path. It is not a complete RISC-V architectural test suite.

## Package-specific evidence

`left_edge_output_evidence.jsonl` applies to the qualified L48 board only:

```text
PIN_25 -> Pico GP12
PIN_26 -> Pico GP13
PIN_27 -> Pico GP16
PIN_28 -> Pico GP17
```

Do not apply this wiring or electrical claim to L100, L64, Q32, or another
board.

## Record policy

Evidence logs are append-only audit data. Corrections add a new record that
references the superseded record. Product support is defined by
`docs/STATUS.md`, not by the existence of an individual exploratory record.
