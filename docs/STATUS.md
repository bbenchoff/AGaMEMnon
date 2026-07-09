# AGaMEMnon — Status

An honest, detailed accounting of what is finished versus what remains. This is the granular companion to the README's "What runs on silicon" section.

The open loop is complete and proven end-to-end on silicon. `agamemnon build design.v -o design.bin` runs synthesis, place, route, and bitstream generation entirely from the self-contained package (yosys → nextpnr-generic → open bitgen), and an open bitstream has configured the fabric and booted itself from flash on a real AG32, with no vendor binary in the path and no debugger in the config loop. What remains is coverage, breadth, and polish — not reverse engineering, and not any single make-or-break unknown.

## Done — validated byte-for-byte against `af.exe` and/or on real silicon

| Capability | What it covers | Validation |
|---|---|---|
| **Arch-DB codec** | The reversible polyalphabetic codec for the arch DB + `.tx` place/route intermediates | 100/100 vendor `*_cfg.csv` round-trip byte-exact |
| **Semantic feature DB** | `(block, word-line, bit-line) → CFG feature` — 110,188 cells, 14,463 features, 28 blocks | Families cross-validated against the independently enumerated physical map |
| **`.bin` LZW codec** | `.bin` ↔ fixed 99,936-byte raw image, both directions | Byte-exact vs `af.exe` on every test bitstream, and on unseen on-silicon flash bytes |
| **Fabric-config CRC** | CRC-32/BZIP2 over `header(8) + raw[:99932]`, big-endian, in the last word | Recovered *on silicon* (a wrong value returns `FCB STAT` `ERR_CRC`); baked into bitgen |
| **Full physical map** | bit → tile(X,Y) + CFG feature + word-line/bit-line — 554,800 bits, 213 tiles, all routing muxes | Family/name cross-validation vs the semantic DB |
| **Pos↔raw transform** | feature `(top_wl, top_bl)` → raw `byte.bit` (rank model) | 100% on a 1-LUT diff; LUT-init validated bit-exact on full designs |
| **Open bitgen** | routed design → `.bin` (LUT + routing + clock + CRC), no vendor binary | All per-tile feature bits reconstructed with 0 errors; FCB-accepted on silicon (`STAT=0x000f0002`) |
| **Open LUT edit** | rewrite a LUT truth table in a `.bin` | Byte-exact vs `af.exe`; flashed, read back (exactly 1 raw byte changed), restored |
| **nextpnr-generic place & route** | `arch.py` builds the real AGRV2K arch (wires/pips/bels + MCU-edge/IO/clock) for `nextpnr-generic` | Packs, places, and routes combinational, sequential, and MCU-instance designs on the genuine topology |
| **Combinational logic on silicon** | a fabric LUT computes | inverter: `din=0→dout=1`, `din=1→dout=0` |
| **Sequential logic on silicon** | a clocked flip-flop toggles | toggle-FF flips on each clock; register-select (CFG_OMUX sel=2) solved |
| **General clock distribution** | route clock nets to arbitrary tiles, including far ones | FFs clock at scattered + far tiles; per-tile clock config data-complete for all 132 LogicTiles |
| **Far-tile MCU-dout readback** | a genuinely-far FF drives an MCU-dout exit RMUX back to GPIO | Silicon-proven on **3 of 4** dout bits (GPIO4 bits 0/2/4) via a per-exit **live-feeder whitelist** (`chipdb/exit_feeder_whitelist.csv`); the 4th exit (`RMUX02`/bit 6) is local-only. The whitelist is *not* from a vendor file — the far/exit tail was closed on real silicon |
| **Device / package awareness** | select 1 of 4 QFN packages (L100/L64/L48/Q32); front-end pin-NUMBER legality gate | Per-package legal-pin sets transcribed from vendor `CHIP_INFO` (`engine/device.py`); rejects a design declaring an unbonded `PIN_n`; default AGRV2KL48 via `AGAMEMNON_DEVICE`. Per-package *physical* pad pruning is a documented follow-up (needs the `PIN_n→IOTILE` bond map from `af.exe`) |
| **MCU ↔ fabric GPIO** | 4 independent MCU GPIO bits looped through fabric LUT inverters, auto-placed | all 4 invert on silicon, 16/16 input combinations |
| **Ring-pad output** | a fabric FF drives a real external header pin (not just the MCU-readback exit) | **silicon**: a toggle-FF drives `PIN_18` (top-row pad (18,13)z0) — the pin toggles on a logic analyzer. The recovered per-pad feeder-hop + source-select are shipped (`chipdb/iomux_hop_vendor.csv`); the left-edge LED-pad source-select is route-driven in bitgen. As with the far exit, most enumerated pad-feed edges config-accept but are dead on silicon — the working chain uses only proven feeders |
| **MCU AHB write → a pin (CPU-controlled blink)** | the MCU writes a fabric register over the External-AHB bus, and that register drives a header pin | `*(u32*)0x60000000 = v` → fabric register → GPIO readback, on silicon; and routed onto `PIN_18`, so firmware writing 0/1 in a loop **blinks the pin** (~1.25 Hz) — a CPU-controlled output end-to-end through the open flow (`examples/designs/ahb_pad.v` + `examples/firmware/ahb_blink.c`) |
| **Flash-boot** | an open bitstream self-boots from flash | compressed open config in flash → boot ROM configures fabric → after a physical power-cycle the loopback runs, no debugger in the config loop |
| **Self-contained toolchain** | the `agamemnon` package + shipped chipdb + `build`/`pack`/`unpack` + `probe`/`sram`/`backup`/`flash`/`image` CLI | `agamemnon build` produces a valid 99,944-byte image; a `pytest` regression proves the bitgen is byte-exact |
| **Open flasher** | erase → program → byte-verify to flash by driving the `0x40001000` controller directly (no vendor `agrv` driver) | full backup → write → verify on a real board; the fabric self-boots after a power-cycle |

