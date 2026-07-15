# AGaMEMnon — AGRV2K bitstream format

This is the bit-level reference for the AG32 / AGRV2K fabric bitstream. It describes what a `.bin` contains, how it decompresses to the whole-fabric config image, how a config bit maps to a physical tile feature, how routing is encoded, and how the image reaches the chip. Codec, physical-map, CRC, and named-ASCII behavior are covered by checked-in regressions; configuration acceptance and the supported functional subsets are validated on silicon.

## 1. The `.bin` container

A fabric `.bin` is an 8-byte header followed by an LZW codestream:

```
offset 0   u32  DEVICE_ID   = 0x40200001   (stored 40 20 00 01)
offset 4   u32  max_index   = 0x0000ffff   (stored 00 00 ff ff)
offset 8   ...  variable-width LZW codestream
```

There is **no outer container CRC** on the `.bin` file itself. Integrity is checked on the *decompressed* image (§3). Compressed `.bin`s in the wild are a few KB; the file is what lives in flash and what `agamemnon pack` emits (a `.comp` alongside the uncompressed image).

## 2. LZW codec

The codestream is a variable-width LZW, textbook GIF/TIFF-style, with these exact parameters (validated: `decode`→`encode` reproduces every test `.bin` byte-for-byte):

- `dw = 8` — literals `0..255` occupy codes `0..255`.
- `CLEAR = 256`; first dictionary code = `258`; **no EOI** is used (the last code is emitted and the final byte is zero-padded).
- **Initial code width = 9 bits.** The width bumps as the dictionary grows.
- **Dictionary reset at `next_code == 1024`** — a CLEAR is emitted and width returns to 9, so codes never exceed 10 bits.
- Codes are packed **MSB-first**.

Decoding the payload always yields a fixed **99,936-byte** raw image (the whole-fabric configuration). Implementation: `agamemnon/engine/lzw_codec.py` (`decode` / `encode`).

## 3. The raw image and its config CRC

The 99,936-byte raw image is the actual fabric configuration memory. Its layout:

- bytes `[0:164]` — a **preamble** of leading config-chain records (device/global setup). This is generic — no device-specific or unsafe bytes — and is generatable from scratch.
- bytes `[164:99932]` — the per-tile configuration proper (§4).
- bytes `[99932:99936]` — the **config CRC**: `CRC-32/BZIP2` (poly `0x04C11DB7`, init/xorout `0xFFFFFFFF`, no input/output reflection) computed over `header(8) + raw[:99932]`, stored **big-endian**.

The fabric-config engine (FCB) checks this CRC at configure time: feeding an image with a wrong value returns `FCB->STAT` bit `ERR_CRC` (`0x40`); a correct image returns `STAT = 0x000f0002` (ACTIVE, zero errors). This was recovered on silicon and is distinct from any file-level container CRC. `agamemnon/engine/bitgen_seq.py` computes and writes it.

## 4. Physical map — a config bit is a tile feature

`af.exe` exposes, for any config bit, its `tile (X,Y) + CFG feature + word-line/bit-line`. Enumerated exhaustively this is the complete physical map: **554,800 config bits across 213 tiles**, in the usual families — `CFG_LUT`/`INIT_VAL` (LUT truth tables and BRAM init), `CFG_RMUX0..15` and `CFG_IMUX*` (routing muxes), `CFG_SEAMMUX` (inter-tile seam), `CFG_IOMUX`, clock/control. The map is shipped as `agamemnon/chipdb/pips_full.csv` (one-hot pips with raw `(byte, mask)`) and the wire/node set as `agamemnon/chipdb/wires.csv` (50,046 nodes).

### Pos↔raw transform

The vendor coordinates `(top_wl, top_bl)` map into the raw byte array by a **rank model**: the raw image is word-line-major, and within a word-line only the *used* bit-lines pack sequentially (reserved gaps removed), 8 per byte, MSB-first, after the 164-byte preamble.

```
rank = index of top_bl among the word-line's sorted USED bit-lines   (chip-DB lookup)
byte = 116 * top_wl + rank // 8 + 164
bit  = 7 - (rank % 8)
```

The essential subtlety is the **rank** among *used* bit-lines — a naive `top_bl // 8` ignores the reserved gaps and misses about a third of the bits. LUT-init reduces to a closed-form over `(x,y,z)` with an **inverted polarity** (the SRAM stores the LUT truth table complemented), validated bit-exact on real designs. Implementation: `agamemnon/engine/physmap.py`.

## 5. Routing sel encoding

A routed connection (a used edge in the routing graph) is realized by setting a **2-hot sel pair** in the destination mux's config group. An RMUX group contains six independent 10-bit destination-node blocks; an IMUX group contains four independent 12-bit blocks. The pair is a function of the source node, destination node, and tile offset. The release encoder resolves it in these regimes:

