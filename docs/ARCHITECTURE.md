# AGaMEMnon — Architecture

AGaMEMnon is an open bitstream and place-and-route toolchain for the AGM **AG32 / AGRV2K** (an RV32IMAFC MCU welded to a small eFPGA). The vendor flow is a Windows-only, Quartus-derived back end called `af.exe`.

The structural advantage over IceStorm-for-Lattice: **the architecture knowledge already lives inside `af.exe`.** Rather than inferring the bitstream format by statistical diffing (a person-years effort), AGaMEMnon *transcribes* the vendor's embedded data into open formats and validates every layer byte-for-byte against `af.exe` — and, where it touches hardware, against real AG32 silicon.

This document describes the recovered stack from the bottom up, then the engine that sits on it. Each layer states what it is, how it was validated, and the file that implements it.

Conventions:
- `agamemnon/engine/<file>` — a runtime module in the self-contained package (the single source of truth).
- `agamemnon/chipdb/<file>` — a shipped device-database file; large derived artifacts are tracked with Git LFS.
- `tools/<file>` and `tools/agamemnon/<file>` — scripts in the sibling AG32-Docs source tree (the RE workbench; not shipped at runtime).

---

## Device facts (validated)

- **AGRV2K** = RV32IMAFC MCU + eFPGA. `DEVICE_ID = 0x40200001` (read from `0x03000100`), `misa = 0x40801125`.
- Fabric resources: 2112 LUT4, 2112 flip-flops, 4 block RAMs, 1 PLL, global clocks, up to 128 IO, on a tile grid (132 LogicTiles plus IO/BRAM/clock/MCU-edge tiles).
- **Packages / device model.** One AGRV2K die is offered in **4 QFN packages — L100 / L64 / L48 / Q32** — with the same core fabric and different bonded perimeter pins. AGaMEMnon ships the per-package legal-pin sets and rejects a declared `PIN_n` that the selected package does not bond. The default is **AGRV2KL48**; select another with `AGAMEMNON_DEVICE`. User-IO counts are L100=79, L64=49, L48=34, and Q32=26. A physical `PIN_n → IOTILE` bond map is shipped only for L48, so physical-PCF builds for L100/L64/Q32 fail closed rather than borrowing L48 coordinates.
- A fabric `.bin` is an **8-byte header** `[DEVICE_ID 0x40200001 | max_index 0x0000ffff]` followed by a variable-width LZW codestream; it always decompresses to a fixed **99,936-byte** whole-fabric raw config image.
- The MCU and fabric share a 256 KB SPI flash: MCU code at `0x80000000`, the fabric config at an option-byte-specified address (factory `0x80008100`, LZW-compressed). At power-on the boot ROM reads the config from flash, runs a decompression routine, and streams it into the fabric-config engine (FCB) — this is the flash-boot path AGaMEMnon now drives with its own bitstream. See `BITSTREAM_FORMAT.md`.

---

## Layer 1 — The arch-DB codec (the master key)

`af.exe`'s architecture database (`etc/arch/.../*_cfg.csv`) and its `.tx` place/route intermediates are obfuscated with a custom *reversible* ASCII codec — not encryption. It is a keyed polyalphabetic substitution: a 96-char alphabet, 100 substitution tables, the trigger set `"ezEZ\n"`, and a deterministic table-switch counter (the newline trigger is why the encoding is line-structured), recovered from the decompiled constructor and per-byte transform. All 100/100 vendor `*_cfg.csv` files round-trip byte-exact, and the same codec decodes the routing/placement `.tx` intermediates — the single most reused result in the project. **Files:** `agamemnon/engine/codec_validate.py`, `agamemnon/engine/tx_decode.py`.

> Caveat: the vendor `alta::decode_file` Tcl command is *destructive* (it re-opens the input path for write-truncate — a vendor copy-paste bug). The open codec is the safe replacement; never run `decode_file` on real package files.

## Layer 2 — The semantic feature database

Decoded, each arch-DB file is a readable `(block × word-line × bit-line) → CFG feature` matrix — what every config cell *means*. Flattened this is **110,188 mapped config cells, 14,463 distinct features, 28 blocks**, in the families a normal FPGA has: `CFG_LUT` / `INIT_VAL` (LUT truth tables / BRAM init), `CFG_RMUX0..15` (routing muxes per tile), `CFG_SEAMMUX` (inter-tile seam routing), `CFG_IMUX*`, `CFG_IOMUX`. The families match Layer 4's independently enumerated physical map exactly (mutual cross-validation). This is the semantic half of the bit map IceStorm spent person-years inferring — here sourced from the vendor.

## Layer 3 — The `.bin` LZW codec

The fabric `.bin` payload is a variable-width LZW, transcribed from the decompile and pinned against the `blinky.bin` oracle: 8-byte header, then the codestream; `dw = 8` (literals 0–255), CLEAR = 256, first dict code = 258, no EOI; initial code width 9 bits; dictionary reset at `next_code = 1024` (codes never exceed 10 bits); codes packed MSB-first, final byte zero-padded. `decode`→`encode` reproduces all test `.bin`s byte-for-byte; every `.bin` decodes to a fixed 99,936-byte raw image. The `.bin` *file* has no outer container CRC — but the *decompressed* raw image carries a config-protocol CRC that the fabric-config engine checks (Layer 4 / `BITSTREAM_FORMAT.md`). **Files:** `agamemnon/engine/lzw_codec.py`.