## V0.2 additions (2026-07-05) — real registered feedback, dense packing, BRAM config

This drop closes the "sequential logic is real, not just a toggling output" question and adds BRAM config.
All verified via the MCU **AHB value-read** path (`0x60000000` = the fabric register value) — an
ambiguity-free readout that reads the *actual computed value*, not just "a bit toggles."

| Capability | What it covers | Validation |
|---|---|---|
| **Registered feedback (internal `Qin`)** | `reg <= reg ^ x` — a slice's FF-Q feeds its own LUT via the internal `FeedbackMux` (`pinC = FeedbackMux?Qin:C`), NOT a routed net. `engine/qin_pack.py` permutes self-feedback to the C input (index 2); bitgen emits `CFG_LUTCMUX[2z]` (from `chipdb/slice_cfg.csv`) | Byte-exact vs an `af.exe` oracle; small designs read correct values on silicon |
| **Sequential compute on silicon (positive proof)** | auto-placed 2–8-bit counters, shift register, small FSM, ripple adder, LUT-decode→FF — all read their **actual value** over AHB | distinct-value readout matches the routed-netlist simulation (SOUND: observed ⊆ sim, no spurious value; several with full/high coverage e.g. adder reads all of {0..7}) |
| **Dense intra-tile packing** | multiple sequential cells in ONE tile with cell-to-cell reads (the earlier "must spread 1/tile" constraint was a harness artifact) | packed accumulator + packed Johnson read correct on silicon |
| **Inter-tile carry** | `bit_k → bit_{k+1}` on the conducting RMUX mesh | counters count on silicon |
| **BRAM config emission** | `alta_bram9k` INIT_VAL / port-width / clkmode / port-enables → `.bin` (`engine/bram_emit.py` + `pips_bram_pll.csv`) | byte-exact vs `af.exe` BRAM oracles (config only) |
| **BRAM bel + routing + `$mem` techmap** | placeable `ALTA_BRAM9K` bel + BramTILE↔fabric routing edges + `$mem`→`ALTA_BRAM9K` yosys techmap (inferred `reg[] mem` → BRAM) | **silicon**: inferred ROM reads its real contents over AHB (distinct=8, 3-bit dynamic address); nextpnr places + routes the BRAM, bitgen byte-exact |
| **Faithful-graph data** | decoded tile template sel resolver (`engine/mesh_template.py` byte-exact sels), silicon conduction map (`chipdb/master_conduction.csv`, 2650 edges) | resolver byte-exact vs vendor; conduction map is silicon-measured |

## V0.3 progress (2026-07-08) — wider readout, dense compute to 16 bits, BRAM read, and the arch decision

| Capability | What it covers | Validation |
|---|---|---|
| **Multi-lane AHB readback** | the fabric→MCU read funnel (BBMUXE) is a clean 4×3=12-input mux, corpus-harvested (`chipdb/bbmuxe_fanin.csv`); 12 distinct feeder RMUXes wired in | **silicon**: 9 of 10 read lanes conduct simultaneously (was 4); read-position map verified per lane |
| **Dense compute to 16 bits** | a single dense structure (16-bit counter, 20 cells across 3 tiles) computes through intra-tile conducting pairs + inter-tile carry | **silicon**: all taps including the deepest `d[15]` sweep (distinct=16) |
| **Native placement (hook-free)** | nextpnr-generic's own placer packs a dense counter on the conduction-pruned arch, no pre-place hook | **silicon**: 4-bit counter, nextpnr-packed, reads distinct=16 |
| **`$mem`→BRAM read path** | inferred `reg[] mem` → `ALTA_BRAM9K` → placed/routed → reads real ROM contents | **silicon**: distinct=8, 3-bit dynamic address |

**The one open frontier — dense packing at scale.** Everything above is proven; the remaining piece is
packing a large, richly-connected core (SERV-scale, ~1800 cells) rather than a single dense structure. The
current `arch.py` pre-pack + hand-placement hooks are a bootstrap scaffold; native placement works small but
lacks the arch-specific packing-validity (`isBelLocationValid`) and clustering that dense scale needs. **The
solution is our own nextpnr microarchitecture, `agrv2k`** — a Viaduct uarch (`agamemnon/engine/uarch/agrv2k/`)
that holds those rules in the placer while reusing this repo's chipdb + bitgen unchanged. It is **built and
loads the full device** (50,047 wires, 326,760 pips, emitted by `emit_uarch_db.py`); the staged bring-up onto
silicon — (1) a trivial design end-to-end, (2) native dense packing via `isBelLocationValid`, (3) the pivotal
exit-reachability predicate — is in progress. The chip database and bitstream layer are backend-agnostic and
transfer 1:1; only the place/route frontend changes, so the silicon-proven results above are unaffected.

