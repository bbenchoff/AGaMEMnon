# The Vendor Canvas — `fabric_default.bin`

> **The one byte-blob AGaMEMnon does not yet generate from scratch.**
> Every bitstream the open flow emits is painted *on top of* this 2.8 KB file.
> This page is the honest, byte-exact account of what it is, what its bits do,
> and why it is the single biggest "not *completely* open" caveat in the project.
> All figures here were produced with the engine's own tooling (`lzw_codec`,
> `bitstream_inspect`, `bit_ownership`) against the real file — nothing is invented,
> and everything not decoded is marked **UNKNOWN**.

See also: [BITSTREAM_FORMAT.md](BITSTREAM_FORMAT.md) · [ARCHITECTURE.md](ARCHITECTURE.md) ·
[STATUS.md](STATUS.md) · [VENDOR_PARITY.md](VENDOR_PARITY.md) · [the provenance notice](../NOTICE.md).

---

## TL;DR

The open flow (Verilog → yosys → nextpnr → bitgen) does **not** synthesize a blank,
design-neutral fabric image from first principles. Instead it loads a **vendor-tool-derived
baseline** — `fabric_default.bin` — decompresses it to a full 99,936-byte configuration
image, **clears** the design-dependent slice/routing surface, and **overlays** the bits it
actually generated (LUTs, routing, clocks, IO, BRAM, carry, CRC). Everything it does *not*
touch is inherited **verbatim**.

- The **preamble** (164 B) and the **CRC** (4 B) are fully **decoded and regenerated** every
  build — those bytes are ours.
- The **99,768-byte body** in between is **mostly inherited**. ~230 thousand asserted bits
  (~28.7 KB) are vendor default/reset tile-grid state whose *exact per-bit meaning we have
  not decoded*.

So the accurate headline is: **"no vendor executable at runtime" is true; "fully
vendor-free, from-scratch image" is not.** Removing this canvas is tracked, open work.

---

## 1. Anatomy of the file

```
agamemnon/chipdb/fabric_default.bin        2,839 bytes on disk   (0xB17)
sha256 6093e876041bab9f8d1f6058235713a6b8ced1024455070fe2b358e87915a041   (pinned: NOTICE.md)

┌ header [0x00:0x08] ── 8 B ───────────────────────────────────────────────┐
│  40 20 00 01   DEVICE_ID = 0x40200001  (the AGRV2K family id)             │
│  00 00 FF FF   max dictionary index = 0xFFFF                             │
└───────────────────────────────────────────────────────────────────────────┘
┌ payload [0x08:] ── 2,831 B ──────────────────────────────────────────────┐
│  variable-width LZW codestream (the engine's OWN codec, lzw_codec.py):    │
│    8-bit literals · CLEAR=256 · first code 258 · NO end-of-info           │
│    width 9→ bits, grows by 1, dictionary reset at code 1024               │
│    MSB-first packing, final byte zero-padded                              │
└───────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │  L.decode(payload)
                                   ▼
              99,936-byte RAW CONFIGURATION IMAGE  (a complete, design-neutral canvas)
              sha256 717d6c672b215676ae74279d47835eaab7367e8d05b6cb0d7585727ba581c18f
              (header + raw = 99,944 B)
```

This is **not** standard/`zlib` LZW — it is the same reversible codec that round-trips vendor
`.bin`s byte-exact (see [BITSTREAM_FORMAT.md](BITSTREAM_FORMAT.md)). The decompressed image is
the **full** raw configuration, not a partial fragment.

---

## 2. Memory map of the decompressed image

