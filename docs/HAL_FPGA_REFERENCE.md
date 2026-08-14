# AG32 eFPGA reference — the AGRV2K fabric half

Reference for the **AGRV2K** embedded FPGA inside the **AG32VF303CCT6**
(package **AGRV2KL48**, LQFP-48), treated as a programmable resource you can
target without vendor tools. Its companion is
[HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md), which covers the hard RISC-V MCU.
The two meet at the External-AHB window, the MCU-GPIO bridge, the fabric local
interrupts, and the DMA sidebands.

---

## How to read this document — the provenance tiers

Same three tiers as the MCU reference. The fabric half has *more* decoded
structure and *less* silicon coverage than the MCU half, so the distinction
matters even more here: a byte-exact encoding is not a behavioural proof.

| Tag | Tier | Meaning |
|---|---|---|
| **[S]** | **SILICON-QUALIFIED** | Exercised on the actual L48 board by an electrically observable oracle. |
| **[R]** | **REGISTER-MAP / ENCODING DERIVED** | Decoded from the architecture database or vendor artifacts, often byte-exact or differentially validated against the vendor back-end, but **never proven on silicon**. |
| **[U]** | **RE-INFERRED / UNPROVEN** | Recovered by inference; unconfirmed. Includes stated negatives. |

Three project rules that govern everything below:

> **"Build supported" means the public flow completes through strict bitgen.
> "Silicon-qualified" means the emitted image was exercised by an electrically
> observable hardware oracle. FCB configuration acceptance alone is not
> functional qualification.** — [STATUS.md](STATUS.md)

> **Qualification applies to the exact package, mode, and feature boundary
> exercised by the oracle.** — [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md)

> **Byte-exact-vs-decoded is a static result. It is not silicon proof that a
> regenerated image boots identically.** — [FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md)

