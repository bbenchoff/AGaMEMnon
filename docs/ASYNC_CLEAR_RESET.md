# Async-clear reset (N4.2): supported scope and qualification — 2026-09-25

## What this admits

`ASYNC_CLEAR_POS_ZERO` — a positive-edge register with an active-high asynchronous clear to zero
(Verilog `always @(posedge clock or posedge reset) if (reset) q <= 0; else q <= d;`, and the
RTL-inverted active-low-input form, which yosys's `proc` pass normalizes to the identical
`$_DFF_PP0_` frontend cell) — is now admitted behind `AGRV2K_SHARED_CONTROL_ASYNC_CLEAR`, on by
default for ordinary `build --uarch` (witnessed-means-default-on). `--no-async-clear-reset` or
`AGRV2K_SHARED_CONTROL_ASYNC_CLEAR=0` restores the pre-N4.2 refusal.

Before this, `agamemnon/engine/features/shared_control.py`'s "N4.1" frontend oracle validated the
routed shape of an async-clear register but admitted none of it: every design using async reset was
refused at nextpnr ingress with `unsupported physical shared control ASYNC_CLEAR_POS_ZERO ...: control
graph, selector codewords, and HIL qualification are absent`.

## The evidence

Two board-witnessed vendor (af.exe) images built from AG32-Docs
`tools/vendor_witness/designs_open/clk_rst_high.v` / `clk_rst_low.v` (ported here as
`examples/async-clear-reset/clk_rst_high.v` / `clk_rst_low.v`) — a 13-bit free-running counter cleared
by the board's physical reset pin, one active-high, one RTL-inverted — pass on real silicon
(AG32-Docs `results/clock_20260925/RESULT_clock_clk_rst_*.json`).

Decoding both images with `agamemnon to-agasc` and `agamemnon.engine.control_encode.bit_position`
(the same formula already board-validated for `CFG_TILECLKENMUX`/`CFG_TILESYNCMUX`, and independently
cross-checked here against the 2026-09-03 vendor differential-override sweep at a different tile,
memory `ag32-config-bit-extractor-replay-2026-09-03`, which measured `CFG_TILEASYNCMUX` landing
exactly inside the byte range the formula predicts) shows:

- Both images assert **the identical bit**: LogicTile (19,12), row 33 (the same row pair `sync`
  already uses for its own tile line, at columns 27–30 — `CFG_TILEASYNCMUX` — instead of `sync`'s
  columns 31–33), column 29 (`CFG_TILEASYNCMUX` index 1) — LogicTile line 1, source `ctrl_a` in
  `control_encode.py`'s naming, matching the exact same `CtrlMUX -> tile-line` graph shape
  `tile_control_edges.csv` already uses for clock-enable and sync.
- The routed netlist's `alta_asyncctrl` instance for the design's async source is at `(19,12,z=0)`,
  `AsyncCtrlMux=2'b10` ("passes Din"); every registered bit of the 13-bit counter shares this one
  signal.
- Per-slice `CFG_ASYNCMUX<z>` (the selector at `W(4z)`/column 32 that picks which of the tile's two
  async lines a given slice takes) reads **0 for all 13 registers** in both images — i.e. the default,
  unconfigured value already selects the line this route uses. Nothing per-slice needs to be set for
  this composition.
- One further, unresolved difference (`CFG_TILEASYNCMUX` column 27, index 3) differs between the two
  images. It is `logictile_asyncmux3.json`'s own per-tile "clocked tile" bit (owned by the unrelated
  `clocks` feature, confirmed by a real `BitOwnershipError` when this module tried to also claim it
  2026-09-25) and does not belong to async-clear's claim at all.

**Which `CtrlMUX` instance actually reaches `TileAsyncMUX`, and which SOURCE WIRE feeds it, needed
two corrections on 2026-09-25, both mid-session, both settled by direct raw-byte/route decoding rather
than left as a guess:**

1. The first open-flow board round (`clk_rst_high`/`clk_rst_low`/`clk_rst_multi_tile`, all `CtrlMUX00`)
   glitched during the held-reset window (`CONTROL_FAIL`/`RATE_FAIL`, `controls_static=False`) on the
   two single-tile designs. This was read as "wrong CtrlMUX instance" against AG32-Docs
   `docs/archive/2026-09/GPT6_ASYNC_CONTROL_ROUTE_INVENTORY_2026-09-05.md` /
   `tools/vendor_parity/gpt6_async_independent_sources_20260906/RESULT.json` (four vendor-routed seeds
   at LogicTile X14Y10: `CtrlMUX01 -> line 0`, `CtrlMUX03 -> line 1`), and the graph was switched to
   `CtrlMUX03`. Board round 2 flipped `controls_static` to `True` (a real, measured change) but still
   never resumed after release (`RATE_FAIL`). **This diagnosis was then itself corrected**: decoding
   vendor's own board-PASSING `clk_rst_high.bin` at raw byte level (bytes 6438/6439/6554/6555 --
   `CtrlMUX` instance 0's byte range per `agamemnon/chipdb/pips_full.csv`'s literal
   `(x,y,"CFG_CTRLMUX",sel,byte,mask)` rows, independent of any instance-number convention -- carry
   the bits; bytes 6670/6671/6786/6787, instance 3's range, are all zero) proves vendor's own async
   source at X19,Y12 is **`CtrlMUX00`**, not `CtrlMUX03`. This also matches, rather than contradicts,
   three pieces of this codebase's own PRE-EXISTING evidence: clock-enable/sync's own `LINE_OF_CTRL`
   (instances 0/1 drive line 1), `control_encode.CTRL_INDEX[(1,"ctrl_a")] == 0`, and
   `control_sets.py`'s "CtrlMUX 0/1 reach line 1" note. The X14Y10 finding apparently does not
   generalize to every tile the way it was first read as doing; `async_control_edges.csv` and
   `ASYNC_LINE_OF_CTRL`/`ASYNC_SOURCE_OF_CTRL` are back to `CtrlMUX00` (instance 0 only -- the one
   composition this codebase actually has evidence for).