Two smaller items remain scoped, not shipped:
- **Deep dense arithmetic via the dedicated `Cin/Cout` carry chain** — the shipped path uses routed
  inter-tile carry (silicon to 16 bits). The slice's dedicated hardware carry is confirmed functional on
  silicon; emitting it through the open flow is a routing-resource-sharing detail, not an unknown.
- **Deterministic wide-design verification** — the polled AHB read aliases beyond ~256-period designs;
  SOUND (⊆ routed-netlist sim) is the guarantee. A clock-gated single-step readout is scoped.
- **Verification rule:** treat a design as "computes" only on distinct-value > 2 with coverage — never on
  SOUND alone (a static design passes SOUND).

## Remaining — coverage, breadth, and polish (no reverse engineering)

| Item | State | Note |
|---|---|---|
| **Routing byte-exactness** | ~99%, FP=0 | The router never emits *wrong* config bits (false-positive rate zero). The residual ~1% is *under-coverage*: a handful of dense intra-tile IMUX/OMUX crossbar pips lack an exact byte-formula (bitgen falls back to an approximate sel, ~98% likely correct, or leaves the net unmapped), and some far/long routes are missing real adjacencies. The MCU-edge far/exit-feeder tail specifically is **closed on 3 of 4 dout bits** via a silicon-validated per-exit live-feeder whitelist (`chipdb/exit_feeder_whitelist.csv`; the 4th exit, `RMUX02`/bit 6, is local-only). Small and medium designs are reliable; the tail is a corpus + closed-form grind, not an unknown. |
| **Timing model (`agamemnon time`)** | not built | We have the vendor delay tables in the arch DB, but a timing-driven placer/router (Fmax closure) is a substantial piece. Today the flow optimizes for *function*, not *frequency*. This is the honest frontier. |
| **Wide hard-block bels** | emitters cracked, integration pending | The IO ring, all four BRAM ports, and arbitrary PLL clocks are reverse-engineered and reproduce vendor output byte-exact (`io_emit`/`pll_emit`/`bram_emit`); what remains is general nextpnr-generic bel coverage, not RE. |
| **Wider MCU bus** | read + write silicon-proven; full 32-bit-in-one-shot remaining | The `hrdata` read path is silicon-proven and widened to a multi-lane readback (9 of 10 lanes at once); the write path is silicon-proven. Assembling a full 32-bit transfer in a single access is the remaining step — more of the same, no unknowns. |
| **`.agasc` ASCII hub** | design | An `icebox`-style human-readable per-tile config text, to make the bitstream self-documenting and to feed `time`/`bram`/`vlog` utilities. Today the P&R intermediate is the routed nextpnr JSON. |
| **Alternate flash transports** | probe-based flashing done; DFU pending | The open flasher (SWD via a CMSIS-DAP probe) is silicon-proven and in-repo, alongside the RISC-V MCU SDK (`mcu/`). What's left is probe-less transports: UART bootloader and native-USB DFU, so a bitstream can be loaded without a debugger. |

## Honest caveats

- Routing is byte-exact ~99% with a false-positive rate of zero. That distinction matters: an incorrect prediction would silently corrupt a net, but the encoder is built to emit only what it can prove, so the failure mode is a *dropped/approximated* pip, not a *wrong* one. Closing the last percent is coverage work (more observed-real routing corpus, more closed-form sel rules).
- Timing optimization is the fuzzy frontier. Feature parity for *functionality* is here; parity for *timing closure* (what Quartus does) is a further, larger effort we have not built.
- This is debug-probe + differential reverse engineering, not decap. We do not and cannot recover analog blocks (PLL VCO internals, RC-oscillator trim), hard-block gate-level RTL, or anything the config bitstream does not expose. Complete RE of the *fabric configuration and toolchain* is the achievable goal, and it is done; complete RE of the *silicon* is a different, microscopy-scale project we are explicitly not doing.
- Un-exercised corners stay honest-unknown until a design drives them. Each is crackable the same way, but each needs its exercising design or oracle.

## Bottom line

The reverse engineering is finished and the open toolchain is real: Verilog compiles to a flashable bitstream, the bitstream configures the fabric, the configured logic computes and clocks, the MCU and fabric exchange data (read and write), and the whole thing boots from flash — all through open code, validated on silicon. The one substantial piece ahead is packing density at scale: a dedicated nextpnr arch for the fabric so the placer holds the fabric's packing rules and large soft cores (SERV-scale) route natively. The rest is polish — timing, probe-less UART/USB-DFU transports, the ASCII hub. None of it is reverse engineering; the hard part — opening the chip — is done.
