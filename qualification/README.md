# Qualification data

This directory contains reproducible software checks, routed artifacts,
hardware oracles, hashes, and append-only observation records for AGaMEMnon's
supported feature set.

`evidence_manifest.json` pins the current canonical-LF byte prefix of every
JSONL ledger. Checkout line endings do not change the prefix identity.
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

Negative evidence has precedence over corpus attribution. The release database
carries a small conservatively blocked negative-evidence edge set. It is **no
longer** described as "14 isolated dead-edge classifications": the trials were
not isolated -- they came from one large, congested MCU-exit design, so the
per-edge attribution was a congestion-context artifact. Six of the original
fourteen are board-proven to conduct and are now admitted; the remaining eight
stay blocked as **unverified, not proven-dead**. Whole-design correlation is not
a release blacklist. See `docs/CONDUCTION_REFRAME_STATUS.md`.

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
| `mcu_ahb32_write_evidence.jsonl` | protocol-valid four-lane groups covering HWDATA[31:0], plus one exact simultaneous 16-lane posted-capture checkpoint that replays source-to-route with `--qualified-checkpoint`; the latter is not a 16-bit register bank |
| `mcu_ahb_constant_slave_evidence.jsonl` | L48 silicon qualification of the constant-ready, OKAY-only combinational External-AHB endpoint, including all 32 read-data lanes and no-effect writes |
| `mcu_bus_clock_evidence.jsonl` | L48 pure-open qualification of direct-D sites X14Y11 slice4 through slice7, an eight-state three-bit counter, a 16-bit long-period LFSR, exact 1:1 LFSR-step/MTIME-tick delivery on default `bus_clk = sys_gck` (a ratio; the absolute rate once inferred as 10 MHz is an open question -- MTIME later measured 14.08 MHz), and GPIO4.1-fed synchronous reset-to-zero/re-arm; hard `MCU_RESETN`, PLL3, and unrestricted direct-D lowering remain open |
| `mcu_haddr5_logic_evidence.jsonl` | L48 pure-open qualification of HADDR[5] logic ingress through an isolated HADDR[5:4] XOR over all 256 addresses; no wider register-bank or protocol claim |
| `mcu_haddr3_logic_evidence.jsonl` | L48 pure-open qualification of HADDR[3] logic ingress over all 256 addresses; HTRANS[1] was low at the observation phase, so no new HTRANS or wider protocol claim |
| `mcu_ahb_register_bank_evidence.jsonl` (HSIZE1 corridor) | One exact L48 HSIZE[1]-to-logic corridor distinguishes 256 word, halfword, and byte reads at a fixed address with zero errors after correcting the generic selector pair to the vendor-measured `CFG_RMUX5 {42,48}`. This qualifies a live combinational control input on that exact route only; it does not qualify byte strobes, subword storage, arbitrary placement, or its composition with the 16-bit scratch. |
| `mcu_hwdata_logic_route_evidence.jsonl` | L48 HWDATA consumer-footprint evidence: HWDATA6 registered capture at X14Y12 slice15 and retained HWDATA7 capture at X14Y11 slice0 are positive; X14Y10 slice1 and X14Y12 slice15 combinational identity-buffer modes are negative. The latter blocks reuse as a generic fanout root and does not weaken the registered captures |
| `mcu_ahb_register_bank_evidence.jsonl` | L48 bounded register-bank evidence for the complete-byte ID/scratch/counter/W1C bank, GPIO reset, one controlled wait, exact 32-bit reads, and retained routing/commit negatives. Simultaneous HADDR[1:0] commit gating qualifies aligned byte/halfword reads and writes across the one-byte scratch, ID, counter, and W1C classes. SINGLE transfers are supported; non-SINGLE acceptance is retired and all seven nonzero HBURST encodings fail closed offline with HRESP and no mutation. The ledger also records the hardware-unqualified soft-UART register-window artifact and its pinned loopback/fail-closed regression. Wider writable state remains unsupported. The strict one-hot local-interrupt command bank is retained here as well; failures remain negatives, never dead-PIP claims |
| `mcu_ahb_register_bank_evidence.jsonl` (16-bit checkpoint) | One exact L48 held scratch passes 100 aligned word patterns, SRAM-churn retention, repeated reads, one wait and GPIO reset across HRDATA[15:0]. |
| `mcu_ahb_bank16_write_isolation_evidence.jsonl` | Historical deterministic derivative qualifying write-commit isolation of +0 against aligned writes to +4/+8/+c through HADDR[3:2]. That artifact deliberately aliases reads; the later `mcu_ahb_bank16_read_isolation_evidence.jsonl` supersedes it as the current checkpoint. |
| `mcu_ahb_bank16_read_isolation_evidence.jsonl` | One exact L48 held-scratch derivative qualifies low-16 aligned word reads at +0/+4/+8/+c as `[state,0,0,0]`, with four decoder controls and four repeated real-decoder runs. Three further SRAM-only runs qualify CPU-visible aligned unsigned subword reads. Registered-profile exact route replay reproduces its qualified raw/compressed bitstreams byte-for-byte from a generated checkpoint-derived structural fixture. A second hash-bound profile changes exactly two decoder INITs to move that scratch to public offset +4; three 32-pattern/160-observation SRAM-only runs qualify aligned word/halfword +4, bytes +4/+5, representative foreign-offset rejection, decoded word/subword reads, retention and reset. Neither fixture is portable canonical RTL, and this ledger alone makes no coexistence claim; the later public16 ledger below qualifies the exact composition. Misaligned and signed loads, raw HRDATA[31:16], higher/full-window decode, bursts, arbitrary placement/width and a generic generator remain open. |
| `mcu_ahb_public16_evidence.jsonl` | Exact L48 HSE=8 SYSCLK=10 composition of ID8 `0x4d` at +0, held scratch16 at +4, counter3 at +8, and W1C1 at +c. Four sequential SRAM-only runs pass scratch word/halfword/independent-byte semantics, isolation, coexistence, reset, counter coverage, and qualification-hook W1C set/clear with set priority. Composer, checker, generated structural mirror, SDK profile, routed checkpoint, and raw/compressed outputs are hash-bound. Raw HRDATA[31:16], canonical 32-bit identity, production status-set ingress, bursts on this composition, arbitrary placement/width, other packages, and a generic 32-bit ABI remain open. |
| `mcu_ahb_public32_evidence.jsonl` | Default exact L48 HSE=8 SYSCLK=10 composition of canonical ID32 `0x4147414d` at +0 and zero-extended scratch16/counter3/W1C1 at +4/+8/+c. Three sequential SRAM-only full-map runs pass exact LW values, every ID byte/halfword lane, unsigned-load zero extension, the entire retained scratch/counter/W1C/reset/isolation matrix, and strict packing with zero selector debt. Composer, checker, generated structural mirror, SDK profile, routed checkpoint, raw/compressed outputs, and the relocated status-pending branch are hash-bound. Production status-set ingress, bursts/full-window decode, misaligned/signed loads, arbitrary placement/width, other packages, and a generic register-bank generator remain open. |
| `mcu_ahb_public32_autoevent_w1c_evidence.jsonl` | Exact public32 derivative in which the existing HCLK-synchronous three-bit fabric counter emits one reset-rearmed count-seven event into W1C status without an AHB set write or GPIO stimulus. The unchanged negative, dual-source OR control, and three production runs have distinct causal signatures (`0x04`, `0x15`, `0x11`) while the complete public32 matrix stays clean. This proves one bounded autonomous synchronous source, not a generic user-net socket, asynchronous/CDC contract, interrupt ABI, arbitrary application overlay, or generic bank. Composer, controls, checker, generated fixture, SDK profile, logs, and raw/compressed images are hash-bound. |
| `mcu_ahb_public32_gpio5_w1c_evidence.jsonl` | Exact public32 derivative replacing the bit1 qualification hook with MCU GPIO5 DATA0/OUT_EN0 as an independently routed sustained-level W1C set source. One common firmware gives distinct negative (`status_errors=162`), OR-control (`2`), and production (`0`) signatures; the production image then repeats three times with the full nine-group public32 regression clean. GPIO5 low permits hold/clear, high sets or reasserts with set priority, and reset dominates. This is a software-controlled hard-boundary qualification source, not a package-pin input, autonomous event, edge/pulse/CDC guarantee, interrupt, or generic `STATUS_SET` owner. Composer, both causal checkpoints, checker, generated structural mirror, SDK profile, logs, and raw/compressed images are hash-bound. |
| `mcu_gpio5_route_evidence.jsonl` | Exact L100/L48 GPIO5 data/OE/input routing; retained L48 negatives, differential terminal bisection, and pure-open silicon qualification of data/OE lanes 0 and 1 through input lane 2 with coherent inactive-terminal defaults |
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
| `left_input_evidence.jsonl` | Exact single-consumer direct-input truth tables for L48 PIN_25 through PIN_28 |
| `timing_evidence.jsonl` | exact image, configured clock, model result, and hardware oracle |
| `bram_evidence.jsonl` | one x18 Port-A path, one x2 Port-B read/control corridor, bounded x9 recovery negatives, the exact route-through/HSE boundary fix, all nine x9 data bits through exact per-lane projections, the simultaneous q4/q5 BBMUXE6 correction, a strict-open 256-word simultaneous identity bundle, three INIT projections over the 0..255 range, and the HADDR11/AddressA12 word-0/512 discriminator |
| `example_evidence.jsonl` | reproducible SERV and serial-mux build/simulation/hardware records |
| `serv_compliance_evidence.jsonl` | named SERV instruction-signature workload |
| `io_evidence.jsonl` | Physical-pad routing observations, including the strict-clean four-link L48 node image with four distinct dynamic-OE trunks and exact input corridors. The node record is build-only and explicitly carries no electrical claim |

