# Multi-bit sequential logic through the `agrv2k` uarch (silicon-proven)

This example runs **real multi-bit sequential logic on silicon through the fully-open `agrv2k` nextpnr
uarch** — the shippable backend (`nextpnr-generic --uarch agrv2k`). It is the milestone that makes the
uarch a *sequential* backend, not just a combinational one.

`examples/designs/counter_ahb.v` is a 4-bit counter whose bit 0 and bit 3 are read back over the MCU AHB
bus (`0x60000000`). Bit 3 only cycles when the carry propagates through all four bits, so observing all
four `(bit3,bit0)` states proves genuine multi-bit compute (not a stuck or toggle-only output).

**Silicon result:** `distinct=4` (values `0xc,0xd,0xe,0xf`, both read bits cycling) — it computes.

## Why this needs more than stock nextpnr

The AGRV2K fabric has two properties the open flow had to solve, both cracked here:

1. **Only some pips physically conduct.** A byte-correct config can still route through an electrically
   dead pip. So the device database is emitted **conduction-gated** (only silicon-conducting pips), and the
   uarch's `tile_adj` conducting graph is built from those same pips — placer and router agree exactly.
2. **Self-feedback + placement must conduct.** Registered feedback uses the slice's internal `Qin` path
   (`qin_pack`); cells that talk to each other must sit on **conducting tile-pairs**, which the uarch's
   conduction-aware placer (`pack_condplace`) arranges; and high-fanout nets are split by `fanout_split`
   (net replication) so each copy fits the fabric's conducting-fanout budget.

## The flow — one command

```
# builds the gated device on first use (cached), synths, routes on the uarch, and writes the .bin.
# --verify then cycle-sims the routed netlist and prints the AHB read-values it will produce (hardware-free):
agamemnon build examples/designs/counter_ahb.v -o counter.bin --uarch --verify
#   -> "MCU read-values the design will produce (AHB 0x60000000): [0, 1, 2, 3]"
#      "MCU_DOUT bind (h<k> -> AHB bit k): OK"   (a scrambled bind would fail the build)

# silicon: SRAM-inject and read 0x60000000 -> distinct values = it computes
#    (the workbench's tools/ahb_read_run.py drives the OpenOCD inject + AHB read)
```

## Verifying without a board

`agamemnon verify <routed.json>` (or `build --verify`) **cycle-simulates the actual routed netlist** — the
`GENERIC_SLICE` INITs, the real `I[0..3]/Q` connectivity, and the `MCU_DOUT`→AHB-bit binding, all read from
the nextpnr `--write` JSON — and reports the exact set of values the MCU will read over `0x60000000`. It is
the ground truth of *what was built*, needing no hardware. With a silicon-observed set it also checks
**SOUND** (every observed value must be reachable in the sim — a spurious value means the silicon is not
faithfully executing the routed netlist) and the **bind** (the `h<k>`→bit-`k` mapping, catching read-bit
scrambles). For the counter it reports the reachable set `{0,1,2,3}`; on silicon the free-running readout
(`tools/ahb_read_run.py`) observes that same set, so `SOUND` passes and coverage reaches 100%.

`--uarch` selects this backend. `--cap N` sets the placer's cells-per-tile (default 2); `--maxfo M` sets the
tightest fanout floor for the escalation below (default 2). The build needs the uarch-built `nextpnr-generic`
— point `$AGAMEMNON_UARCH_NEXTPNR` at it (or have the uarch build first on `PATH`); build it with
`engine/uarch/agrv2k/build.sh`.

### What the one command does under the hood

1. **Device (cached):** emits a **conduction-gated** device DB with the hardware-carry pins + `CLKIN`
   clock source (`emit_uarch_db.py … --env AGAMEMNON_CONDUCTION_GATE=1 …`), copying in
   `master_conduction.csv`.
2. **Synth + Qin:** yosys to LUT4 logic, then `qin_pack.py` permutes each registered FF's self-feedback to
   the slice's internal `Qin` path (never routed — without it every counter/FSM freezes).
3. **Place & route with route-driven cap+fanout escalation.** Placement is the conduction-aware
   `pack_condplace` (`AGRV2K_CONDPLACE`) embedding cells on conducting tile-pairs of the gated graph. Two
   knobs are design-dependent and auto-tuned: **cells-per-tile `cap`** (a counter routes *spread* at cap 2;
   a shift register routes *packed* at cap 8 — co-located on one tile's conducting crossbar) and **fanout**
   (the conducting fanout limit is `>2`, so splitting nets a design doesn't need *corrupts* it). The flow
   sweeps `cap` ascending `{2,4,8}` **unsplit** and stops at the first that routes; only if all fail does it
   run `fanout_split` (net replication) at the largest cap, escalating tighter (`maxfo` 16 → 8 → 4 → 2).
4. **Open bitgen:** `to_bin.py` with the mesh-template crossbar resolver + `CLKIN` clock.

## Status and limits (honest)

**Silicon-proven (2026-07-09):** toggle FF, 2-bit counter, 4-bit counter — all read back distinct values
through the uarch (`counter_ahb.v` = `distinct=4`). The current CLI `--uarch` build of `counter_ahb.v`
produces a valid conduction-aware placement that `agamemnon verify` confirms computes `{0,1,2,3}` with a
sound bind and 0 unmapped pips; it is *functionally* equivalent to the proven design (the placer emits a
different-but-valid embedding than the original hand-run, so a silicon spot-check of the exact new bitstream
is the honest final step — the offline verifier is the trust anchor in the meantime).

**Builds clean through the CLI (routes, 0 unmapped; silicon spot-check pending):** the 8-bit counter
(`counter8_ahb.v`, cap 2) and an 8-bit Johnson counter (cap 8, auto-discovered by the sweep). The earlier
"8-bit fails at ~26 cells" was an artifact of the old always-split behaviour bloating the netlist; routing
unsplit-first keeps it at ~8–13 cells and it embeds fine. So the cap+fanout escalation both fixed small
designs *and* pushed the practical ceiling — and it auto-tunes, so no design-specific flags are needed.

**Known walls (unreachable at any cap/fanout — the scalable-placer frontier):** a 16-bit counter (wide
carry lookahead) and an 8-bit LFSR (XOR tap feedback) fail to route on the sparse conducting graph. These
need the scalable conduction-aware placer below, not a knob.

**Not yet — the SERV-scale goal.** A full soft RISC-V core (~1800 cells) does **not** route through this
flow. `pack_condplace` is a bounded-backtracking embedder on a sparse conducting graph; it comfortably
handles the tens-of-cells designs above but does not scale to a soft CPU. Getting there needs a **scalable
conduction-aware placer** (analytical/force-directed start with local conduction refinement, or a
conduction-aware seed for nextpnr's HeAP/SA) plus BRAM program-memory integration and pad-output for a
physical LED. Those are the next milestones; the sequential path they build on is what this example proves.

Also banked (built, silicon-diagnosed, deferred): the dedicated hardware-carry chain for wide arithmetic —
see the README "Banked" section. Wide arithmetic here runs via LUT + mesh carry instead.