2. Round 1's `CtrlMUX00` was thus the right INSTANCE all along, but used `RMUX94` -- a feeder witnessed
   in the 1,074-row `tile_control_edges.csv` corpus for **clock-enable's own net** at LogicTile 19,12,
   not for async's. Being witnessed to reach an instance for one net does not prove a different net can
   ride the same pip on this silicon (memory `ag32-silent-lookup-miss-class-2026-08-15`); AG32-Docs
   `tools/pipwit`'s ledger of 727 silicon-witnessed `SHARED_CONTROL` pips gives an independent, per-net-
   agnostic source of feeder evidence, so admission is now restricted to a whitelist
   (`async_feeder_wl.csv`, see below) rather than the whole unrestricted corpus.

Both corrections are recorded in `shared_control_graph.py`'s comments on `ASYNC_EDGE_TABLE` in full,
including why the second, cheaper-looking fix (just restricting to *some* witnessed feeder) was not
sufficient either -- see "Board results" below.

## What is claimed, and what is not

`control_encode.py`'s `FAMILY_SOURCE_COLUMNS["async_clear"]` claims exactly **one** physical
composition: LogicTile line 1 (row 33), source `ctrl_a` (CtrlMUX instance 0), column 29. `ctrl_b`, the
constant tie, and line 0 (row 34) all have **no board evidence** and stay refused
(`ControlEncodeError`/`SharedControlEmitError`) rather than guessed — matching this codebase's
existing fail-closed convention (see `sync`'s own per-slice line selector, marked "undetermined" for
the same reason). Concretely: `shared_control_graph.py`'s `_add_control_sinks` adds only the
`TileAsyncMUX01` sink bel (`X<x>Y<y>_ASYNCCLR1`, one per LogicTile) and `async_control_edges.csv`
carries only the `CtrlMUX00 -> TileAsyncMUX01` topology, so a design that needs `ctrl_b` or line 0 has
no route to it in the graph at all — the router cannot silently pick an unresolved composition.

`async_control_edges.csv`'s rows are honestly labelled `tier=formula`, not `tier=observed`: unlike
`tile_control_edges.csv`'s clock-enable/sync rows (harvested per tile from a large retained vendor
corpus), this table is the SAME uniform CtrlMUX0->TileAsyncMUX01 topology computed for all 132
LogicTiles from the tile-invariant formula, calibrated against the two real silicon images above (at
one tile) and cross-checked against the independent 2026-09-03 override sweep (at a different tile).
It is not a per-tile vendor observation.

### The feeder whitelist (`async_feeder_wl.csv`)

The wire->CtrlMUX00 feeder half is a SEPARATE evidence question from the CtrlMUX->TileAsyncMUX
destination half above, and needed its own restriction after point 2 above: when async_clear is the
only shared-control family active (no clock-enable/sync), `shared_control_graph.add_architecture`
now filters the 811-row shared wire->CtrlMUX input half of `tile_control_edges.csv` through
`async_feeder_wl.csv` before adding any pip, and refuses to add an unwhitelisted one at all (so an
unreachable design fails at nextpnr's own router self-check, naming the tile and terminal, rather than
silently routing through an unproven composition). The 114-row whitelist is:

- **1 row**: vendor-image-witnessed. `RMUX10 -> CtrlMUX00` at LogicTile (19,12), decoded directly from
  the board-PASSING `clk_rst_high.bin` (bytes 6438/6439/6554/6555).
- **113 rows**: ledger-witnessed. Every other silicon-witnessed `wire -> CtrlMUX00` `SHARED_CONTROL`
  pip in AG32-Docs `tools/pipwit`'s ledger (`ledger.State.load().witnessed`), across LogicTiles
  X14-X20-ish, **minus** `X19Y12_RMUX94.X19Y12_CtrlMUX00` -- witnessed for clock-enable's own net at
  that tile, but board-tested FALSE for async specifically in round 1 (`CONTROL_FAIL`). A negative
  board result is evidence too, so that one entry stays excluded on purpose even though the ledger
  admits it.