- **Conflict-free physical observations** — `chipdb/sel_edge_pairs.pkl` contains 659,643 physical edges whose destination-local pair never conflicts in the streamed route corpus or a dedicated vendor oracle.
- **Unanimous tile-relative replication** — 62,003 `(family,index,source,delta)` keys are admitted only when every physical observation agrees; any conflicting relative key is excluded.
- **MCU-edge (`BBMUXS`) exit** — a per-source, instance-independent 2-hot pair table; the MCU→fabric entry pair is region-dependent (GPIO region vs AHB region) and harvested per edge.

Release builds enable `AGAMEMNON_CLEAN_SEL_GATE=1`: nextpnr never sees general-routing edges outside those
clean tables, and bitgen fails if a routed data PIP would require a legacy or predicted selector. The
placement-diverse SERV qualification images use roughly 3.4k data PIPs each with zero predicted and zero
unmapped selectors. Data: `sel_edge_pairs.pkl`, `sel_map.json`, `pips_full.csv`, `rrg_edges_full.csv`,
`rrg_omux_imux_full.csv`, and `pips_mcuedge_routing.csv`.

## 6. Baseline canvas

bitgen does not synthesize every one of the 99,936 bytes from nothing; it overlays the design onto a **fabric-default baseline** that supplies the invariant background (IO defaults, clock spine, saturated/structural muxes, the preamble). AGaMEMnon ships this as `agamemnon/chipdb/fabric_default.bin` — a *derived*, design-neutral image produced by taking a fabric config and clearing its data-routing bits (exactly the clear bitgen performs at runtime), so no vendor *design* is shipped. bitgen clears the design region (non-saturated `CFG_RMUX`/`CFG_IMUX` bits and the placed slices' LUT/OMUX), ORs the new design's features on top, emits the open clock source for clocked designs, and finally writes the CRC.

## 7. `.agasc` — named, lossless per-tile ASCII

`.agasc` is the editable text form of the complete raw image. It assigns each
physical bit covered by the shipped feature tables one canonical name under a
tile block, while preserving asserted bits outside those tables in sparse
`.raw` records:

```text
.agasc 1
.device 0x40200001
.max_index 0x0000ffff
.raw_length 99936
.crc auto
.tile 10 4
+CFG_LUT[0]
+CFG_OMUX0[2]
.end
.raw 000080 ff00
```

Only asserted named features are written. Removing a `+FEATURE` line clears
that cell and adding a valid feature sets it. `.raw` records are restricted to
unmapped bits, so the parser rejects contradictory raw/semantic encodings,
unknown features, duplicate features, and overlapping raw ranges. With
`.crc auto`, the final four raw bytes are derived rather than serialized and
CRC-32/BZIP2 is regenerated after edits. `.crc preserve` is available for
forensics on intentionally invalid images.

The canonical map is the union of `slice_cfg.csv`, `bram_cell.csv`,
`pips_io.csv`, `pips_mcuedge.csv`, and `pips_full.csv`. Undecoded global or
reserved bits remain lossless `.raw` data; the format does not pretend those
bits have known semantics. The real `blinky.bin` regression expands to 1,530
named asserted features across 30 tiles and converts back to the original
compressed file byte-for-byte.

```bash
agamemnon to-agasc fabric.bin -o fabric.agasc
agamemnon from-agasc fabric.agasc -o rebuilt.bin
agamemnon from-agasc fabric.agasc --uncompressed -o rebuilt-raw.bin
```

Implementation: `agamemnon/engine/agasc.py`.

## 8. Flash layout and boot

The MCU and fabric share a 256 KB SPI flash:

```
0x80000000   MCU code (reset vector / firmware)
<option>     fabric config (.bin), LZW-compressed        (factory: 0x80008100)
<option>     decompression-algorithm blob (for compressed configs)
0x81000000   option bytes (config address + compress/encrypt flags)
```

At reset the boot ROM reads the option bytes to find the fabric config address, runs the decompression routine for a compressed config, and streams the resulting image into the FCB (`CTRL = 0x40` AUTO at `0x40010000`, data at `0x4001000c`, status at `0x40010010`). It then branches per the BOOT0 strap. Fabric flash configuration occurs at power-on; a warm debugger reset does not replay the complete boot path. The silicon-qualified persistent path replaces the compressed image at the existing factory pointer and preserves its decompressor. See `PROGRAMMING.md` and `flashboot/FLASH_LAYOUT.md`.

## 9. Producing and reading a bitstream

```
agamemnon pack routed.json out.bin     # routed nextpnr JSON -> out.bin (uncompressed) + out.bin.comp
agamemnon unpack out.bin -o raw.img    # .bin (either form) -> 99936-byte raw image
agamemnon to-agasc out.bin -o out.agasc # .bin -> named, lossless per-tile ASCII
agamemnon from-agasc out.agasc -o out.bin # edited ASCII -> CRC-correct compressed .bin
agamemnon edit-lut in.bin --le x,y,z --init 0x96e9 -o out.bin   # rewrite one LUT truth table, byte-exact
```

The `pack` output is byte-exact against the vendor `af.exe` for the same routed design (the shipped `pytest` regression pins three reference designs by SHA-256). `unpack`/`decode` auto-detect the uncompressed image vs a compressed `.bin`.
