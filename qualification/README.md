# Qualification data

This directory contains reproducible software checks, routed artifacts,
hardware oracles, hashes, and append-only observation records for AGaMEMnon's
supported feature set.

`evidence_manifest.json` pins the current byte prefix of every JSONL ledger.
`python tools/validate_evidence.py` rejects rewrites or truncation while
allowing validated records to be appended. New ledgers must be declared. The
gate also validates JSON/schema policy, SHA-256-shaped fields, duplicates, and
machine-specific home paths, and runs in CI.

One historical exception remains explicit: the 2026-07-15 PIN_26 record has a
63-character `bitstream_sha256`, and the original image is not retained. The
record stays immutable; repeat PIN_26 qualification with a retained artifact
and append a superseding record rather than editing history.

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
python qualification/clean_sel_blocks.py sel_dataset.csv sel_edge_pairs.agdb \
  --runtime
```

The runtime table includes only physical keys with one observed selector pair.
Conflicting keys are excluded. The shipped artifact contains 659,759
conflict-free physical keys; architecture generation and bitgen enforce it.
AGDB schema 1 is deterministic compressed JSON with bounded decoding; runtime
loading does not execute Python objects.

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
| `mcu_ahb_constant_slave_evidence.jsonl` | L48 silicon qualification of the constant-ready, OKAY-only combinational External-AHB endpoint, including all 32 read-data lanes and no-effect writes |
| `mcu_bus_clock_evidence.jsonl` | L48 pure-open qualification of direct-D sites X14Y11 slice4 through slice7, an eight-state three-bit counter, a 16-bit long-period LFSR, exact 1:1 LFSR-step/MTIME-tick delivery at undivided 10 MHz HSI on default `bus_clk = sys_gck`, and GPIO4.1-fed synchronous reset-to-zero/re-arm; hard `MCU_RESETN`, PLL3, and unrestricted direct-D lowering remain open |
| `mcu_haddr5_logic_evidence.jsonl` | L48 pure-open qualification of HADDR[5] logic ingress through an isolated HADDR[5:4] XOR over all 256 addresses; no wider register-bank or protocol claim |
| `mcu_haddr3_logic_evidence.jsonl` | L48 pure-open qualification of HADDR[3] logic ingress over all 256 addresses; HTRANS[1] was low at the observation phase, so no new HTRANS or wider protocol claim |
| `mcu_local_int_evidence.jsonl` | L48 differential qualification of `local_int[3:0]` through `mie/mip[19:16]` and causes 19:16, plus simultaneous safe-low tie-off |
| `mcu_local_int_independent_route_evidence.jsonl` | Four distinct source nets routed simultaneously to `local_int[3:0]`, with each lane triggered and observed independently on L48; no pending/acknowledge/re-arm claim |
| `mcu_local_int0_evidence.jsonl` | Superseded first-lane trial retained as append-only historical evidence |
| `mcu_slave_ahb_hrdata_route_evidence.jsonl` | Hardware-free vendor-selector and strict-open route evidence for all 32 fabric-master HRDATA lanes in bounded groups and one simultaneous full-width placement; no transaction or silicon claim |
| `mcu_slave_ahb_request_control_route_evidence.jsonl` | Hardware-free shared-safe-low route evidence for all 11 fabric-master request qualifiers; no independent-source, transaction, or silicon claim |
| `mcu_slave_ahb_request_payload_route_evidence.jsonl` | Vendor and strict-open evidence for all 64 fabric-master request payload lanes from one dual-output safe-low source; no independent-source, transaction, or silicon claim |
| `mcu_dma_request_route_evidence.jsonl` | Hardware-free vendor-selector and strict-open evidence for all 16 DMA request endpoints from one shared safe-low source; no independent-source, protocol, or silicon claim |
| `mcu_dma_response_route_evidence.jsonl` | Hardware-free vendor-selector and strict-open evidence for all eight DMA clear/terminal-count response lanes routed independently; no protocol or silicon claim |
| `analog_adc0_db0_route_evidence.jsonl` | Hardware-free vendor-selector and strict-open evidence for read-only ADC0 result bit 0 routing; no ADC configuration, ownership, electrical, or silicon claim |
| `analog_adc0_db1_route_evidence.jsonl` | Hardware-free vendor-selector and strict-open evidence for read-only ADC0 result bit 1 routing; no ADC configuration, ownership, electrical, or silicon claim |
| `analog_adc0_eoc_route_evidence.jsonl` | Hardware-free vendor-selector and strict-open evidence for the read-only ADC0 end-of-conversion route; no ADC configuration, ownership, electrical, or silicon claim |
| `mcu_stop_route_evidence.jsonl` | Hardware-free exact route evidence for the typed MCU stop-status source to one known MCU observation sink; no polarity, gating, wake, or silicon claim |
| `left_edge_output_evidence.jsonl` | L48 PIN_25 through PIN_28 harness mapping and output behavior |
| `timing_evidence.jsonl` | exact image, configured clock, model result, and hardware oracle |
| `bram_evidence.jsonl` | one x18 Port-A path, one x2 Port-B read/control corridor, bounded x9 negative controls including independent AddressA[3:5] terminal trials, and an isolated passing HADDR[4:2] boundary probe |
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
AGAMEMNON_SYSCLK=25 AGAMEMNON_HSE=8 \
agamemnon build qualification/serv_rv32i_smoke.v --uarch \
  --pcf qualification/serv_rv32i_smoke_L48.pcf --freq 10 --verify \
  --write-routed qualification/serv_rv32i_smoke_L48_routed.json \
  -o serv_rv32i_smoke_L48.bin
AGAMEMNON_SYSCLK=25 AGAMEMNON_HSE=8 \
agamemnon build qualification/serv_rv32i_heartbeat.v --uarch \
  --pcf qualification/serv_rv32i_smoke_L48.pcf --freq 10 --verify \
  --write-routed qualification/serv_rv32i_heartbeat_L48_routed.json \
  -o serv_rv32i_heartbeat_L48.bin
```

The recorded hardware-qualified images used a 25 MHz fabric clock from the
board's 8 MHz HSE and the L48 left-pad output mapping. These pack inputs are
stored as `pack_environment` in `serv_compliance_evidence.jsonl`; the evidence
gate clears ambient `AGAMEMNON_*` settings and replays exactly that record. Text
artifact hashes use canonical LF bytes (`sha256-lf-v1`), independent of the
checkout platform's newline convention.

`regen_serv_evidence.py` dry-runs the current selector replay. If a newly
qualified selector table changes only a derivable packing metric, use its
`--append-trial-id` mode to add a superseding replay record; never rewrite the
checked historical record. The 2026-08-03 replay records the local-interrupt
table promotion changing the signature image's clean-selector split from
4021 to 4020, with identical image hashes and inherited silicon observations.

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