When both flags are active together, the whitelist does not apply -- clock-enable/sync's own,
separately-validated admission is not narrowed by a restriction scoped to async_clear's graph.

## Mechanism (mirrors native clock enable exactly)

- Frontend: `synth_pads.tcl` already tags `$_DFF_PP0_` with `AGRV2K_SHARED_CONTROL_MODE=ASYNC_CLEAR_POS_ZERO`
  (this predates N4.2; see `tests/test_shared_control_frontend.py`).
- Packing (`agrv2k.cc`): `is_packable_ff` admits `$_DFF_PP0_` behind the flag; `lift_async_clear`
  moves the "R" net (and, since `$_DFF_PP0_`'s clock pin is yosys's standard "C", not "CLK", the clock
  net too — `dff_to_lc` silently no-ops on a source port name it doesn't have) onto the packed
  `GENERIC_SLICE` as attributes, exactly like `lift_clock_enable` does for `EN`; `pack_shared_async_clear`
  groups slices by async-clear net, chunks at 16 slices/tile (matching the tile's 16 slice
  positions), and creates one `AGRV2K_TILE_CONTROL` cell per chunk, clustered at `z=18`
  (`ASYNC_CONTROL_Z_BASE`, past clock-enable's `z=16/17` so the two families can never collide).
- Architecture (`shared_control_graph.py`): `add_architecture`/`_add_control_sinks` add the
  `CtrlMUX00->TileAsyncMUX01` pip and `ASYNCCLR1` sink bel per LogicTile, gated on
  `AGRV2K_SHARED_CONTROL_ASYNC_CLEAR` **independently** of the base `AGRV2K_SHARED_CONTROL_GRAPH`
  flag (a real bug during bring-up: the top-level gate used to require the base flag unconditionally,
  which silently dropped async-clear's entire graph whenever `--no-native-clock-enable` was used).
  When async_clear is the only family active, the wire->CtrlMUX00 feeder half is additionally
  restricted to `async_feeder_wl.csv` (see above).
- Bitgen (`control_encode.py` family `"async_clear"`, rows shared with `sync`, columns private via
  `FAMILY_SOURCE_COLUMNS`): resolves the routed `CtrlMUX->TileAsyncMUX01` edge to the one claimed bit;
  no per-slice bit is emitted (the default already selects the right line, per the evidence above).
- Validation (`shared_control.py`): `ASYNC_CLEAR_POS_ZERO`'s packed-slice shape check now mirrors
  `CLOCK_ENABLE_POS`'s lifted-attribute model instead of the old (never physically real) "routed ARST
  port" placeholder; `.active` is conditional on `AGRV2K_SHARED_CONTROL_ASYNC_CLEAR`, so bitgen refuses
  a still-unsupported async-clear control on its own, independent of nextpnr's ingress gate.

## Board results

See `AG32-Docs/tools/vendor_parity/ASYNC_RESET_OPEN_20260925.md` for the open-flow board verdicts
(`clk_rst_high.v`, `clk_rst_low.v`, and the multi-tile corpus design
`examples/async-clear-reset/clk_rst_multi_tile.v`, which forces the >16-slice chunk split across two
physical LogicTiles).

Status as of 2026-09-25 19:00: **not yet passing, after six board rounds and two corrected
diagnoses**. Round 1 (`CtrlMUX00` with an unrestricted, clock-enable-witnessed feeder, `RMUX94`)
glitched during the held-reset window (`CONTROL_FAIL`, `controls_static=False`). Round 2 (`CtrlMUX03`,
since found to be the wrong instance -- see above) held cleanly but never resumed (`RATE_FAIL`,
`controls_static=True`). Rounds 3-6, after both corrections (instance back to `CtrlMUX00`, feeder
admission restricted to the whitelist above): four different builds --
`RMUX40@(16,11)`, vendor's own exact wire `RMUX10` at a *different* tile `(17,11)`, and the
`clk_rst_multi_tile` two-tile composition -- **all four show the identical `RATE_FAIL`,
`controls_static=True`, 0 edges signature**, including well after the harness releases reset.
Every single pip in each of these routes, hop by hop (checked directly against the pipwit ledger, not
assumed), is independently silicon-witnessed -- including the multi-hop general-routing legs between
the pad and the CtrlMUX feeder, not just the final `wire->CtrlMUX00` hop. Per-pip witnessing has
therefore been exhausted as an explanation for this specific, reproducible failure signature: the
remaining gap is not "which pip is unproven" but something this restriction cannot see -- most likely
whether this exact *chain* of individually-witnessed pips conducts *simultaneously* as used here (the
aggregate-congestion frontier this codebase's conduction-reframe model already flags as open), or a
still-unidentified mechanism difference between this lifted/attribute-only packing and what vendor's
own bitstream does. The destination bit, instance, and per-pip route are no longer the open question;
what silicon actually does with this whole composition at once is. See `ASYNC_RESET_OPEN_20260925.md`
for the full field diff and next steps.
