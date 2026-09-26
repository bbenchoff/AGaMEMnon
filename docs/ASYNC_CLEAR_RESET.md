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

**Which `CtrlMUX` instance actually reaches `TileAsyncMUX` was NOT determined from these two images**
(both are decoded at their *destination* tile only; the destination-side bit above is silent about
which of the four `CtrlMUX` instances upstream of it is live). The first open-flow board round
(2026-09-25, `clk_rst_high`/`clk_rst_low` open images) wired the reset through **`CtrlMUX00`** by
wrongly reusing clock-enable/sync's `LINE_OF_CTRL`/`SOURCE_OF_CTRL` table (even instances 0/2 drive
lines 1/0 there) — internally self-consistent, but `CtrlMUX00` never physically reaches
`TileAsyncMUX` on this silicon, so the reset never asserted (`CONTROL_FAIL`/`RATE_FAIL`, 0 edges on
all three designs). The actual instance is independently vendor-witnessed at LogicTile X14Y10 across
four seeds and two separate isolated-source builds, AG32-Docs
`docs/archive/2026-09/GPT6_ASYNC_CONTROL_ROUTE_INVENTORY_2026-09-05.md` and
`tools/vendor_parity/gpt6_async_independent_sources_20260906/RESULT.json`: **`CtrlMUX01 -> line 0`
(`TileAsyncMUX00`), `CtrlMUX03 -> line 1` (`TileAsyncMUX01`)** — the reverse pairing from clock-enable/
sync, and odd instances instead of even. `async_control_edges.csv` and
`shared_control_graph.ASYNC_LINE_OF_CTRL`/`ASYNC_SOURCE_OF_CTRL` were corrected to `CtrlMUX03` on
2026-09-25 after this diagnosis; see the board-verdicts section below for the reboard result.

## What is claimed, and what is not

`control_encode.py`'s `FAMILY_SOURCE_COLUMNS["async_clear"]` claims exactly **one** physical
composition: LogicTile line 1 (row 33), source `ctrl_a` (CtrlMUX instance 3), column 29. `ctrl_b`,
the constant tie, and line 0 (row 34, CtrlMUX instance 1) all have **no board evidence** for this
open flow specifically (line 0's CtrlMUX instance IS vendor-witnessed at X14Y10, but this codebase
has never routed a design through it) and stay refused (`ControlEncodeError`/`SharedControlEmitError`)
rather than guessed — matching this codebase's
existing fail-closed convention (see `sync`'s own per-slice line selector, marked "undetermined" for
the same reason). Concretely: `shared_control_graph.py`'s `_add_control_sinks` adds only the
`TileAsyncMUX01` sink bel (`X<x>Y<y>_ASYNCCLR1`, one per LogicTile) and `async_control_edges.csv`
carries only the `CtrlMUX03 -> TileAsyncMUX01` topology, so a design that needs `ctrl_b` or line 0 has
no route to it in the graph at all — the router cannot silently pick an unresolved composition.

`async_control_edges.csv`'s rows are honestly labelled `tier=formula`, not `tier=observed`: unlike
`tile_control_edges.csv`'s clock-enable/sync rows (harvested per tile from a large retained vendor
corpus), this table is the SAME uniform CtrlMUX0->TileAsyncMUX01 topology computed for all 132
LogicTiles from the tile-invariant formula, calibrated against the two real silicon images above (at
one tile) and cross-checked against the independent 2026-09-03 override sweep (at a different tile).
It is not a per-tile vendor observation.

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
  `CtrlMUX03->TileAsyncMUX01` pip and `ASYNCCLR1` sink bel per LogicTile, gated on
  `AGRV2K_SHARED_CONTROL_ASYNC_CLEAR` **independently** of the base `AGRV2K_SHARED_CONTROL_GRAPH`
  flag (a real bug during bring-up: the top-level gate used to require the base flag unconditionally,
  which silently dropped async-clear's entire graph whenever `--no-native-clock-enable` was used).
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

Status as of 2026-09-25 17:30: **not yet passing**. Round 1 (`CtrlMUX00`, this module's original,
wrong instance) glitched during the held-reset window (`CONTROL_FAIL`, `controls_static=False`) --
consistent with `CtrlMUX00` not reaching `TileAsyncMUX` at all on this silicon. Round 2 (`CtrlMUX03`,
corrected per the vendor evidence above) holds cleanly during the held-reset window
(`controls_static=True`, a real, vendor-evidenced improvement) but the counter never resumes after
release either (`RATE_FAIL`, 0 Hz throughout, two placements/routes tried). The corrected destination
bit and instance are structurally confirmed correct (matches vendor's own bit, matches the vendor
instance evidence, matches the offline netlist simulator's clean hold/release logic); what is NOT yet
established is whether the *specific source wire* nextpnr's router picks to feed `CtrlMUX03` at an
arbitrary LogicTile actually carries the live reset signal on silicon, as opposed to a wire that is
admitted in the graph but unwitnessed for this exact composition. See `ASYNC_RESET_OPEN_20260925.md`
for the full field diff and next steps.
