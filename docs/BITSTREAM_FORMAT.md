# AGaMEMnon — AGRV2K bitstream format

This is the bit-level reference for the AG32 / AGRV2K fabric bitstream — the AGaMEMnon analogue of Project IceStorm's format documentation. It describes what a `.bin` contains, how it decompresses to the whole-fabric config image, how a config bit maps to a physical tile feature, how routing is encoded, and how the image reaches and boots the chip. It is a summary; the exhaustive reverse-engineering narrative (decompiled functions, every byte-exact validation) lives in `../AG32-Docs/AG32_Bitstream_RE.md`.

Every claim here is validated byte-for-byte against `af.exe` and, where noted, on real silicon.

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

A routed connection (a used edge in the routing graph) is realized by setting a **2-hot sel pair** in the destination mux's config group. The destination CFG group is `dst_node_idx // {RMUX: 6, IMUX: 4, OMUX: 3}`, and the pair is a function of the source node, destination node, and tile offset. The encoding is solved in three regimes:

- **Inter-tile RMUX mesh** — closed-form (a direction-bank table keyed on the tile delta plus a source-geometry term). This is what the router leans on for long routes.
- **Intra-tile OMUX→IMUX crossbar** — observed per-instance, then completed by validated cross-tile replication (the crossbar is a fixed structure repeated per tile).
- **MCU-edge (`BBMUXS`) exit** — a per-source, instance-independent 2-hot pair table; the MCU→fabric entry pair is region-dependent (GPIO region vs AHB region) and harvested per edge.

Byte-validated against `af.exe` at **~99% with a false-positive rate of zero**: the encoder emits a sel only where it can prove the mapping, so the residual ~1% is a *dropped or approximated* pip (dense crossbar corners, some far routes), never a *wrong* one. Data: `agamemnon/chipdb/sel_map.json`, `pips_full.csv`, `rrg_edges_full.csv`, `rrg_omux_imux_full.csv`, `pips_mcuedge_routing.csv`.

## 6. Baseline canvas

bitgen does not synthesize every one of the 99,936 bytes from nothing; it overlays the design onto a **fabric-default baseline** that supplies the invariant background (IO defaults, clock spine, saturated/structural muxes, the preamble). AGaMEMnon ships this as `agamemnon/chipdb/fabric_default.bin` — a *derived*, design-neutral image produced by taking a fabric config and clearing its data-routing bits (exactly the clear bitgen performs at runtime), so no vendor *design* is shipped. bitgen clears the design region (non-saturated `CFG_RMUX`/`CFG_IMUX` bits and the placed slices' LUT/OMUX), ORs the new design's features on top, emits the open clock source for clocked designs, and finally writes the CRC.

## 7. Flash layout and boot

The MCU and fabric share a 256 KB SPI flash:

```
0x80000000   MCU code (reset vector / firmware)
<option>     fabric config (.bin), LZW-compressed        (factory: 0x80008100)
<option>     decompression-algorithm blob (for compressed configs)
0x81000000   option bytes (config address + compress/encrypt flags)
```

At reset the boot ROM reads the option bytes to find the fabric config address, runs the decompression routine (for a compressed config) to reconstruct the 99,936-byte raw image, and streams it word-by-word into the FCB (`CTRL = 0x40` AUTO at `0x40010000`, data at `0x4001000c`, status at `0x40010010`) — the same FCB sequence AGaMEMnon uses for SRAM-injected configuration, just sourced from flash. It then branches per the BOOT0 strap (run the flash MCU app, or enter the UART serial bootloader). Because the config runs at power-on, flashing a new fabric image requires a physical power-cycle to take effect. AGaMEMnon has driven this end-to-end with its own bitstream (an open compressed config flashed to the config region → power-cycle → fabric configured and computing, no debugger in the loop). Full detail: `../AG32-Docs/tools/flashboot/FLASHBOOT_FINDINGS.md`.

## 8. Producing and reading a bitstream

```
agamemnon pack routed.json out.bin     # routed nextpnr JSON -> out.bin (uncompressed) + out.bin.comp
agamemnon unpack out.bin -o raw.img    # .bin (either form) -> 99936-byte raw image
agamemnon edit-lut in.bin --le x,y,z --init 0x96e9 -o out.bin   # rewrite one LUT truth table, byte-exact
```

The `pack` output is byte-exact against the vendor `af.exe` for the same routed design (the shipped `pytest` regression pins three reference designs by SHA-256). `unpack`/`decode` auto-detect the uncompressed image vs a compressed `.bin`.