The accepted scope is deliberately narrower than the hardware block's full
theoretical feature set. Evidence for one package, tile, width, route, or mode
does not qualify another.

## SERV signature workload

`serv_rv32i_smoke.S` is the source for the instruction words in
`serv_rv32i_smoke.v`. It computes signature 19 using dependent `addi`, `slli`,
and `xori`, checks not-taken `bne` and taken `beq`, stores the result, and loops
with backward `jal`. The failure path stores zero.

The signature and heartbeat observers use the same program, CPU, and
x2 dual-port-shaped register-file source:

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

The all-artifact A0 gate applies the same rule to routed JSON inputs under
`routed-sha256-lf-v1+bitstream-sha256-binary-v1`; emitted `.bin` identities
remain raw-byte SHA-256 values. The prior manifest accidentally pinned one
Windows checkout's EOL bytes. In particular,
`mcu_hwdata6_identity_buffer_20260804_routed.json` had 168 CRLF endings and
six lone LF endings, all six following generated `src` attributes. Its old
hash therefore matched only that mixed-EOL working copy, not an LF or uniform
CRLF form. Canonical LF matches the tracked Git blob and changes no JSON value
or emitted image.

`regen_serv_evidence.py` dry-runs the current selector replay. If a newly
qualified selector table changes only a derivable packing metric, use its
`--append-trial-id` mode to add a superseding replay record; never rewrite the
checked historical record. The 2026-08-03 replay records the local-interrupt
table promotion changing the signature image's clean-selector split from
4021 to 4020, with identical image hashes and inherited silicon observations.

On the L48 fixture, PIN_10 is reset and PIN_25 is the observation output. The
signature image is low in reset and high on success. The heartbeat image is
low in reset and toggles while repeatedly returning to the success block.

This qualifies only the named instruction/workload observations. Direct
hard-output probes later showed that the wrapper-visible store discriminator
does not prove BRAM array mutation, so this record does not qualify hard-BRAM
write ingress or a true-dual-port storage path. It is not a complete RISC-V
architectural test suite.

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