```
 offset (hex)     99,936 bytes  ×  8  =  799,488 configuration bits
 0x00000  ┌────────────────────────────────────────────────────────────┐
          │  PREAMBLE                              164 B                 │  ◀ DECODED
          │  global / configuration-chain records                       │    regenerated
 0x000A4  ├────────────────────────────────────────────────────────────┤    every build
          │                                                              │
          │  CONFIG-CHAIN BODY                     99,768 B              │
          │  116-byte word-lines  (861 lines, 612 non-zero)             │  ◀ mostly
          │  coord→offset:  byte = 116·top_wl + rank//8 + 164            │    INHERITED
          │                 bit  = 7 - (rank % 8)                        │    -OPAQUE
          │  LUT INIT stored in COMPLEMENTED polarity                    │
          │  ► ~28.6% of the body is 0xFF  (28,570 bytes)               │
          │    = unconfigured LUT SRAM at reset polarity                 │
 0x1865C  ├────────────────────────────────────────────────────────────┤
          │  CRC-32/BZIP2                          4 B                   │  ◀ DECODED
          │  poly 0x04C11DB7, init/xorout 0xFFFFFFFF, big-endian         │    regenerated
 0x18660  └────────────────────────────────────────────────────────────┘    every build
```

`164 + 99,768 + 4 = 99,936`. The CRC covers `header[0:8] + raw[0:99932]`.

> **Trivia that tells the story:** the CRC *stored inside the canvas* (`0xAD5B5DB9`) is
> **stale** — recomputing it over the canvas's own bytes yields `0x4B36B054`, so
> `bitstream_inspect` reports the shipped canvas as `crc valid: False`. This is harmless:
> bitgen always recomputes and overwrites the CRC. But it is a nice tell that the file is a
> *frozen vendor artifact* we inherit, not something we author.

### The preamble, sub-region by sub-region

The 164-byte preamble *looks* inherited but is actually **reconstructed from declarative
constants** every build — it is byte-exact equal to `preamble.IDLE_PROFILE`, and the
clock/PLL windows are swapped for one of seven pinned `(SYSCLK,HSE)` profiles.

| Offset | Bytes | Region | Source |
|--------|-------|--------|--------|
| `[0x00:0x21]` | 33 | leading descriptor + idle | reconstructed-fixed |
| `[0x21:0x40]` | 31 | global setup | reconstructed-fixed |
| `[0x40:0x71]` | 49 | clock distribution | qualified-profile |
| `[0x71:0x7C]` | 11 | PLL descriptor | reconstructed-fixed |
| `[0x7C:0x9A]` | 30 | PLL source chain | qualified-parametric |
| `[0x9A:0xA4]` | 10 | trailer | reconstructed-fixed |

These are **configuration-chain records** — not a file header and not per-die calibration.
The preamble is a *solved* problem; the body is not.

---

## 3. Who owns each bit? (measured)

Bitgen tracks provenance for **every one of the 799,488 bits** via `bit_ownership.py`
(enable it with `AGAMEMNON_OWNERSHIP_TRACE=<path>`). A feature may only write within its
declared masks or it raises `BitOwnershipError`; two features can never claim the same bit;
untouched bits keep the owner `baseline`.

Real ownership trace of a placed 4-bit hard-carry counter build:

```
 baseline  inherited verbatim, never written   ████████████████████████████▏   68.08%   544,323 bits
 default   cleared to 0 in the CLEAR phase      ██████████████▏                 31.85%   254,629 bits
 owned     generated by the open flow           ▏                                0.07%       536 bits
                                                                                 ├─ clock 259  LUT 143
                                                                                 ├─ PIP 98  integrity 32
                                                                                 └─ register_mode 4
```

The `owned` slice is tiny because the design is tiny — it scales with design size. The point
is the split: **~68% of the image is passed through untouched.** Most of those bits are `0`,
but not all — and that is where the vendor content hides.

### Where the vendor bytes actually live

Of the canvas's **~231,600 asserted (`=1`) bits**:

| Class | Asserted bits | What it is | Decoded? |
|-------|--------------:|------------|----------|
| **Named** | **1,460** | routing/slice-control fields in 23 border/edge tiles that the shipped feature tables name | ✅ the same families the open flow generates |
| **Opaque residue** | **230,116** | default/reset tile-grid state across body bytes `0xA4…0x1865B` (~28.7 KB) | ❌ **not decoded per-bit** |

**99.86%** of the canvas's asserted bits sit in `baseline`-owned bytes → carried into your
bitstream verbatim. The residue is **~99% `0xFF` runs**, and only 32 distinct byte values
appear in the whole body.

---

## 4. What do the canvas bits *do*?