## Layer 4 — The complete physical map (routing included)

`af.exe`'s Tcl command `alta::find_config_by_bit <bit>` prints, for any config bit, its `tile (X,Y) + CFG feature + word-line/bit-line`. Enumerating all bits yields the entire physical map: **554,800 mapped config bits across 213 tiles**, every routing mux (`CFG_RMUX0..15`, `CFG_SEAMMUX`, `CFG_IMUX*`) included alongside logic/IO/clock. This collapsed the routing "mountain" into an enumeration; family counts and names match the Layer-2 arch DB exactly. The fabric-config engine additionally checks a **CRC-32/BZIP2 over `header(8) + raw[:99932]`, big-endian**, stored in the last raw word — recovered on silicon (a wrong value returns `FCB STAT` `ERR_CRC`) and baked into bitgen.

> Scope note: "complete/entire physical map" here means the **config-bit map is complete** (every config cell's meaning + placement, from the vendor's own enumeration). The **routing *adjacency* graph** (which mux input drives which, i.e. the pip mesh the router actually walks) is a separate artifact harvested from the vendor router's routed designs; it is **corpus-covered ~99%** of the mesh the vendor exercises, with the far-link / MCU-edge exit-feeder tail **closed on real silicon** rather than from any vendor file (see Layer 6 / `HARDWARE_VALIDATION.md`).

## Layer 5 — The Pos↔raw transform (rank model)

Layer 4's coordinates are `af.exe`'s `(top_wl, top_bl)`; the programmable image is the LZW-decompressed raw bytes. The raw image is word-line-major, and within a word-line the *used* bit-lines pack sequentially (reserved gaps removed), 8 per byte, MSB-first, after a 164-byte preamble:

```
rank = index of top_bl among the word-line's sorted USED bit-lines   (chip-DB lookup)
byte = 116 * top_wl + rank // 8 + 164
bit  = 7 - (rank % 8)
```

The key insight is the **rank** among used bit-lines (a naive `top_bl // 8` ignores the reserved gaps). For LUT-init this reduces to a closed-form formula over `(x,y,z)` with an inverted polarity (SRAM stores the LUT init complemented), validated bit-exact on real designs. **Files:** `agamemnon/engine/physmap.py` (and the rank model it embeds).

## Layer 6 — Open bitstream generation

Given a placed+routed design, write every per-tile feature value into the raw image (via Layer 5) over a baseline canvas, add the config CRC (Layer 4), then LZW-encode (Layer 3) to a `.bin`. No vendor binary anywhere in the path. All per-tile feature bits reconstruct with zero errors; the emitted `.bin` is FCB-accepted on silicon. The baseline canvas is `agamemnon/chipdb/fabric_default.bin` — a *derived*, design-neutral fabric-default image (the vendor bitstream it was distilled from has had its routing stripped; no vendor design ships). **Files:** `agamemnon/engine/bitgen_seq.py` (routed JSON → `.bin`), `agamemnon/engine/to_bin.py` (adds the uncompressed image for SRAM inject), `agamemnon/cli.py` `pack`/`edit-lut`, `agamemnon/program.py` (OpenOCD program/verify/restore).

## Layer 7 — The chip database and routing/sel encoding

The data a router needs — bels, wires, pips, and the config bits that select each:

- **Wires / nodes** — the decoded `route.tx` global node section (node identity via `agamemnon/engine/coord2named.py`) → the complete node set (`chipdb/wires.csv`, **50,046 nodes**).
- **Pips (config side)** — the arch DB + physical map → the complete one-hot config-pip set with raw `(byte, mask)` (`chipdb/pips_full.csv`, **276,834 pips**), including every routing-mux selection.
- **Routing graph** — the enumerated/observed edge set (`chipdb/rrg_edges_full.csv` + the intra-tile crossbar `chipdb/rrg_omux_imux_full.csv`) plus the MCU-edge crossings (`chipdb/pips_mcuedge_routing.csv`).
- **Sel/edge encoding** — a used edge lights a 2-hot pair in its destination node's independent block (six 10-bit RMUX blocks or four 12-bit IMUX blocks per CFG group). `chipdb/sel_edge_pairs.pkl` ships 659,759 conflict-free physical edge pairs recovered from the route corpus and dedicated vendor oracles; 62,044 tile-relative keys are replicated only where every physical observation agrees. The release graph and bitgen both enable the clean-selector gate, so an edge needing a legacy formula, majority choice, or prediction fails closed. MCU-edge BBMUXS/entry paths use their separately qualified pair tables.

## The engine on top — nextpnr + the `agrv2k` uarch, MCU edge, flash-boot

The place-and-route engine is nextpnr driven by the **`agrv2k`** Viaduct uarch in `agamemnon/engine/uarch/agrv2k/`. The recovered AGRV2K graph is emitted to flat CSV and replayed into nextpnr with selector/conduction gating and placement legality. `agamemnon build --uarch` selects this release backend. Regional placement, fanout splitting, BRAM packing, qualified input synchronization, constructive carry placement, and router2 route the shipped SERV and serial demos without a checkpoint. Sequential logic, global clocks, the characterized L48 IO subset, selected BRAM A/B corridors, the supported PLL ratios, and the documented MCU-bridge modes are silicon-proven within the boundary in `STATUS.md`. Synthesis uses Yosys with the mappings in `agamemnon/synth/`.
