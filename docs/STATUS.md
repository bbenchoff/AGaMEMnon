# AGaMEMnon — Status

An honest, detailed accounting of what is finished versus what remains. This is the granular companion to the README's Coverage and Roadmap sections.

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
| **MCU AHB memory-bus write** | the MCU writes a fabric register over the External-AHB bus | `*(u32*)0x60000000 = v` → fabric register → GPIO readback, on silicon |
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
| **BRAM routing + pinmap (data)** | BramTILE↔fabric routing edges (`chipdb/bram9k_edges.csv`) + single-port pin→wire map (`chipdb/bram9k_pinmap.csv`) | harvested from vendor routes; **bel + techmap not yet wired** (see Remaining) |
| **Faithful-graph data** | decoded tile template sel resolver (`engine/mesh_template.py` byte-exact sels), silicon conduction map (`chipdb/master_conduction.csv`, 2650 edges) | resolver byte-exact vs vendor; conduction map is silicon-measured |

**Honest scope of V0.2:** every sequential result above is a **small, auto-placed** design verified within
the AHB-read observability window. The following are explicitly **not** done and are the V0.3 targets:
- **General dense-packing flow at scale** — the current results use spread/minimal-dense placement; a real
  large design (e.g. SERV, ~1300+ FFs) needs the general packing flow, not yet built.
- **Deep dense arithmetic via the dedicated hardware carry chain** — the shipped sequential path uses
  routed inter-tile carry (proven to ~6–8 bits). The slice's dedicated intra-tile `Cin/Cout` carry (for
  deeper/denser arithmetic) is a separate mechanism: the hardware itself is confirmed functional on
  silicon, but emitting it through the open flow is blocked on a routing-resource conflict (the carry
  slices' `vcc`/input routing shares the tile resources the readout also needs). Scoped, not shipped.
- **Airtight wide-design verification** — the polled AHB read aliases beyond ~256-period designs; SOUND
  (⊆ routed-netlist sim) is the guarantee, distinct-value coverage is supporting. A deterministic
  (clock-gated single-step) readout is scoped but not built.
- **BRAM bel + `$mem`→`alta_bram9k` techmap** — only config + routing/pinmap *data* are done.
- **Verification rule:** treat a design as "computes" only on distinct-value > 2 with coverage — never on
  SOUND alone (a static design passes SOUND).

## Remaining — coverage, breadth, and polish (no reverse engineering)

| Item | State | Note |
|---|---|---|
| **Routing byte-exactness** | ~99%, FP=0 | The router never emits *wrong* config bits (false-positive rate zero). The residual ~1% is *under-coverage*: a handful of dense intra-tile IMUX/OMUX crossbar pips lack an exact byte-formula (bitgen falls back to an approximate sel, ~98% likely correct, or leaves the net unmapped), and some far/long routes are missing real adjacencies. The MCU-edge far/exit-feeder tail specifically is **closed on 3 of 4 dout bits** via a silicon-validated per-exit live-feeder whitelist (`chipdb/exit_feeder_whitelist.csv`; the 4th exit, `RMUX02`/bit 6, is local-only). Small and medium designs are reliable; the tail is a corpus + closed-form grind, not an unknown. |
| **Timing model (`agamemnon time`)** | not built | We have the vendor delay tables in the arch DB, but a timing-driven placer/router (Fmax closure) is a substantial piece. Today the flow optimizes for *function*, not *frequency*. This is the honest frontier. |
| **Wide hard-block bels** | emitters cracked, integration pending | The IO ring, all four BRAM ports, and arbitrary PLL clocks are reverse-engineered and reproduce vendor output byte-exact (`io_emit`/`pll_emit`/`bram_emit`); what remains is general nextpnr-generic bel coverage, not RE. |
| **Wider MCU bus** | write path proven; read + width remaining | 32-bit AHB and the `hrdata` read path (MCU reads a fabric register back over the bus). The 1-bit write path is silicon-proven; the read exit and the widening are next. |
| **`.agasc` ASCII hub** | design | An `icebox`-style human-readable per-tile config text, to make the bitstream self-documenting and to feed `time`/`bram`/`vlog` utilities. Today the P&R intermediate is the routed nextpnr JSON. |
| **Alternate flash transports** | probe-based flashing done; DFU pending | The open flasher (SWD via a CMSIS-DAP probe) is silicon-proven and in-repo, alongside the RISC-V MCU SDK (`mcu/`). What's left is probe-less transports: UART bootloader and native-USB DFU, so a bitstream can be loaded without a debugger. |

## Honest caveats

- Routing is byte-exact ~99% with a false-positive rate of zero. That distinction matters: an incorrect prediction would silently corrupt a net, but the encoder is built to emit only what it can prove, so the failure mode is a *dropped/approximated* pip, not a *wrong* one. Closing the last percent is coverage work (more observed-real routing corpus, more closed-form sel rules).
- Timing optimization is the fuzzy frontier. Feature parity for *functionality* is here; parity for *timing closure* (what Quartus does) is a further, larger effort we have not built.
- This is debug-probe + differential reverse engineering, not decap. We do not and cannot recover analog blocks (PLL VCO internals, RC-oscillator trim), hard-block gate-level RTL, or anything the config bitstream does not expose. Complete RE of the *fabric configuration and toolchain* is the achievable goal, and it is done; complete RE of the *silicon* is a different, microscopy-scale project we are explicitly not doing.
- Un-exercised corners stay honest-unknown until a design drives them. Each is crackable the same way, but each needs its exercising design or oracle.

## Bottom line

The reverse engineering is finished and the open toolchain is real: Verilog compiles to a flashable bitstream, the bitstream configures the fabric, the configured logic computes and clocks, the MCU and fabric exchange data, and the whole thing boots from flash — all through open code, validated on silicon. The work ahead is making it *general and robust* (close the routing tail, add timing, widen bels and the MCU bus) and adding reach (probe-less UART/USB-DFU transports, the ASCII hub). None of it is reverse engineering; the hard part — opening the chip — is done.
