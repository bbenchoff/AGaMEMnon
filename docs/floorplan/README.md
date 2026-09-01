# Device floorplan

A small visualizer that draws the AGRV2K die from the project's own recovered
device model, plus a per-design placement view. Everything here is generated from
tables already shipped in the repo — no external dependencies, no vendor data.

## What it shows

`render_die.py` reads the two gzipped device tables in `agamemnon/engine/`:

- `status_overlay_dev_belpins.csv.gz` — every placeable bel (SLICE / BRAM / MCU /
  IO / OPAD / ADC) and its tile coordinate;
- `status_overlay_dev_pips.csv.gz` — the routing graph, which gives the full tile set.

and writes `agrv2k_die.html`, a self-contained floorplan. Open it in a browser.

## What the picture tells you about the part

- **The logic is exactly 132 tiles × 16 slices = 2,112 LUT4** — the fabric's entire
  slice budget. There is no hidden logic; if a "missing" region looks empty, it is
  empty *by design*, not un-recovered.
- **The logic array is L-shaped, not a rectangle:** a full-width band along the
  bottom plus a tall right-hand column. The BRAM tiles form a column; a bidirectional
  IO ring and single-ended output pads wrap the edges; one ADC0 boundary sits off the
  east edge.
- **The full routing grid is ~190 tiles.** The ~31 beyond the placeable set are
  routing-only switch tiles — chiefly the **Y5 MCU boundary spine** and the **X21
  spacer column** (routing, no ordinary slices).
- **The large blank top-left is the hard MCU / SoC**, not a data gap. The AG32 is an
  MCU *and* an FPGA on one die: the RISC-V core, 256 KB flash, 128 KB SRAM, and hard
  peripherals occupy real silicon but are not FPGA fabric, so they hold no fabric
  tiles. The MCU meets the fabric only along the Y5 spine, where the AHB boundary port
  (the `M` tile at X10Y5) hands signals across.

These facts are cross-checked against the AGRV2K datasheet (16 slices per logic block;
up to 2K slices; embedded flash CFM; one PLL; bidirectional IOEs on the periphery).

## Regenerate

```sh
python3 docs/floorplan/render_die.py                 # -> docs/floorplan/agrv2k_die.html
python3 docs/floorplan/render_die.py <engine_dir> <out.html>
```

The die view is design-independent. A per-design placement view (where one routed
design's cells and nets land on this fabric) can be built the same way from any
`*_routed.json` the flow produces — see `render_die.py`'s `kind()` / coordinate
parsing for the `NEXTPNR_BEL` and `ROUTING` attribute formats.