**Decoded regions (ours):**
- **Preamble** — configuration-chain record descriptors, the qualified clock-0 distribution
  defaults, and a disabled (all-zero) PLL source chain. Regenerated from constants + the
  selected PLL profile.
- **The 1,460 named body bits** — routing and slice-control fields in edge tiles
  (X0Y1–Y4, X22Y1/Y3/Y4, the top and bottom tile rows, X20Y11/Y12). These belong to the same
  bit families the open flow emits for real designs, so they are understood.

**The opaque residue (inherited) — corrected 2026-08-13 by direct measurement:**
> **Correction.** An earlier version of this page said the `0xFF` residue was "unconfigured
> LUT INIT (complemented all-ones)." **That was wrong.** Measured against `physmap.init_bit_pos`
> (all 132 LogicTILE × 16 × 16 = 33,792 LUT-INIT positions), the canvas holds those LUT-INIT
> bits at **`0x00`**, not `0xFF` (only 220 are set — the configured border LUTs; a placed SERV
> image sets 3,524 of the same positions). So the **unconfigured-LUT default is `0x00`, and a
> zeros base already reproduces it.** The `0xFF` residue is a *different* region.
- **KNOWN:** the `0xFF` residue is the **complemented-all-ones default of unnamed reserved
  routing/seam bit-lines** in a clean rectangle of the config body (columns 59-114, word-lines
  0-510 ≈ 7.5 tile-rows × the right-half columns): **227,652 bits**. Plus a per-word-line
  **col-58 framing nibble** (`0x0f`, 1,904 bits), the **220 border-tile LUT-INIT** bits, and
  ~340 region-edge partials. These positions sit among the CFG_RMUX/IMUX/SEAM/BBMUXS families,
  but the shipped tables name only ~26% of that region — so the asserted `0xFF` bits are
  overwhelmingly the **unnamed 74%** of those bit-lines at their reset (all-ones) polarity.
- **UNKNOWN:** the arch DB carries no per-bit-line *reset value* for the unnamed lines, so the
  open flow cannot yet emit them from scratch. This is the single biggest blocker (see below).

> This KNOWN/UNKNOWN line is the whole honesty of the page: we can say *what class of state*
> the residue is, and that clearing it naïvely breaks the image; we cannot yet write it from
> scratch.

### Decode status & regenerability (measured 2026-08-13)

How close is a *from-scratch* base image (no vendor blob) to the decoded canvas, byte-exact?

| Candidate | What it emits | Body byte-exact |
|-----------|---------------|-----------------|
| **A** | zeros + `preamble.build()` + regenerated CRC (only what the arch DB / constants give us today) | **70.33 %** (70,168 / 99,768) |
| **B** | A + the geometric `0xFF` reserved-SRAM fill | **98.97 %** (98,738 / 99,768) |

So **70.3 % of the base is regenerable today**; a single decoded rule (the reserved routing/seam
bit-line all-ones default) closes it to **~99 %**; the last ~1 % is a few small per-field decodes
(the col-58 nibble + region-edge partials). Decode status by family:

| Family | Bits | Regenerable? |
|--------|-----:|--------------|
| Preamble (164 B) | — | ✅ regenerated (164/164) |
| CRC | 32 | ✅ regenerated |
| Unconfigured LUT-INIT default (`0x00`) | — | ✅ a zeros base reproduces it |
| Reserved routing/seam SRAM all-ones default | **227,652** | ❌ needs the per-bit-line reset-polarity map (biggest blocker) |
| col-58 framing nibble | 1,904 | ❌ small decode |
| Border-tile neutral config | 1,680 | ⚠️ named/known — emittable declaratively now |
| Region-edge partials | ~340 | ❌ small decode |

The one blocker that matters is the **reserved routing/seam SRAM default (227,652 bits)**: the
open flow needs a *complete per-LogicTile bit-line → resource + reset-polarity map* so every
unnamed bit-line gets its default. That map is the decoded `alta_tile_agr_cfg`-class crossbar
table held in the **AG32-Docs workbench — not yet promoted** to this repo (a deliberate,
by-hand vendor-data promotion decision). With it, a `default_frame.py` emitter fills the reserved
region from the tile grid and the canvas can be generated, gated byte-exact, and retired.