[STATUS.md](STATUS.md) is authoritative on qualification. Where sources
disagree, this document records the disagreement — see
[Open questions](#open-questions-and-known-disagreements).

---

## The fabric at a glance

| Resource | Count | Tier |
|---|---|---|
| LUT4s | **2,112** | **[R]** |
| Flip-flops | **2,112** | **[R]** |
| Block RAMs | **four × 9 Kbit** | **[R]** |
| PLL | **1** | **[R]** |
| Global clocks | "global clocks" (see note) | **[U]** on the exact count |
| LogicTiles | **132** | **[R]** |
| Total grid positions | **322** | **[R]** |
| Named routing nodes | **50,046** | **[R]** |
| IO ring | programmable, ~128 IO on the die; **34 bonded on L48** | **[R]** / **[S]** for L48 |
| MCU bridge | External-AHB master/slave, GPIO, interrupts, DMA | **[S]** subset |

> **Note on global clocks.** [ARCHITECTURE.md](ARCHITECTURE.md) says only
> "global clocks" with no count. The project overview carries **5** global
> clocks. The number is not independently confirmed in the public tree, so it
> is **[U]** here. Clock *distribution* to near and far logic tiles is
> silicon-qualified for the listed PLL configurations — see
> [Clocks](#clocks-and-the-pll).

The fabric occupies the 132 logic tiles **plus** IO, BRAM, clock, and MCU-edge
tiles.

---

## Coordinate system and tile geometry

### The grid **[R]**

Tiles are addressed as `X<x>Y<y>`, with a per-tile slot index conventionally
called `z` (or *slice* inside a LogicTile, *pad index* inside an IOTile).

| Axis | Range | Notes |
|---|---|---|
| `x` | **0 … 22** | 23 columns. `x = 0` is the LEFT IO edge, `x = 22` the RIGHT edge. |
| `y` | **0 … 13** | 14 rows. `y = 0` is the BOTTOM IO edge, `y = 13` the TOP edge. |

23 × 14 = **322** positions, which matches [STATUS.md](STATUS.md)'s routing
baseline denominator ("at least one clean edge in **159 of 322 grid tiles**",
with 163 tiles uncovered — 159 + 163 = 322). **[R]**

Tile roles **[R]**:

| Role | Where |
|---|---|
| IO ring / IOTiles | the four edges: `x = 0` (LEFT), `x = 22` (RIGHT), `y = 0` (BOTTOM), `y = 13` (TOP) |
| **BRAM column** | **`x = 13`**, with the four BRAM sites at `X13Y1` … `X13Y4` |
| LogicTiles | 132 of the interior positions |
| Clock / MCU-edge tiles | the remainder |

The BRAM column is structurally special in the bitstream too: the config-body
geometry transform subtracts a **144-bit BRAM column** for every `x >= 13` (see
[Bitstream and base-image layout](#bitstream-and-base-image-layout)). That is
the cleanest independent confirmation that `x = 13` is the BRAM column.

### Where the 132 LogicTiles actually are — the footprint is **L-shaped** **[R]**

This matters for floorplanning and is easy to get wrong: the LogicTile region is
**not** a rectangle, and it does **not** fill the interior. Enumerated exactly
from the shipped `chipdb/slice_cfg.csv` (every tile that has slice
configuration), the 132 LogicTiles are:

| Columns | Rows | Tiles | Region |
|---|---|---|---|
| `x = 1 … 12` (12 columns) | `y = 1 … 4` only | **48** | a short band left of the BRAM column |
| `x = 14 … 20` (7 columns) | `y = 1 … 12` (all 12) | **84** | a tall block right of the BRAM column |
| | | **132** | |

Consequences:

- **`x = 0`, `x = 13`, `x = 21`, `x = 22`, `y = 0` and `y = 13` carry no logic
  slices.** `x = 13` is BRAM; the rest are IO/edge.
- **There are no LogicTiles at `x = 1 … 12` above `y = 4`.** The upper-left
  interior is *not* logic. A design that expects a full 20 × 12 interior array
  will not place.
- Vertically tall designs must live in the `x = 14 … 20` block; that block is
  also the one adjacent to the MCU edge, which is why nearly every qualified
  MCU-AHB site name is `X14Y*` … `X20Y*`.
- The qualified carry corridor (`X20Y11, X20Y12, X20Y10`) and the qualified
  direct-D bus-clock sites (`X14Y11 slice4…7`) both sit in the tall block, as
  does `X13Y4`'s neighbourhood.

**[R]** — this is a direct enumeration of a shipped table (132 distinct `(x, y)`
pairs, 2,112 `CFG_BYPASSEN` rows = one per slice), not an inference. It also
independently confirms the 16-slices-per-tile arithmetic in
[open question 2](#open-questions-and-known-disagreements): the same file holds
**2,112** `CFG_BYPASSEN` and **2,112** `CFG_CARRY_CRL` rows (one each per slice)
and **4,224** `CFG_LUTCMUX` rows — exactly **two `CFG_LUTCMUX` bits per slice**,
which is what the `CFG_LUTCMUX[2z + 1]` indexing in the carry encoding assumes.

### Routing-resource census **[R]**

The 50,046 named routing nodes in `chipdb/wires.csv`, grouped by resource family
(family name with its trailing index stripped):

| Family | Nodes | Family | Nodes |
|---|---|---|---|
| `RMUX` | 15,376 | `InputMUX` | 620 |
| `IMUX` | 8,704 | `TileClkMUX` | 564 |
| `OMUX` | 6,528 | `TileClkEnMUX` | 272 |
| `SinkMUXPseudo` | 4,458 | `TileAsyncMUX` | 272 |
| `ClkMUX` | 2,112 | `TileSyncMUX` | 264 |
| `AsyncMUX` | 2,112 | `alta_clkenctrl` | 264 |
| `alta_slice` | 2,112 | `alta_asyncctrl` | 264 |
| `SeamMUX` | 1,359 | `alta_syncctrl` | 264 |
| `IsoMUXPseudo` | 892 | `BBMUXW` | 159 |
| `IOMUX` | 888 | `BBMUXE` | 152 |
| `CtrlMUX` | 836 | `alta_io` | 150 |
| `BufMUX` | 706 | `alta_rio` | 150 |
| | | `alta_ioreg` | 146 |
| | | `BBMUXS` | 144 |
| | | `LoopMUX` | 112 |
| | | `TMUX` | 64 |
| | | `KMUX` | 64 |
| | | **`alta_gclkgen`** | **7** |

Three of these counts are self-checking: `ClkMUX`, `AsyncMUX` and `alta_slice`
are all **2,112** — one per slice — which agrees with the slice census above.
`BBMUXE` / `BBMUXW` / `BBMUXS` are the MCU-edge boundary muxes (East/West/South)
that every qualified `hrdata` exit and GPIO5 lane goes through.

> **On the global-clock count** ([open question 1](#open-questions-and-known-disagreements)):
> there are **7** `alta_gclkgen` nodes in the wire table. That is a count of
> *wires in one resource family*, **not** a statement that the device has 7
> global clock networks, and it does not confirm or refute the "5" figure. It is
> recorded here only as the one piece of public-tree data that bears on the
> question. **[U]**

**`x` runs right-to-left in the config body.** Bit rank — and therefore byte
column within a word-line — *decreases* as `x` increases, so tile column 22
lands nearer the start of a word-line than tile column 0. This is a frequent
source of off-by-one confusion when hand-checking bits. **[R]**

### Tile-relative vs physical addressing **[R]**

The routing tables carry two kinds of selector encoding: **conflict-free
physical** encodings (an exact `(tile, mux, terminal)` observation) and
**tile-relative** encodings that are unanimous across all physical
observations. The tile-relative scheme is what makes it possible to *predict*
encodings for the 163 uncovered tiles — but predictions are not shipped as
facts; conflicting, predicted, or unresolved selectors **fail closed**.

---

## The LogicTile and slice model

### Slice census **[R]**

2,112 LUT4s across 132 LogicTiles = **16 slices per LogicTile**, each slice
carrying **one LUT4 and one flip-flop** (2,112 FFs / 132 tiles = 16). Slice
indices observed in the qualification record run `slice0` … `slice15`,
consistent with 16. **[R]** (arithmetic on sourced totals)

Each slice's LUT has four inputs `I[3:0]`, conventionally named A, B, C, D with
`D = I[3]`. A slice's LUT INIT is 16 bits; 2,112 × 16 = **33,792** LUT-INIT bit
positions, which is exactly the size of the decoded LUT-function plane
(`physmap.init_bit_pos`, 33,792 positions, unconfigured default `0x00`). **[R]**
That arithmetic agreement is a good self-check on the census.

### The `pinC` mux — the detail that breaks naive carry and feedback models

The slice's third LUT input is not a plain input. It is selected by two
configuration muxes:

```
pinC = modeMux ? Cin : (FeedbackMux ? Qin : C)
```

- `modeMux = 1` routes the **dedicated carry-in** into `pinC`. The shipped
  micro-architecture sets it by emitting `CFG_LUTCMUX[2z + 1] = 1` for slice
  `z`. **[R]**
- `modeMux = 0`, `FeedbackMux = 1` routes the slice's own registered output
  `Qin` back in — the internal feedback path. **[U]**
- `modeMux = 0`, `FeedbackMux = 0` uses the ordinary routed input `C`. **[U]**

The three-way expression above is **RE-inferred [U]**; what the shipped
micro-architecture source directly evidences is the `modeMux = 1 → pinC = Cin`
leg and the existence of the `Qin` internal path as the alternative. A dedicated
hardware-carry cell **cannot** use the `Qin` internal path, precisely because
`modeMux` has claimed `pinC`. That single constraint is why carry packing and
register-feedback packing interact.

Getting this wrong produced a memorable bug class: a 2-bit counter that would
not count, ultimately traced to the `pinC` selection rather than to routing.

---

## Dedicated carry

### Encoding **[R]**

A ripple slice is a LUT4 configured with `INIT = 0x96E8` and `D = I[3]` tied
**high**:

| With `D = 1` | Result |
|---|---|
| LUT output | `A ^ B ^ Cin` (the sum) |
| `Cout` | `maj(A, B, Cin)` — taken from the **low mask byte** |

`I[2]` is unused because `pinC` comes from the carry hardware
(`modeMux = 1`, `CFG_LUTCMUX[2z+1] = 1`). Because `D` must be 1, the packer ties
it to a **shared VCC slice**. Related masks in the same family
(`0x69D4`, …) appear as folded/inverted variants. **[R]**

### Silicon status **[S]** — opt-in and narrow

| Qualified | Detail |
|---|---|
| Same-tile short chains | 4-stage and 8-stage chains; **two simultaneous 3-stage** chains |
| One inter-tile corridor | a **33-site** corridor containing a seed plus up to **32** arithmetic stages, in the qualified order through **X20Y11, X20Y12, X20Y10** — one 32-bit chain observed |

Placement rule enforced by the packer **[R]**:
`sum(arithmetic stages) + number of chains <= 9`.

Dedicated-carry lowering is **opt-in**, because only these specific physical
footprints are qualified. **Unqualified [U]:** arbitrary seed/spill corridors,
multi-chain placement beyond the above, and all other carry sites and modes.
A "fourth binary carry cone" is explicitly still fail-closed.

---

## BRAM

### Structure **[R]**

Four 9-Kbit blocks in the `x = 13` column at `X13Y1` … `X13Y4`. Dual-port
(Port A / Port B) with per-port width selection, optional output registers,
independent or single clock mode, and read-during-write / collision behaviour.

### Decoded mode configuration **[R]** / **[U]**

The mode/port configuration surface has been decoded to individual bit
positions for one tile. The table below is **30 bit positions across 18
configuration cells, all at `X13Y4`** — not a general per-site map.

| Cell | Width (sel range) | Meaning | Validation |
|---|---|---|---|
| `CFG_CLKMODE` | 2 (sel 0–1) | clock mode: independent vs single-clock, 2-bit binary | **byte-validated** (bitgen vs `bramp` oracle) **[R]** |
| `CFG_DWSEL_A` | 5 (sel 0–4) | Port A data width, **thermometer** coded (`x18` = `00000`, `x9` = `01000`, …) | **byte-validated** **[R]** |
| `CFG_DWSEL_B` | 5 (sel 0–4) | Port B data width, same coding | position-resolved, **not** oracle-validated (**B unexercised**) **[U]** |
| `CFG_PORTA_CLKIN_EN` / `CLKOUT_EN` | 1 each | Port A clock in/out enables | **byte-validated** **[R]** |
| `CFG_PORTA_RSTIN_EN` / `RSTOUT_EN` | 1 each | Port A reset in/out enables | **byte-validated** (`bramp` oracle) **[R]** |
| `CFG_PORTB_CLKIN_EN` / `CLKOUT_EN` / `RSTIN_EN` / `RSTOUT_EN` | 1 each | Port B equivalents | position-resolved, **not** validated **[U]** |
| `CFG_SELOUT_A` / `_B` | 1 each | **output-register select** (registered vs bypass out) | position-resolved, **not** validated **[U]** |
| `CFG_SEL_WRITHU_A` / `_B` | 1 each | **write-through / read-during-write (collision) select** | position-resolved, **not** validated **[U]** |
| `CFG_DLYTIME` | 2 (sel 0–1) | read-datapath delay time | position-resolved, **not** validated **[U]** |
| `CFG_RSEN_DLY` | 2 (sel 0–1) | read-strobe-enable delay | position-resolved, **not** validated **[U]** |
| `CFG_PACKEDMODE` | 1 | packed mode | position-resolved, **not** validated **[U]** |

**11 of the 30 rows are byte-validated; 19 are "position-resolved, not
oracle-validated."** Every Port-B cell is in the unvalidated group. Bits live at
absolute image byte offsets in the range 66,222 … 73,414 with masks only ever
`0x80`, `0x40` or `0x20` (bits 7, 6, 5) — and **bytes are shared across cells**
(byte 71,558 hosts three different bits; byte 72,718 hosts two), so never
read-modify-write a whole byte assuming it belongs to one field.

Separately, **39 configuration rows across `X13Y1` … `X13Y4`** are admitted only
under the `experimental-strict` policy. They are **config-encoding only and
establish no write, output-register, or collision behaviour**, and are **denied
under the default `release-strict` policy**. **[R]**

### Silicon status **[S]** — a bounded *read* proof at one site

| Qualified at `X13Y4` | Detail |
|---|---|
| One **x18 Port-A** path | |
| One **x2 Port-B** read/control path | |
| All nine **x9** read-only data bits | via exact per-lane projections, each **256/256** reads; bits 0–2 return word-address triplets `[2:0]`, `[5:3]`, `[8:6]`; bits 3/4/5 each match word-address bit 3; bits 6/7/8 match word-address bits 0/1/2, mapping to physical `DataOutA15`, `DataOutA16`, `DataOutA7` |
| A simultaneous strict-open x9 bundle | returns identity words 0…255 exactly once; `q8` is zero over this bounded address range and retains its independent two-state proof |
| The exact **1024-aligned-word** `HADDR[11:2]` address bundle | `HADDR11` / `AddressA12` distinguishes word addresses 0 and 512 for **64/64** alternating samples |

Named qualified corridors **[S]**:
`q5 = BufMUX13 → RMUX92 → RMUX75 → RMUX20 → BBMUXE07`;
`q4 = BufMUX12 → RMUX75` with a source-dependent `RMUX43 → BBMUXE06` selector
`{1, 6}` (the earlier source-only fallback `{0, 6}` was the defect).

Additional exactness requirements **[S]**: `X22Y4 CFG_IOMUX11[9]` is part of the
complete qualified x9 Port-A boundary footprint — clearing that one bit makes an
otherwise working clone static. Two GND-fed `AddressA` final edges must be
emitted with **complete** exact fields; a generic two-bit selector emission
omitted three required bits.

### BRAM negatives — do not re-chase these **[S]**

- **`AddressA[3]`/`IMUX09`, `AddressA[4]`/`IMUX08`, `AddressA[5]`/`IMUX07` each
  returned `0xfffffffe` for 256/256 reads.** The named terminal-identity /
  permutation class is **functionally eliminated**.
- **All-zero and all-one images differing at every one of the 9,216 `INIT_VAL`
  cells produced the same `0xfffffffb` at all 256 addresses** — in the reduced
  open route, where `AddressA[6:12]` had no drivers or terminal selections.
- Interpretation note **[U]**: those earlier static observations *remain valid*,
  but their reading as "dead INIT/address behaviour" is **superseded** — the
  isolated constant was caused by **incoherent constant address terminals**.
- **Fail-closed:** writes, byte enables, output registers, width/mode
  composition, independent clocks, collision / read-during-write, the remaining
  high-address range, and every BRAM site other than `X13Y4`.

A soft-logic path exists for anything the hard-block model does not represent:
BRAM inference is accepted **only** for patterns the integrated model covers;
unsupported semantics must use soft logic or fail.

---

## Clocks and the PLL

### PLL emission **[R]** — one closed-form equation, byte-exact

The PLL configuration is emitted from a **single closed-form divider equation**,
not a per-ratio lookup table. It is **differentially validated byte-exact on
every point of a 53-point vendor `(SYSCLK, HSE)` sweep** — all 53 decoded
preambles reconstruct with zero residual. Seven profiles are emitted:
`(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, `(100,16)`, `(60,8)`, `(100,12)` MHz.
Every other ratio — including byte-exact-but-unqualified `HSE != 8` sweep points
— **fails before synthesis**.

The generated 164-byte preamble for each of the seven profiles is pinned to its
retained vendor-oracle hash in `agamemnon/chipdb/pll_profile_manifest.json`.

### PLL silicon status **[S]**

**The silicon-qualified surface is `HSE = 8 MHz`, `SYSCLK` 4–248 MHz.**
`qualification/pll_freq_evidence.jsonl` holds **43 frequency rows**: the five
`HSE = 8` profile rates qualified earlier plus **38 sweep rates**.

Method **[S]**: firmware selects the PLL, then the effective clock is read
against the **OpenOCD host wall clock** — MTIME counts the system clock, so an
external host timer is the only clock-independent reference. OpenOCD resumes for
a known window, halts, and reads elapsed MTIME across a **1 s and a 4 s** window;
solving `measured = true × (T − offset) / T` for both windows yields the true
frequency and a fixed **~26 ms** host resume/halt offset.

Result: **all 38 promoted rates pass, worst 0.058 % off the requested rate**,
with the PLL locked and selected and the DAP/SWD link surviving halt/readback at
every rate up to 248 MHz.

Extras: `(60,8)` additionally closes the strict L48 16-bit bus-clock instrument
at 60 MHz (110.34 MHz reported Fmax). `(10,8)` is numerically equal to the
10 MHz HSI reference but is **confirmed PLL-driven** by the clock-register
lock/select bits.

**Negatives [U]:** `(100,16)` and `(100,12)` cannot be exercised on the 8 MHz-HSE
reference board (they need 16/12 MHz HSE and would mis-clock), so they are
**preamble/timing-qualified only**; **no other HSE is claimed**. Other PLL
outputs, phase, duty cycle, feedback and bypass modes are **not qualified and
fail closed**. No general oscillator source is implemented — internal/external
oscillator modes are **absent** from the open flow and **unqualified**.

Default when no frequency is supplied by CLI, project or environment: the
qualified **10 MHz** setting.

### The decoded PLL configuration chain **[R]** / **[U]**

The PLL's own serial configuration chain is decoded as **66 fields spanning 239
bits**, contiguous with no gaps or overlaps from bit 0 to bit 238. Reachable
through the FCB non-auto path at chain address `0x401`, 8 words = 256 bits
(comfortably ≥ 239). **[U]** for that addressing.

Structure: an analog-trim block, then N / M / G0–G4 divider blocks each with
`BYPASS_*`, `DIVNUM_H*`, `EN_DUTYTRIM_*`, `DIVNUM_L*`, then a
delay/mux/enable block.

| Region | Fields |
|---|---|
| Analog trim | `CFG_IVCO` (3, default `b010`), `CFG_RVI` (2, `b01`), `CFG_RREF` (2, `b01`), `CFG_RLPF` (2, `b01`), `CFG_POST_SCALE_COUNTER` (1), `CFG_DUMMY` (5), `CFG_ICP` (3, `b100`) |
| Input divider N | `CFG_BYPASS_N` (1), `CFG_DIVNUM_HN` (8), `CFG_EN_DUTYTRIM_N` (1), `CFG_DIVNUM_LN` (8) |
| Feedback divider M | `CFG_BYPASS_M`, `CFG_DIVNUM_HM` (8), `CFG_EN_DUTYTRIM_M`, `CFG_DIVNUM_LM` (8) |
| Output dividers G0–G4 | the same four-field pattern per output |
| Delay / mux / enable | `CFG_DLYNUM_G0..G4` (8 each), `CFG_CLK_EN0..4`, `CFG_SELCLK_G0..G4` (3 each), `CFG_CASCADE0..3`, `CFG_DLYNUM_M` (8), `CFG_SELCLK_M` (3), `CFG_ENB_PLLOUTP`, `CFG_ENB_PLLOUTN`, `CFG_FEEDBACK_MODE`, `CFG_PllSeamMUX` (3), `CFG_DUMMY1` (3), `CFG_PllClkInMUX` (3), `CFG_PLLFB_DLY` (3), `CFG_PllClkFbMUX` (2), `CFG_PLL_EN_FLAG` (1, **default `b1`**), `CFG_REG_CTRL` (2) |

> ⚠️ **Only 5 of the 66 fields have any byte-position validation**, and all five
> only partially: `CFG_DIVNUM_HN` and `CFG_DIVNUM_LN` (low bit only),
> `CFG_DIVNUM_HG0` and `CFG_DIVNUM_LG0` (bits 0–2), and `CFG_EN_DUTYTRIM_G0`.
> The other **61 read "enumerated (arch DB); byte-position unmapped."** Field
> names, widths and chain order are architecture-DB data **[R]**; the mapping
> from chain bit to image byte is **unknown [U]** for 61 of 66.
>
> **The chain is bit-scrambled relative to the byte image.** `CFG_DIVNUM_LG0`
> bits 0–2 land at non-monotonic byte positions (`144.0`, `146.6`, `146.5`).
> Never treat a chain bit index as a byte offset.

Field-name capitalization is inconsistent in the source and is preserved here:
`CFG_PllSeamMUX`, `CFG_PllClkInMUX`, `CFG_PllClkFbMUX` are camel-case; the rest
are upper-snake.

### Global clock distribution **[S]** subset

Clock distribution to **near and far logic tiles** is silicon-qualified using
the listed PLL configurations. **[S]** Anything beyond those configurations, and
the complete clock/global-clock resource surface, is open work.

The MCU↔fabric **External-AHB `bus_clock`** is a third, separate clock boundary
— see [the MCU boundary](#the-mcufabric-boundary).

---

## The IO ring, bond maps, and reaching a package pad

### How a pad is reached **[S]**

There is **no fixed alternate-function bond matrix on this part.** A signal
reaches a package pad only by being routed, in the loaded fabric image, to an
**IOTile pad slot** on the ring. That is true both for fabric logic *and* for
MCU hard-peripheral signals, which arrive at the fabric as named boundary GPIO
ports and are bound to pads by the fabric design. Change the fabric image and
you change the pinout. The MCU-side consequences are in
[HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md).

**Until firmware FCB-configures the fabric, every pad reads static.** **[S]**

### The L48 bond map **[S]** (the map) / **[R]** (the fields)

`chipdb/bondmap_L48_full.csv` in the workbench (and `bondmap_L48.csv` in the
shipped chipdb) lists **34 bonded fabric-IO pads**. Columns:

```
agm_pin, iotile_x, iotile_y, z, edge, iomux_index, padfeed_rmux
```

Structural note **[R]**: `z` and `iomux_index` are **identical in all 34 rows**,
so the file carries six independent quantities, not seven.

| Edge | Count | Pins |
|---|---|---|
| RIGHT | 1 | PIN_2 at `(22,2)` |
| TOP | 13 | PIN_10 … PIN_22 at `y = 13`, `x ∈ {14, 17, 18, 19, 20}` |
| LEFT | 11 | PIN_25 … PIN_35 at `x = 0`, `y ∈ {1, 2, 4}` |
| BOTTOM | 9 | PIN_37, 38, 39, 40, 41, 42, 43, 45, 46 at `y = 0`, `x ∈ {1, 17, 18, 19}` |

Representative rows, exact:

```
agm_pin,iotile_x,iotile_y,z,edge,iomux_index,padfeed_rmux
PIN_25,0,4,0,LEFT,0,30
PIN_26,0,4,1,LEFT,1,0
PIN_27,0,4,2,LEFT,2,18
PIN_28,0,4,3,LEFT,3,6
PIN_29,0,2,4,LEFT,4,42
PIN_10,20,13,1,TOP,1,28
PIN_15,19,13,1,TOP,1,12
PIN_2,22,2,3,RIGHT,3,18
PIN_37,1,0,0,BOTTOM,0,16
```

`z` / `iomux_index` runs 0–3 on TOP/RIGHT/BOTTOM but **0–5 on LEFT** — LEFT
tiles `(0,1)` and `(0,2)` use `z = 4` and `z = 5`. `padfeed_rmux` values
observed: 0, 4, 6, 8, 12, 16, 18, 20, 24, 28, 30, 36, 42 — all even, and **not
unique across pads** (0 appears for PIN_17, PIN_19, PIN_26 and PIN_33).

> ⚠️ **`padfeed_rmux` is per-build routing, not a pad property. [U]**
> The column records the IOTile RMUX that fed the pad *in the one vendor
> `pintest` build the map was decoded from* — the chain is
> `LogicTILE(sx,sy).RMUX{src} → IOTILE(px,py).RMUX{R} → IOMUX{z} → pad`, and
> `padfeed_rmux` is that `R`. A **second** vendor pintest bondmap in the same
> workbench gives *different* `padfeed_rmux` values for pins it shares
> (PIN_11 `0` vs `12`, PIN_12 `20` vs `16`, PIN_13 `8` vs `24`, PIN_15 `4` vs
> `12`, PIN_16 `0` vs `8`, PIN_18 `8` vs `28`), while `(x, y, z)` agrees in every
> case. So **`(agm_pin → x, y, z, edge)` is the stable bond fact; `padfeed_rmux`
> is one witnessed route among several.** Do not treat it as the only way to
> reach a pad.

Pin numbering is **not contiguous**: there is no PIN_23, PIN_24, PIN_36 or
PIN_44 row, and nothing below PIN_2 or above PIN_46. Those are the LQFP-48's
power/ground/dedicated pins.

### The 14 L48 package pins that are *not* fabric IO **[R]**

From the datasheet-derived pin table in the research workbench
(`AG32-Docs/docs/reference/PINS_DATASHEET.md`,
`AG32-Docs/tools/agamemnon/chipdb/pins_datasheet.csv`). These explain every gap
in the pad numbering:

| Pin | Function | Pin | Function |
|---|---|---|---|
| 1 | `VBAT` | 23 | `VSS33` / GND |
| 3 | `OSC32_IN` (LSE 32 kHz) | 24 | `VDD33` |
| 4 | `OSC32_OUT` | 36 | `VDD33` |
| 5 | **`OSC_IN`** (HSE) | 44 | **`BOOT0`** |
| 6 | **`OSC_OUT`** (HSE) | 47 | `VSS33` / GND |
| 7 | **`NRST`** | 48 | `VDD33` |
| 8 | `VSSA` / GNDA | | |
| 9 | `VDDA` | | |

34 fabric IO + 14 dedicated = 48. ✔ The L48 crystal pins are **dedicated**, not
muxed: `OSC_IN`/`OSC_OUT` are pins 5/6 and the 32 kHz pair is 3/4. `BOOT0` is
its own pin (44); **`BOOT1` is not** — see the alt-function table below.

### ⚠️ Alternate functions that live *on* fabric pads — read before you assign a pin **[R]**

Every pad below is a normal, assignable fabric IO **and** carries a hard-function
alternate. Claiming one from the fabric can take out your debug link, your USB,
or your recovery path. This is the pin-level detail behind the
"no fixed alt-function matrix" rule.

| Pad | Alternate function(s) | Risk if you drive it from the fabric |
|---|---|---|
| **PIN_34** | **`JTMS`** | ⚠️ **kills SWD/DAP** — this is your primary debug and programming transport |
| **PIN_37** | **`JTCK`** | ⚠️ **kills SWD/DAP** |
| PIN_38 | `JTDI` | JTAG chain |
| PIN_39 | `JTDO` | JTAG chain |
| PIN_40 | `JNTRST` | JTAG reset |
| **PIN_32** | **`USBDM`** | ⚠️ breaks the USB CDC uploader transport |
| **PIN_33** | **`USBDP`** | ⚠️ breaks the USB CDC uploader transport |
| **PIN_30** | **`UART0_TX`** | ⚠️ breaks the mask-ROM UART recovery path |
| **PIN_31** | **`UART0_RX`** | ⚠️ breaks the mask-ROM UART recovery path |
| **PIN_20** | **`BOOT1`** | ⚠️ affects boot-mode selection |
| PIN_29 | board **button** | ⚠️ see the dedicated warning below |
| PIN_2 | `RTC`, and the only **`IO_GB`** (global-clock-capable) pad identified on L48 | RTC; also the sole RIGHT-edge pad |
| PIN_10 | `WKUP`, `ADC_IN0`, `CMP_PA0` | wake-up + analog |
| PIN_11 … PIN_13 | `ADC_IN1..3`, `CMP_PA1..3` | analog |
| PIN_14 | `ADC_IN4`, `CMP_PA4`, **`DAC0`** | analog |
| PIN_15 | `ADC_IN5`, `CMP_PA5`, **`DAC1`** | analog |
| PIN_16 … PIN_19 | `ADC_IN6..9` | analog |

Note the overlap with the qualified pads: **PIN_31 is simultaneously board LED4
(`GPIO4.4`), a fabric-IO pad, and `UART0_RX`** — three claims on one pin,
resolved only by the loaded fabric image. And **PIN_10/PIN_11/PIN_15/PIN_19**,
the four silicon-qualified fabric *inputs*, are all `ADC_IN*` pads.

> **This table also undermines the "ADC channels 0–3 are not bonded on L48"
> claim** made in `ag32_adc.h`. `ADC_IN0..3` are listed here as alternates of
> `PIN_10..PIN_13` — pads that are bonded and have been driven as working digital
> IO on the bench. See the analog caveat in
> [HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md#analog-adc012-dac01-cmp0--on-the-external-ahb-window-not-mcu-mmio).

### ⚠️ The L48 IO count is disputed: 34 or 32 **[U]**

| Source | Count | Treatment of PIN_34 / PIN_37 |
|---|---|---|
| Reference manual + on-die `CHIP_INFO` user-pin set | **34** | user IO, with `JTMS`/`JTCK` as *alternates* |
| Shipped `chipdb/bondmap_L48.csv` and the workbench full bondmap | **34** | present as ordinary pad rows |
| Vendor Application Guides (Native v4.2, Compatible v3.2) | **"Total available IOs: 32"** | printed as **`TMS`** and **`TCK`**, *not* IO |

The two guides also disagree with the reference manual elsewhere on the same
pinout diagram — they show fingers 3/4/5/6 as `NC` rather than the OSC pins, and
finger 1 as `VDD33` rather than `VBAT`.

**AGaMEMnon sides with 34**, because the bond map contains PIN_34 and PIN_37 rows
and the exact map is silicon-qualified. But if you assign PIN_34 or PIN_37, you
are using a pad that one vendor document says is not an IO at all — and that in
practice carries your debug link. **Treat those two as 34-minus-2 in anything
safety-relevant.**

### ⚠️ PIN_29 is the board button. Never drive it as an output. **[S]**

`PIN_29` is a fully bonded fabric-IO pad at `(0,2)`, `z = 4`, LEFT — nothing in
the tooling stops you from driving it. **Driving it high while the button is
pressed shorts the pad driver to ground.** It is deliberately excluded from the
pad-walk harness, which is why the tooling talks about **33 drivable** pads
(34 bonded − PIN_29) while the bond map lists 34. The exclusion is a **safety
policy, not a bonding fact**.

### Qualified L48 pads **[S]**

| Direction | Pads | Notes |
|---|---|---|
| Fabric **outputs** | **PIN_25, PIN_26, PIN_27, PIN_28** | including **concurrent use**; characterized header outputs |
| Fabric **inputs** | **PIN_10, PIN_11, PIN_15, PIN_19** | PIN_19 also has a qualified **registered** input path |

17 of the 33 drivable pads are confirmed wired through to the bench harness by
frequency pad-walk (every one of PIN_10…PIN_19, plus PIN_21, PIN_22, PIN_25–28
and PIN_35), and every one of those 17 tile/edge triples matches the bond map
exactly. **[S]** The 16 no-signal pads cluster geographically — every BOTTOM
pad, the sole RIGHT pad, and most of LEFT tile `(0,1)` — while TOP and LEFT tile
`(0,4)` work; whether that clustering is electrical or simply unwired harness
pins is **explicitly not proven [U]** (there are 33 drivable pads but only 26
usable harness pins, so at least 7 cannot be wired at all).

### Packages **[S]** / **[R]**

**L48 is an exact, silicon-qualified map. `AGRV2KL100`, `AGRV2KL64` and
`AGRV2KQ32` are architecture-recovered research data; strict image emission
fails closed for them, and they do not inherit L48 qualification.**

Package evidence never transfers by pin number. The harness mapping
PIN_25/26/27/28 → Pico GP12/GP13/GP16/GP17 is package- and board-specific.

### The IO electrical configuration chain **[R]** / **[U]**

Each pad's electrical attributes live in a serial configuration chain, decoded
as **26 field rows across 7 chain types**. Reachable through the FCB non-auto
path at chain address `0x400`, 27 words. **[U]** for that addressing — and note
that "27 words" (864 bits) is a per-device chain length, **not** the 26 field
rows; do not conflate them.

**`SINGLE`** — the base IO-electrical chain, 6 fields / 10 bits:

| Field | Width | Chain bit | Default(s) | Meaning |
|---|---|---|---|---|
| `CFG_INPUT_EN` | 1 | 0 | `1;0;1` | input buffer enable |
| `CFG_PULL_UP` | 1 | 1 | `0;1` | weak pull-up enable |
| `CFG_SLR` | 1 | 2 | `0;0` | slew-rate limit (slow slew) enable |
| `CFG_OPEN_DRAIN` | 1 | 3 | `0;0` | **open-drain output enable** |
| `CFG_PDRCTRL` | 4 | 4 | `0010;0010` | programmable drive strength |
| `CFG_KEEP` | 2 | 8 | `00;00` | bus-keeper mode (off / keeper / pull) |

Derived chains:

| Chain | Inherits | Adds | Total bits |
|---|---|---|---|
| `SINGLE_IN` | — | `CFG_MCUTEST_EN` (1) — MCU test-mode input enable | 1 |
| `SINGLE` | — | (above) | 10 |
| `SINGLEP` | `SINGLE` | `CFG_WKUP_EN` (1), `CFG_WKUP_INV` (1) — wake-up detect + polarity | 12 |
| `OSC` | `SINGLE` | `CFG_RCOSC_EN` (1), `CFG_RCOSCCAL` (7), `CFG_RESSEL` (2) | 20 |
| `USB` | `SINGLE` | `CFG_PULLUP_ENB` (1, **active-low**), `CFG_DIFF_EN` (1), `CFG_PULLDN_ENB` (1, **active-low**) | 13 |
| `MIPI_TX` | — | `CFG_SELDLY_DACLK` (3), `CFG_SELDLY_CKCLK` (3), `CFG_SEL_RPD` (2), `CFG_SEL_RPU` (2), `CFG_SEL_LPSRC` (2), `CFG_SEL_TX_VREF` (3) | 15 |
| `MIPI_RX` | — | `CFG_SEL_DLY_DA1` (3), `CFG_SEL_DLY_DA0` (3), `CFG_SEL_DLY_CK` (3), `CFG_SEL_HSRX_CUA` (2), `CFG_SEL_LPSRC` (2) | 13 |

Two traps **[U]**: `CFG_SEL_LPSRC` appears in **both** MIPI chains at different
positions — always qualify it by chain. And the `defaults` column is a
semicolon-separated variant list whose **length is not uniform** (most rows have
two values; `CFG_INPUT_EN` has three), so a positional read of it is unsafe.
This file carries **no confidence column at all**, so nothing in it makes a
validation claim.

### IO electrical qualification — the honest gap **[U]**

The **decode** is much broader than the **qualification**. The device supplies a
checked 15-chain / four-alias / 26-field static inventory, two-pad
pull-up/open-drain oracles, and the complete **2–30 mA `CFG_PDRCTRL`** mapping
**[R]** — but:

> The RIO drive-current, pull-up, and open-drain domains are populated, but
> **their open support is empty and electrical behaviour unqualified**.

Specifically **not** qualified: **dynamic output enable, open-drain, and
bidirectional (shared-wire) behaviour**. Static input/output support **must not**
be read as bidirectional support. The prepared one-pad and four-link
bidirectional images are **human wiring gates** — build-supported with all 102
routed PIPs mapped and zero unmapped selectors, but **electrical
drive/release/readback is human-gated**. I2C's open-drain requirement, in
particular, is a *decoded* capability with no electrical silicon record.

---

## The configuration surface — the three-plane model

The 99,936-byte raw configuration decomposes into three planes, each a different
*kind* of configuration. This partition is the map to "completely open".

| # | Plane | What it is | Decode state |
|---|---|---|---|
| **1** | **LUT function plane** | the logic-cell truth tables (`LUT INIT`) — *what each cell computes* | ✅ **decoded**: `physmap.init_bit_pos`, **33,792** positions, unconfigured default `0x00` **[R]** |
| **2** | **Routing / cell-interconnect plane** | the mux/selector fabric — `CFG_RMUX`, `IMUX`, `OMUX`, `CTRLMUX`, `SEAMMUX`, `BBMUXS`, `IOMUX` — *how the cells connect* | ⚠️ **~26 % named, ~74 % not yet mapped** to resources. This is the big `0xFF` region: cols 59–114, **227,652 bits** at their complemented-all-ones default **[R]** / **[U]** |
| **3** | **Subsystem / peripheral config plane** | everything that is neither a logic cell nor a fabric route: clock/PLL (in the preamble), IO electrical / OE / bank config, BRAM modes and ports, and the hard-block edge interfaces | ⚠️ **subset** decoded — this *is* the peripheral surface **[R]** / **[U]** |

**Completely open = generate all three planes from the architecture DB.
Vendor parity = know what every bit in all three planes does. They are the same
decode viewed two ways.**

Marked as hypothesis in the source **[U]**: plane 2 being the cell-interconnect
plane is measurement-backed (family overlap), but the per-bit resource
assignment of the unnamed ~74 % awaits the crossbar-table promotion; and the
plane-3 boundary (which residue bits are IO vs BRAM vs hard-block) is "a working
partition, not yet bit-exact."

---

## Bitstream and base-image layout

### The two image forms **[S]**

| Form | Size | Structure |
|---|---|---|
| **Raw configuration** | **99,936 bytes** | 164-byte preamble + 99,768-byte body + 4-byte CRC |
| **SRAM / flash device image** | **99,944 bytes** | 8-byte device header + the 99,936-byte raw image |
| Compressed image | variable | the same 8-byte header + an AGRV2K **LZW** stream |

`164 + 99,768 + 4 = 99,936`. ✔

### The 8-byte device header **[S]**

```
40 20 00 01 00 00 ff ff
```

That is two big-endian 32-bit words: `DEVICE_ID = 0x40200001` followed by
`MAX_INDEX = 0x0000FFFF`. Both are pure constants — there is nothing
design-specific in the header. 99,944 bytes is the length firmware passes to
`ag32_fcb_config()` (24,986 words).

### The body **[R]**

The body occupies raw offsets `[164 : 99932]` = **99,768 bytes**, addressed as a
grid of **116-byte word-lines**:

```
word_line = (offset - 164) / 116
column    = (offset - 164) % 116
```

99,768 / 116 = 860 remainder 8 — so word-line indices **0 … 859** are complete
(860 × 116 = 99,760 bytes) and an **8-byte tail** occupies `[99924 : 99932]`
immediately before the CRC. **[R]** (arithmetic on sourced constants; the
reserved-region tables reference word-lines up to 859, consistent with 860.)

Reserved / structural regions in the body **[R]**:

| Region (word-lines × columns) | Meaning |
|---|---|
| `0…497 × 59…114` | main crossbar block (the big `0xFF` plane-2 region) |
| `0…21 × 36…58` | top tile-row selector band |
| `0…21 × 0…3` | top-left seam band |
| `838…859 × 0…3` | bottom-left seam band |
| word-lines `22…497`, **column 58** | the framing column |

The reserved routing/seam SRAM default is **227,652 bits** at
complemented-all-ones, of which **28,570** are emitted from the promoted
`logictile_config_template.csv`.

### The CRC **[S]**

**CRC-32/BZIP2**: polynomial `0x04C11DB7`, init and xorout `0xFFFFFFFF`,
**big-endian** output, stored in the last four bytes at offset **99,932**.

It covers **`header[0:8] + raw[0:99932]`** — i.e. the 8-byte device header *is*
part of the checksummed data even though it sits outside the raw image. Getting
that wrong is an easy way to produce an image the FCB rejects with
`STAT_ERR_CRC` (bit 6 — see the FCB section of
[HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md)).

Note this is a *different* CRC variant from the MCU's hard CRC0 block's default
(CRC-32/MPEG-2), even though both use the same polynomial.

### The config-body geometry transform **[R]** — validated bit-exact

This maps a decoded per-tile configuration cell `(x, y, word_row, bank_col)` to
its position in the config body. It is **validated byte- and bit-exact against
the silicon-validated physmap LUT-INIT formula, 73,216 / 73,216.**

```
word_line = 838 - 68*y + word_row          # tile rows run bottom y=0 -> top
rank      = K(x) - bank_col                # rank DECREASES with bank_col
K(x)      = 935 - 36*x                     # for x < 13
K(x)      = 935 - 36*x - 144               # for x >= 13  (the BRAM column)
col, k    = divmod(rank, 8)
bit       = 7 - k                          # MSB-first within a byte
offset    = 164 + 116*word_line + col
```

Equivalently, going the other way: `rank = col*8 + (7 - bit)`.

Reading the constants:

| Constant | Meaning |
|---|---|
| `838` | the word-line of tile row `y = 0`'s `word_row = 0` — tile rows run **bottom-up** |
| `68` | word-lines per tile row |
| `935` | the rank base at `x = 0` |
| `36` | bit ranks per tile column |
| `144` | the extra ranks consumed by the **BRAM column at `x = 13`**, subtracted for every `x >= 13` |
| `7 - k` | bits are **MSB-first** within a byte |

Two things to internalise: **`y` runs bottom-to-top** (increasing `y` *decreases*
the word-line), and **`x` runs right-to-left in rank/column order** (increasing
`x` *decreases* the rank).

This transform is what let the last 227 residual body bytes be attributed to
named cells: **408** canvas-asserted bits map to named LogicTile cells
(`x, y, word_row, bank_col → CFG_<MUX>`) through the transform, **fail-closed**
against the promoted LogicTile template, plus **15** bits on template-blank
`XXXX` spare bit-lines (`bank_col 33`, `word_rows 9` and `57`) whose **position
is known but meaning is unproven [U]**.

### `fabric_default.bin` — a template, not a loadable image

| Property | Value | Tier |
|---|---|---|
| Size on disk | **2,839 bytes** ("2.8 KB compressed") | **[S]** |
| First 8 bytes | `40 20 00 01 00 00 ff ff` — the standard device header, then an LZW stream | **[S]** |
| **Stored CRC** | **`0xAD5B5DB9` — stale** | **[R]** |
| CRC recomputed over its own bytes | **`0x4B36B054`** | **[R]** |
| `bitstream_inspect` verdict | **`crc valid: False`** | **[R]** |

> This is **harmless in the normal flow, because bitgen always recomputes and
> overwrites the CRC** — but it is a clean tell that the file is a *frozen
> vendor artifact we inherit, not something we author*. Treat it as a
> **template**: it is **not directly loadable**.
>
> **[S] The rejection IS demonstrated, as its own controlled experiment**
> (2026-08-14). Two 99,944-byte SRAM images were built that differ in *exactly*
> the four CRC bytes and nowhere else — `HEADER + decoded canvas` versus
> `HEADER + default_frame.build()` — and each was SRAM-loaded and handed to
> `ag32_fcb_config()` by identical firmware:
>
> | image presented to the FCB | `FCB_STAT` | meaning |
> |---|---|---|
> | canvas body + **stale** CRC `0xAD5B5DB9` | **`0x00000040`** | bit 6 = `STAT_ERR_CRC` — **rejected** |
> | same body + **correct** CRC `0x4B36B054` | **`0x000f0002`** | ACTIVE\|INIT_EMB\|CFGDONE\|CHIP_RSTB\|DEVOE — **configured** |
>
> Because the two images are byte-identical outside the CRC field, this isolates
> the CRC as the cause. Two consequences worth stating plainly: **the FCB really
> does validate the CRC** (it is not ignored), and **a byte-faithful copy of
> `fabric_default.bin` would be a broken image** — recomputing the CRC is
> mandatory, not cosmetic.

### From-scratch base generation — where it actually stands

Progress on regenerating the base image without the vendor canvas, measured
against the **decoded** canvas over preamble + body: **[R]**

| Candidate | Body byte-exactness |
|---|---|
| A | 70.33 % (70,168 / 99,768) |
| B | ≈ 71 % |
| C | 99.77 % (99,541 / 99,768) |
| **final** | **100 % (99,768 / 99,768)** |

The final step promoted `border_edge_partial_cells.csv`, closing the last 227
partial border/edge bytes. The two 99,936-byte files are then identical over
`[0:99932]` and **differ only in the 4 CRC bytes** — the generated one carries a
*valid* CRC.

> ⚠️ **This is a static comparison and nothing more.** Quoting the source:
> *"100 % byte-exact is measured against the decoded canvas — a static
> comparison. It is not evidence that a regenerated image boots or configures
> identically on silicon."* Silicon status for a fully from-scratch
> configuration image is **unqualified**, packages **none**. The from-scratch
> path is **opt-in** (`AGAMEMNON_FROM_SCRATCH_BASE`) and filed as
> *experimental / decoded / unapproved / inventory only*; default bitgen still
> loads the canvas.
>
> **The remaining gate is a hardware-in-the-loop boot check**: build a real
> design on the generated base, flash it, and confirm it configures and boots
> identically to the canvas-based build. Until then `fabric_default.bin` remains
> the last vendor thread in the weave. **[U]**

What remains genuinely unknown is now a *validation* gap rather than a *decode*
gap — with the honest exception that the **function** of every unnamed reserved
selector bit-line and of the 15 `XXXX` spares is still not named. **[U]**

---

## Routing

### The selector model **[R]**

A general routed connection selects a **two-hot pair** in its destination `RMUX`
or `IMUX` block. The release tables contain:

| Encoding class | Count | Status |
|---|---|---|
| Conflict-free **physical** edge encodings | **659,759** | admitted **[R]** |
| **Tile-relative** encodings, unanimous across all physical observations | **62,044** | admitted **[R]** |
| Conflicted physical keys (preserved in a conflict atlas) | **74,103** | **not** admitted **[U]** |

> ⚠️ **These are corpus counts, not device-coverage percentages.** The 659,759
> rows are **90 % of 733,862 keys in the historical observed recovery corpus**.
> They are **not "99 % of the fabric"** and do not imply 90 % of all device
> routes are available. The measured baseline exposes **at least one clean edge
> in 159 of 322 grid tiles**.

Conflicting, predicted, or unresolved selectors **fail closed**. Six reviewed
`RMUX30` rows are admitted **experimental-only** and disabled by default behind
`experimental-strict`.

### A hard invariant: an `IMUX → alta_slice → OMUX` segment is **not** a wire **[S]**

Vendor route tables sometimes cross a real LUT buffer. That segment is a
**logical cell arc**, not a routing PIP. The release graph excludes those rows
unless synthesis/packing actually instantiates and configures the LUT —
otherwise an unused LUT's reset INIT masquerades as a transparent wire. **The
first constant-slave silicon run exposed exactly that failure on three HRDATA
lanes**, and the corrected rebuild fixed it.

A narrow exception table (`chipdb/route_through_footprints.csv`) admits **four
exact site/final-edge combinations** — the two original low-lane x9 readback
buffers, the x9 data-bit3 buffer at `X14Y4 slice0`, and the
`HADDR11`/`AddressA12` split at `X14Y7 slice3`. It is **exact-site and does not
generalize arbitrary transparent LUTs**; an `AGRV2K_ROUTE_THROUGH=1` request
outside it fails.

Recovered vendor paths that cross `alta_slice` remain **logical-cell evidence
and are not admitted as transparent routing PIPs [U]**.

### The conduction reframe — read this before trusting any "dead edge" list

This is the most important epistemic correction in the project, and it inverts
an earlier model.

The device database carries a small **negative-evidence set** of routing edges
the release router conservatively blocks. Those were originally classified from
negative silicon trials — **but that classification is now known to be
unreliable, because the trials were not truly isolated.** They came from **one
large, congested MCU-exit design**, and the failures were a **congestion-context
effect mis-attributed to individual edges**.

| Originally catalogued | Outcome | Tier |
|---|---|---|
| **14** edges | — | — |
| **2** — `RMUX21@(14,10) → RMUX87@(14,8)` and `RMUX63@(10,4) → RMUX68@(9,4)` | **conduct in every clean, isolated build** (vendor-native, our natural routing, and our routing forced through the exact pip) → **removed from the negative set and admitted as silicon-verified conducting edges** | **[S]** |
| **12** | **stay conservatively blocked pending an isolated per-edge silicon test** — treated as **unverified, not proven-dead** | **[U]** |

The gate *mechanism* is unchanged: negative evidence has absolute precedence
over positive attribution. **Only the data was corrected.**

Two claims must stay distinct, because merging them has burned people
repeatedly:

1. **Per edge**, the dead catalogue was an artifact and the gate was
   over-restrictive.
2. **Wide / congested designs** (a fabric AHB master, full-word MCU writes) are
   still an open, unproven frontier.

The real limiter is **aggregate MCU-exit congestion** — a routing/allocator
problem in the open flow — **not per-edge silicon death**.

> **Stale text warning.** [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) still
> says *"The release database contains 14 isolated dead-edge classifications."*
> That count and the word "isolated" are **superseded** by
> [STATUS.md](STATUS.md). The claim-policy ledger likewise still files the
> mechanism as `decoded / unapproved / inventory only` against
> `dead_edges_silicon.csv`.

### Placement and scale **[S]** / **[U]**

Silicon-qualified **[S]**: combinational logic, registered feedback, counters,
shifts, state machines, constants, physical-input registers, and **large
sequential designs** — randomized 16-, 32- and 64-bit LFSRs, xorshift, and
nonlinear state machines, plus large routed **SERV** designs.

Integrated designs on silicon **[S]**:

| Design | Evidence |
|---|---|
| **SERV** RISC-V soft core | true-dual-port BRAM blinky plus a named instruction-signature workload: continuing fetch/store operation with dependent `addi`, `slli`, `xori`, not-taken `bne`, taken `beq`, `sw`, and repeated backward `jal`. **This is not full RV32I compliance [U]** — other instructions, R-type `ADD`, exceptions, CSRs, interrupts and complete trap behaviour are outside the claim. |
| **Serial mux** | **three simultaneous 9,600-baud inputs merged to a 115,200-baud output** — the only measured serial line-rate claim on silicon |

Scale ceiling **[U]**: driving the *vendor* back-end through a wide MCU-AHB
slave design reaches ~**84 % fabric** (≈1,800 logics across ~120–130 tiles), so
a wide slave is **placeable in principle — fabric capacity and MCU-edge
corridors are not the limit**. The open flow's limiter is that the `agrv2k`
nextpnr placer must perform a net-inversion / async-control legalization step
the vendor offloads to its Quartus fork's pre-pack. Making the placer/router
close larger *fresh* designs is open toolchain work.

### Timing **[R]** / **[U]**

A **conservative estimate with a bounded exact overlay**:

| Quantity | Value |
|---|---|
| Certified local pairs | **542** |
| Ordinary L48 route pips they cover | **9,375** |
| Ordinary route pips on worst-family fallback | **226,540** |
| Total ordinary routing pips in the strict L48 release graph | **235,915** |
| Exact slow-corner maximum for the whole annotated `alta_slice → OMUX → IMUX` local pattern | **0.401 ns** |
| Four-node local pattern total (**not** split — no proven per-pip decomposition) | **0.613 ns** |

A requested-but-unavailable timing figure is a **fatal** error, not a silent
fallback. But:

> **Exact native wire-class binding, clock skew, IO, BRAM, PLL, package, and
> broad PVT delays are not modeled. Timing reports are not silicon Fmax
> guarantees.** Non-L48 package selections keep the conservative model for every
> routing edge.

Historically the conservative bound has run **1.65×–4.1× pessimistic and never
optimistic**, which is the direction you want but not a sign-off model.

---

## The MCU↔fabric boundary

The RISC-V core is a hard block (`alta_rv32`). It exposes its interfaces to the
fabric through **named ports** that a fabric design binds to on the same nets —
there is no physical IO in this path; it is an internal fabric↔MCU edge. **[R]**

| Port group | Direction | Meaning |
|---|---|---|
| `mem_ahb_*` | MCU master → fabric slave | the MCU reads/writes a fabric-resident slave — the External-AHB window at `0x60000000` |
| `slave_ahb_*` | fabric master → MCU slave | a fabric master reads/writes MCU SRAM |
| `ext_dma_*` | both | DMA request/ack lines |
| `local_int` | fabric → MCU | fabric-sourced local interrupts (CLINT local causes 16–19) |

A protocol-valid MCU write drives `mem_ahb_hwrite` + `mem_ahb_htrans[1]` in the
address phase and 32-bit `mem_ahb_hwdata` in the completing data phase; the
slave returns `mem_ahb_hreadyout` / `mem_ahb_hresp` and, for reads, drives all
32 `mem_ahb_hrdata` lanes. **The clock edge that matters for data capture is the
fabric bus clock, not the system clock.** **[R]**

### Bus clock **[S]**

The qualified default topology aliases `bus_clk` to `sys_gck`. Pure-open silicon
evidence: direct-D self-feedback at **X14Y11 slices 4 through 7**, all eight
states of an explicit three-bit counter, and **500 distinct states** of a 16-bit
XNOR LFSR through `HRDATA[15:0]`. Correlated against MTIME with both MCU and
MTIME undivided from the 10 MHz reference, **three runs covering 45 intervals
each measured exactly one fabric state transition per MTIME tick** — qualifying
the default bus clock at **10 MHz** relative to that reference. A GPIO4.1-fed
synchronous reset held all 16 state bits at zero and re-armed across three runs
(36/36 asserted-reset reads zero).

**Fail-closed [U]:** unrestricted direct-D placement, hard `MCU_RESETN`, equal
post-release phase, and explicit BUSCLK/PLL3 clocking.

### What is qualified across the boundary

The MCU-side view — read/write widths, the register bank, byte/halfword
semantics, burst rejection, and the **retired** `HRESP`-to-exception claim — is
tabulated in
[HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md#the-external-ahb-window-at-0x60000000--the-mcus-door-into-the-fabric).
From the fabric side, the pieces that constrain your RTL:

| Boundary feature | Status |
|---|---|
| Fabric drives all 32 `hrdata` lanes in one read | **[S]** |
| Upper-lane zero completion for exact 32-bit reads | **[S]** — each of `HRDATA7`, `HRDATA9`…`HRDATA31` closed by an individually named route branch (free `RMUX13` GND branch, one-hop `RMUX72`, free `RMUX48`, a constant-zero LUT after a scratch consumer relocation, free `RMUX20`, `X19Y9 RMUX15`, route-only from `X20Y9 RMUX69`, direct `RMUX20` fanout, route-only `RMUX08`, and a grouped route-only image for `HRDATA18,19,21–26,28–31`) |
| Fabric slave accepts a 32-lane write | **[S]** in protocol-valid **four-bit groups**, not one simultaneous capture |
| An **8-bit** writable register bank with one controlled wait | **[S]** |
| Writable state **wider than 8 bits** | **[U]** — fail-closed; needs a simultaneous wide `HWDATA` capture that both routes and encodes exactly |
| Non-`SINGLE` `HBURST` | **[S]** as a *fail-closed* boundary — all seven nonzero encodings rejected with `HRESP` and no state mutation |
| `local_int[3:0]` — four distinct sources routed simultaneously | **[S]**; state is deliberately **shared across the selected lane**, not four simultaneous pending bits |
| **Fabric AHB master** (`slave_ahb_*`) | **[U]** — no route, no qualification. Plan is read-only reserved-SRAM transactions first, then bounded writes with canaries |
| DMA sidebands `DMACBREQ`/`DMACLBREQ`/`DMACSREQ`/`DMACLSREQ` out, `DMACCLR`/`DMACTC` in | **[U]** — request/response route smokes exist; **polarity, duration and level-vs-pulse semantics uncharacterized**; no silicon handshake |
| `EXT_INT0..7` (PLIC external) | **[U]** — unconnected hypotheses |

A known coupled negative worth knowing before you compose a wide bank **[S]**:
the first writable-bank composition retained deterministic wait timing but
**corrupted lane 6**. Nine successive experiments exculpated the capture stage,
the combinational commit phase, response-release duration, the feedback-pin
placement, the Q primitive and the storage site — a raw-Q witness on `HRDATA8`
matched ordinary `HRDATA6` in all 256 cases with the same **sticky-high
127-error pattern**, localizing the failure to *stored lane-6 state* rather than
its read branch. Root cause: **the changed `HWDATA6` ingress route versus the
qualified pure-open bank was causal.** Restoring that route alone made basic
`0xa5`/`0x3c` exact but left a one-transfer lane-6 lag. These are **retained
coupled negatives, not dead-PIP claims.**

### Analog hard blocks are on this boundary, not on MCU MMIO

ADC0/1/2, DAC0/1 and CMP0 are analog hard blocks instantiated as **fabric IP**
and memory-mapped in the External-AHB window at `0x60000000` — they do not exist
until a fabric image instantiating the analog IP wrapper is configured. Their
register maps, the qualified subset, and the CMP0-unit-2 and unbonded-channel
negatives are in
[HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md#analog-adc012-dac01-cmp0--on-the-external-ahb-window-not-mcu-mmio)
and [ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md).

For placement: the vendor macro places ADC0/1/2 at `(22,7)`/`(22,8)`/`(22,9)`
and DAC0/1 at `(22,11)`/`(22,12)` — the RIGHT edge column — via `FIXED_COORD`
constraints. **[U]** (observed in one vendor-macro build; not a general rule.)
**AGaMEMnon's own bitgen does not emit the analog macro.**

The strict open flow exposes exactly three *read-only* ADC0 routes —
`AGRV2K_ADC0_DB0`, `AGRV2K_ADC0_DB1`, `AGRV2K_ADC0_EOC`, from raw route-bar
`src_sub` values 0, 1 and 12. Each gets a **private synthetic first-exit wire**
before joining the shared topology, so vendor route.tx's lossy naming (all three
nets named by the ADC cell instance, with DB0/DB1 both using a symbolic
`InputMUX01`) cannot merge the hard pins. DB0/DB1 route seven pips and map five
configurable fields, passing 49 selector checks each; EOC routes eight pips,
maps six fields, passes 59 checks; all have zero unmapped pips and two fixed
hard-boundary hops. **This is route support only** — no configuration, no
ownership arbitration, no timing, electrical or function claim, and the smoke
images **must not** be treated as board qualification images. **[R]**

---

## Provenance summary

| Fabric subsystem | Best tier | Boundary |
|---|---|---|
| LUT4/FF general RTL | **[S]** | full, including large sequential designs |
| Global clock distribution | **[S]** subset | near and far tiles, listed PLL configs only |
| PLL frequency | **[S]** | HSE = 8 MHz, SYSCLK 4–248 MHz, 43 rows |
| PLL emission encoding | **[R]** | byte-exact on a 53-point sweep; 7 profiles; others fail closed |
| PLL config chain (66 fields / 239 bits) | **[R]** names/widths, **[U]** byte positions | 5 of 66 partially validated |
| Physical outputs | **[S]** L48 subset | PIN_25–28, including concurrent |
| Physical inputs | **[S]** L48 subset | PIN_10, 11, 15, 19; PIN_19 registered |
| L48 bond map | **[S]** | exact; other packages architecture-recovered only |
| IO electrical (drive/pull/open-drain/OE) | **[R]** decode, **[U]** behaviour | dynamic OE, open-drain and bidirectional **unqualified** |
| Dedicated carry | **[S]** opt-in | same-tile chains + one 33-site corridor |
| BRAM | **[S]** bounded read at `X13Y4` | writes, other sites/modes fail closed |
| BRAM mode config | **[R]** 11 of 30 rows | 19 position-resolved only; all Port-B unvalidated |
| Routing selectors | **[R]** | 659,759 + 62,044 admitted; corpus counts, not coverage |
| Dead-edge set | **[S]** for 2, **[U]** for 12 | congestion artifact, not per-edge death |
| LUT-function plane | **[R]** decoded | 33,792 positions |
| Routing plane | **[R]** ~26 % named | ~74 % unmapped |
| Preamble (164 B) | **[R]** qualified subset | 7 byte-exact profiles; silicon narrower than the encoding set |
| Body regeneration | **[R]** 100 % byte-exact vs decoded canvas | **[U]** never booted on silicon |
| From-scratch base image | **[U]** | silicon **unqualified**, packages **none** |
| Bitstream format + CRC | **[S]** | 99,936 / 99,944, CRC-32/BZIP2 over header + body |
| Geometry transform | **[R]** | bit-exact 73,216/73,216 against the physmap formula |
| Bus clock | **[S]** | `bus_clk = sys_gck` at 10 MHz |
| MCU-AHB slave | **[S]** subset | 32-lane read, grouped write, 8-bit writable bank |
| Fabric AHB master | **[U]** | no route |
| DMA sidebands, `EXT_INT0..7` | **[U]** | uncharacterized / unconnected |
| Timing | **[R]** conservative | 542 exact pairs; not an Fmax model |
| Bidirectional node pinout | **[R]** build-supported | electrically **human-gated** |

**Tier tags in this document:** **50** occurrences of **[S]**, **67** of
**[R]**, **44** of **[U]** — counted as tag occurrences, not unique claims. The
shape matters more than the count: the fabric half is **decode-rich and
silicon-poor**. Many encodings are byte-exact or differentially validated against
the vendor back-end; comparatively few are behavioural proofs, and the two
headline decode achievements (100 % body regeneration, the 66-field PLL chain)
both carry explicit validation gaps.

---

## Open questions and known disagreements

1. **The global-clock count is not confirmed in the public tree.**
   [ARCHITECTURE.md](ARCHITECTURE.md) says only "global clocks";
   the project overview says **5**. Nothing in the public docs states a number.

2. **The 16-slices-per-LogicTile figure is arithmetic, not a quoted spec.**
   2,112 LUT4s / 132 LogicTiles = 16, and 2,112 FFs / 132 = 16, and
   2,112 × 16 LUT-INIT bits = 33,792 = the decoded LUT-plane size. Three
   independent sourced numbers agree, and observed slice indices reach
   `slice15` — but no public doc states "16 slices per tile" directly.

3. **The 860-word-line body count is arithmetic too.** `99,768 / 116 = 860 r 8`.
   The reserved-region tables reference word-lines up to 859, which is
   consistent, but the 8-byte tail at `[99924:99932]` is not separately
   documented anywhere. Its **purpose** is unstated — though its contents are
   known and reproduced:

   ```
   canvas [99924:99932] = 2a 00 fc 02 00 00 0f 8f
   ```

   The from-scratch generator emits those eight bytes **byte-identically** (they
   are inside the 99,768/99,768 body match), so nothing is blocked by not knowing
   what they mean — but they are carried, not understood. They are too short to
   be a word-line and sit between the last full word-line and the CRC, so the
   plausible readings are a trailing partial frame, a per-image footer, or
   padding. **Untested either way** — nobody has ablated them to see whether the
   FCB cares.

4. **The full `pinC` mux expression is RE-inferred.** The shipped
   micro-architecture directly evidences `modeMux = 1 → pinC = Cin` and the
   existence of a `Qin` internal path. The three-way
   `pinC = modeMux ? Cin : (FeedbackMux ? Qin : C)` form comes from
   reverse-engineering notes and is not stated in the public tree.

5. ~~**`fabric_default.bin` being FCB-rejected has not been demonstrated.**~~
   **RESOLVED [S] (2026-08-14) — it has now been demonstrated directly.** The
   stale-CRC canvas was fed straight to the FCB and rejected with
   `FCB_STAT = 0x00000040` (`STAT_ERR_CRC`), while an image with an identical
   body and a corrected CRC (`0x4B36B054`) returned `0x000f0002` and configured.
   The two images differ only in the four CRC bytes, which isolates the cause.
   See the base-image section above for the full A/B table.

6. **Chain addressing through the FCB is untested here.** `ADDR = 0x400` (IO
   chain, 27 words) and `ADDR = 0x401` (PLL chain, 8 words) come from
   behavioural RE of the FCB and are labelled "not device MMIO" in their source.
   Nothing in the public flow uses the non-auto path.

7. **The IO chain's field count and the FCB's word count are different
   quantities** and must not be reconciled: 26 decoded field rows across 7 chain
   *types* versus a 27-word (864-bit) per-device chain.

8. **`CFG_SEL_LPSRC` is ambiguous by name** — it exists in both `MIPI_TX`
   (chain bit 10) and `MIPI_RX` (chain bit 11). Always qualify by chain.

9. **The `defaults` column of the IO chain table has non-uniform arity**
   (usually two variants, but `CFG_INPUT_EN` has three). Positional
   interpretation of it is unsafe, and the file carries no confidence column at
   all.

10. **Three cross-doc staleness items.**
    (a) [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) still states "14
    isolated dead-edge classifications", superseded by
    [STATUS.md](STATUS.md) (2 admitted, 12 unverified, "isolated" retracted).
    (b) The same doc lists PLL restoration at only 10/25/50/100 MHz, omitting
    60 MHz and the 38 promoted sweep rates.
    (c) The claim-policy ledger's "Emitted features" table has only **nine**
    IDs (`bram`, `carry`, `clocks`, `core_logic`, `mcu_ahb`, `mcu_gpio`,
    `physical_io`, `route_through`, `routing`) — there is **no policy-ledger
    entry** for UART, flash, USB, DMA, CRC, watchdog, MTIME, RTC or analog, so
    their qualification lives only in STATUS.md / HARDWARE_VALIDATION.md.

11. **Statistical promotion has a hard floor and hard exclusions.** Admission
    requires ≥ **300 zero-failure trials, 10 images, 3 contexts, 3 SRAM
    load/reset cycles, and a 95 % rule-of-three upper bound ≤ 1 %** — and
    **electrical, timing, destructive and safety-sensitive domains cannot be
    promoted statistically at all.** Much of the IO-electrical surface therefore
    cannot be closed by volume; it needs individual qualification.

12. **The plane-3 partition is not bit-exact.** Which residue bits belong to IO
    versus BRAM versus hard-block config is explicitly "a working partition",
    and the per-bit resource assignment of the unnamed ~74 % of the routing
    plane awaits the crossbar-table promotion.

---

## Cross-references

| For | See |
|---|---|
| The RISC-V MCU half, and every register the firmware touches | [HAL_MCU_REFERENCE.md](HAL_MCU_REFERENCE.md) |
| Authoritative qualification state | [STATUS.md](STATUS.md) |
| The three-plane config partition | [CONFIG_SURFACE_MAP.md](CONFIG_SURFACE_MAP.md) |
| Canvas decode, regeneration progress, and the retirement gate | [FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md) |
| Image format detail | [BITSTREAM_FORMAT.md](BITSTREAM_FORMAT.md) |
| Toolchain structure: synth, chipdb, placer, router, bitgen | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Per-feature parity/evidence tiers | [FPGA_PARITY_LEDGER.md](FPGA_PARITY_LEDGER.md), [CLAIM_POLICY_LEDGER.md](CLAIM_POLICY_LEDGER.md) |
| The conduction reframe in full | [CONDUCTION_REFRAME_STATUS.md](CONDUCTION_REFRAME_STATUS.md), [AF_EXE_REVERSE_ENGINEERING.md](AF_EXE_REVERSE_ENGINEERING.md) |
| MCU-edge boundary contract and the wide-transfer path | [MCU_AHB_INTERFACE.md](MCU_AHB_INTERFACE.md), [MCU_FABRIC_ROADMAP.md](MCU_FABRIC_ROADMAP.md) |
| Pin/alt-function policy and how to qualify a new route | [MCU_PIN_ROUTING.md](MCU_PIN_ROUTING.md) |
| Clock domains, and why there is no MCU clock-switch API | [MCU_CLOCKS.md](MCU_CLOCKS.md) |
| Flash/boot of a fabric image | [flashboot/FLASH_LAYOUT.md](flashboot/FLASH_LAYOUT.md) |
| Ranked gaps to full vendor parity | [DOES_EVERYTHING_ROADMAP.md](DOES_EVERYTHING_ROADMAP.md) |
| Bench identity and the qualification rulebook | [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) |