---

## 5. How bitgen uses the canvas (the build pipeline)

`agamemnon/engine/bitgen.py` runs nine phases in order:

```
   ┌─────────────────┐
   │ assemble_canvas │  load fabric_default.bin → decode → 99,936-byte image
   └────────┬────────┘  every bit initially owned = "baseline"
            ▼
   CLEAR_BASELINE      clear non-saturated CFG_RMUX*/CFG_IMUX* selectors  (owner → "default")
            │          + non-claiming clear of each feature's owned surface
            ▼
   ROUTING → MCU_EDGES → LOGIC → CLOCKS → IO → BRAM → CARRY     overlay only OWNED bits
            ▼
   PREAMBLE            preamble.apply() REPLACES raw[0:164] from declarative profiles
            ▼          (the canvas preamble is discarded, not inherited)
   INTEGRITY           recompute CRC-32/BZIP2 over header+raw[0:99932] → store at [99932:99936]
            ▼          → LZW-encode the whole image
        output .bin
```

Key functions: `assemble_canvas` (`bitgen.py:199`), `clear_baseline_phase` (`bitgen.py:256`),
`emit_feature_phases` (`bitgen.py:295`), `emit_preamble_phase` (`bitgen.py:324`),
`emit_integrity_phase` (`bitgen.py:342`). The clear phase is exactly the "residual baseline
slice bits are cleared" step referenced in [STATUS.md](STATUS.md); everything it does not
clear and no feature overlays is the inherited residue.

---

## 6. Why it is still here — and what removing it takes

**The decode gap (quantified 2026-08-13):** a from-scratch base image is **70.3 % byte-exact
today** and reaches **~99 %** once one rule is decoded — the reserved routing/seam bit-line
all-ones default (227,652 bits, the single biggest blocker). The open flow already emits the
preamble, CRC, and the `0x00` regions correctly; it cannot yet emit the unnamed reserved
bit-lines at their reset polarity, because the arch DB carries no per-bit-line default. Clearing
the residue wholesale produces an image the fabric does not accept.

This is **tracked work**, recorded across the parity ledgers (not a stray code TODO):

- [STATUS.md](STATUS.md): *"The canvas still supplies incompletely decoded non-preamble
  defaults, so removing it entirely remains tracked work."*
- [FPGA_PARITY_LEDGER.md](FPGA_PARITY_LEDGER.md): *"Fully from-scratch configuration image —
  partial … the non-preamble canvas is still inherited."*
- [VENDOR_PARITY.md](VENDOR_PARITY.md): *"Non-preamble defaults still come from
  `fabric_default.bin`; exhaustive bit ownership and a fully from-scratch image are open."*
- [the provenance notice](../NOTICE.md): *"generated entirely without vendor-originated
  configuration bytes" is **not** accurate; removing every remaining canvas-derived byte is
  future work.*

**The path to killing the canvas** (in increasing difficulty):
1. **Decode the residue by class** — extend `bitstream_inspect`/agasc tables until the
   `unknown_set_bits` count for the canvas drops toward zero, one bit-family at a time
   (LUT INIT default, per-tile framing, SEAM/global-track, clock/PLL idle).
2. **Generate each default region** from the arch DB the way the preamble already is
   (declarative + parametric), so bitgen can synthesize the base instead of loading it.
3. **Retire the file** — swap `assemble_canvas` from "load + clear + overlay" to
   "generate + overlay," then delete `fabric_default.bin` and drop its `NOTICE.md` pin.

When the canvas's `unknown_set_bits` reach zero and a generated base image boots on silicon,
the AG32 is *completely* open — bitstream and all. Until then, this file is the last vendor
thread in the weave, and this page is here so nobody forgets it.

---

*Every hash and offset on this page is reproducible: decode `fabric_default.bin` with
`agamemnon/engine/lzw_codec.py`, inspect with `bitstream_inspect`, and trace ownership with
`AGAMEMNON_OWNERSHIP_TRACE`. If a number here ever drifts from the tool output, the tool is
right and this page is stale.*
