# AGaMEMnon — Status

An honest, detailed accounting of what is finished versus what remains. This is the granular companion to the README's "What runs on silicon" section.

The open loop is proven end-to-end on silicon for the qualified subset. `agamemnon build design.v -o design.bin` runs synthesis, place, route, and bitstream generation without a vendor binary (yosys → nextpnr-generic → open bitgen), and open images configure, compute, and boot on real AG32 hardware. General routing qualification, timing closure, wider hard-block modes, and comprehensive hardware regression remain before this can be called vendor-parity.

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
| **Combinational logic on silicon** | arbitrary synthesized LUT logic with physical L48 inputs/outputs | `o=(a&b)\|(c^d)` on PIN10/PIN11/PIN15/PIN19 → PIN16, exhaustive **16/16** vectors; two-input AND **4/4**; stock yosys + nextpnr + open bitgen, zero post-build patching |
| **Multi-LUT physical placement/routing** | a preserved three-LUT dependency cone with two LUT→LUT links | Default `build --pcf` clusters the cone at X19Y12 on even slices 0/2/4; real RMUX-mediated inter-LUT routing, **29/29 mapped pips**, exhaustive **16/16** silicon vectors for `(a^b)&(c^d)`. No placement override or post-build patching |
| **Sequential logic on silicon** | a clocked flip-flop toggles | toggle-FF flips on each clock; register-select (CFG_OMUX sel=2) solved |
| **General clock distribution** | route clock nets to arbitrary tiles, including far ones | FFs clock at scattered + far tiles; per-tile clock config data-complete for all 132 LogicTiles |
| **Far-tile MCU-dout readback** | a genuinely-far FF drives an MCU-dout exit RMUX back to GPIO | Silicon-proven on **3 of 4** dout bits (GPIO4 bits 0/2/4) via a per-exit **live-feeder whitelist** (`chipdb/exit_feeder_whitelist.csv`); the 4th exit (`RMUX02`/bit 6) is local-only. The whitelist is *not* from a vendor file — the far/exit tail was closed on real silicon |
| **Device / package awareness** | select 1 of 4 QFN packages (L100/L64/L48/Q32); physical PCF for L48 | Per-package legal-pin gate plus recovered L48 PIN→pad bond map. `--pcf` binds real IPAD/OPAD bels; characterized physical inputs are PIN10/11/15/19 and the proven output is PIN16. Uncharacterized physical inputs fail closed rather than emitting a static design |
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

**SERV-scale placement is now operational.** The `agrv2k` Viaduct uarch has a bounded regional placer,
hard-BRAM pin packing, physical-I/O pin packing, handshake clustering, linear fanout trees, and router2
escalation. The hard-BRAM SERV probe packs to 349 slices + 161 FFs + one 512x2 BRAM, routes 4,127 data PIPs,
and executes an `addi/sw/xori/jal` loop on silicon. Its direct `mem_dat[0]` output is low during reset, toggles
at two independent logic-analyzer sample cadences while running, and returns low when reset is reasserted.

The remaining frontier is **global routing-map completeness**, not placer scale. The strict database still
contains inferred edge families that route but do not conduct in every large design. `build --uarch
--qualified-checkpoint` closes that gap reproducibly for a hardware-qualified design: it replays the packed
placement and lets nextpnr route using only PIPs from the known-running checkpoint. For SERV this regenerates
the running 99,944-byte image byte-for-byte. Each additional qualified checkpoint expands the known-live
coverage; unrestricted large-design rerouting remains pending until those sets cover the whole fabric.

Two smaller items remain scoped, not shipped:
- **Deep dense arithmetic via the dedicated `Cin/Cout` carry chain** — the shipped path uses routed
  inter-tile carry (silicon to 16 bits). The slice's dedicated hardware carry is confirmed functional on
  silicon; emitting it through the open flow is a routing-resource-sharing detail, not an unknown.
- **Deterministic wide-design verification** — the polled AHB read aliases beyond ~256-period designs;
  SOUND (⊆ routed-netlist sim) is the guarantee. A clock-gated single-step readout is scoped.
- **Verification rule:** treat a design as "computes" only on distinct-value > 2 with coverage — never on
  SOUND alone (a static design passes SOUND).

## V0.3 close (2026-07-11) — open conduction-aware P&R promoted; fabric-input frontier characterized

This drop hardened the open place-and-route path, closed the reproducibility/regression items, and then
characterized the one remaining IO gap — reading an external pin *into* the fabric.

**Promoted / done:**

| Capability | What it covers | State |
|---|---|---|
| **Open conduction-aware P&R recipe** | The harvest campaign (`harvest_sweep`) turns every SOFT design that conducts on silicon into proven routing edges; `arch.py` folds `master_conduction ∪ ff2_conduction ∪ harvest_conduction ∪ corpus_conduction`. `place_auto` gained conduction-aware clustering (`AGAMEMNON_CLUSTER_ORDER` — BFS the cell graph so connected cells co-tile) and even-slot packing (`AGAMEMNON_EVENSLOT` — `z = 2·local`, so even→even crossbar hops conduct) | Hard-gated 2-tile / 16-cell designs route **and conduct on silicon**; recipe scales with corpus density |
| **De-hardcoded fabric coordinates** | MCU edge (`AGAMEMNON_MCU_XY`), exit tile (`AGRV2K_EXIT_TILE`), carry tile, and global-clock count (`AGAMEMNON_NGCLK`) are named + env-overridable, not scattered magic numbers | Defaults byte-identical to before |
| **HW-carry techmap in synth** | `AGAMEMNON_HW_CARRY` lowers `$alu` to a ripple of `AG32_FA` blackboxes riding the slice's dedicated Cin/Cout, before abc shreds `+` | Default **OFF** → the proven spread-carry path is byte-for-byte unchanged (regression covers the default) |
| **Reproducible external toolchain** | `uarch/agrv2k/build.sh` pins the nextpnr commit and fetches/checks out that exact SHA | Build reproducible from a clean checkout |
| **Broadened regression** | `tests/test_build_e2e.py` runs Verilog→`.bin` through the CLI (skips cleanly when yosys/nextpnr are absent) | Full `pytest` suite green |
| **BRAM `$mem` read** | re-verified end-to-end | **silicon**: distinct = 8 |

**The open frontier — reading an external pin INTO the fabric (fabric IO input).** Fabric *output* is
silicon-proven (a fabric FF drives a real header pin). The mirror — an external pin driving a fabric
register — is **not yet proven on silicon**, and this session pinned down why:

- **The input structure is decoded.** Each IOTILE's bonded pad drives a per-pad input register
  `alta_ioreg<z>` (`z` = the pad's iomux index), which feeds a *specific* `InputMUX`, which feeds the RMUX
  routing mesh. So a physical pin enters the fabric through exactly one InputMUX; routing from any other
  InputMUX on that tile is simply not connected to the pin. (E.g. header pin GP9 = pad (17,13)z3 →
  `alta_ioreg03` → `InputMUX07`.)
- **The bonded pads' input paths are sparse and circuitous** in the conduction/observed model recovered from
  silicon. `InputMUX07` above reaches even the *adjacent* tile's logic only via a detour four tiles away
  (down to y=8 and back) — which exceeds nextpnr's per-net bounding box, so the input hop fails to route
  unless the consuming FF is deliberately placed on the detour path.
- **A pad→pad loopback test is built and staged** (external pin → fabric FF → a *proven* output pad, with a
  matched self-toggle control on the identical output path) but not yet run on silicon. Whether the sparse
  input path also *conducts* is the open question.
- The input-side routing was never exercised by the vendor design corpus, so it is under-modeled. This is
  the one item most likely to want **vendor documentation** (the IO-cell input-configuration bits and the
  input-side routing graph) rather than more differential reverse engineering.

## V0.4 (2026-07-12) — fabric IO INPUT solved on silicon, open flow

The V0.3-close frontier fell. An external pin now drives fabric logic **through the open flow**,
silicon-proven: a combinational pad→pad loopback (`PIN_19` in → fabric mesh → `PIN_16` out) tracks the
driven pin 1:1, built end-to-end by `yosys → nextpnr-generic → open bitgen` with zero hand-patched bytes.

What was actually wrong (all three fixed in this drop):

| Fix | Detail |
|---|---|
| **RRG input-entry edges** | The perimeter `InputMUX→RMUX` entry edges in `rrg_edges_full.csv` for pad (17,13) were mis-derived (`InputMUX07→RMUX67`); the real edges — recovered by differential decode of a purpose-built pad-input reference design, the first to ever exercise a ring-pad input — are `InputMUX06→RMUX71@(17,12)` and `InputMUX07→RMUX61@(17,12)`. Appended as `observed`. The "sparse/circuitous detour" model of V0.3-close was an artifact of the bad edges (plus a router-breaking soft-penalty setting) and is obsolete. |
| **Pad-feed z-map** | `padfeed_L48_top.csv` had the (19,13) z0↔z3 feeds swapped (z0 is really `RMUX08 ← RMUX55@(19,12)`); why generic pad-toggle attempts at that tile were dead on silicon. |
| **Global pad-input enable** | The single missing config: preamble `raw[97] \|= 0x40`. Isolated by automated on-silicon byte bisection between a route-identical open image (stuck) and the known-good reference (tracks) — it converged to this one byte. No open design had ever read a pad, so it was never emitted; **bitgen now emits it automatically** whenever a routed pip has a perimeter-IOTILE `InputMUX` source. Caveat: proven for the (17,13) top-row pad; the preamble region shows a repeating per-bank pattern, so other IO banks/sides may need sibling bits (extend with per-side silicon validation). |

Also established: the pad input buffer is **default-on** (all `CFG_IN_*` at power-on defaults in the
working reference), the input selection rides the ordinary RMUX source-select the general resolver
already emits byte-exact, and pad-input conduction is *input-specific* — the enable does not revive
unrelated dead exits, so it is not a general conduction switch.

Still open on the input side: a **registered** input (pad → fabric FF) through the open flow — the
FF-branch IMUX fan-out (`RMUX71` reaches only odd IMUX indices, i.e. slice pins B/D) needs the packed
D-input permuted to I[3] and a conducting Q-exit from the input-adjacent tiles; the comb proof plus the
proven-tile readout make this engineering, not an unknown.

## Remaining — qualification, coverage, and integration

| Item | State | Note |
|---|---|---|
| **Trustworthy arbitrary routing** | qualification in progress | Exact config-bit encoding is not the same as a fully qualified electrical adjacency graph. Legacy campaigns promoted unsensitized branches and contradicted 14 silicon-dead edges. Negative evidence now has absolute precedence, and new evidence records only a sensitized source-to-observed-sink path. Unrestricted large routing is not closed until randomized placements and SERV-scale designs repeatedly pass hardware regression without a checkpoint. |
| **Fabric IO input** | **combinational input plus one registered path silicon-proven** | L48 PIN19 now drives a packed FF through `InputMUX07 -> RMUX61 -> RMUX71 -> IMUX03`; a Pico low/high/low test observed 0/200, 200/200, and 0/200 asserted samples at PIN16. Other pins, banks, and packages remain unqualified. |
| **Timing model (`agamemnon time`)** | not built | We have the vendor delay tables in the arch DB, but a timing-driven placer/router (Fmax closure) is a substantial piece. Today the flow optimizes for *function*, not *frequency*. This is the honest frontier. |
| **Wide hard-block bels** | narrow modes proven; general integration pending | The golden flow currently represents one BRAM tile/Port A and a small fixed set of PLL CLKOUT0 ratios. Port B, the other BRAM tiles, independent clocks/control modes, additional PLL outputs, phase/duty/bypass modes, and general nextpnr bel integration remain. |
| **Wider MCU bus** | narrow read + write silicon-proven; full 32-bit transfer remaining | The present graph exposes ten fabric-to-MCU exits and three MCU-to-fabric entries. Exact walking-one, walking-zero, and pseudorandom 32-bit round trips are still required before the bus is complete. |
| **`.agasc` ASCII hub** | design | An `icebox`-style human-readable per-tile config text, to make the bitstream self-documenting and to feed `time`/`bram`/`vlog` utilities. Today the P&R intermediate is the routed nextpnr JSON. |
| **Alternate flash transports** | probe-based flashing done; DFU pending | The open flasher (SWD via a CMSIS-DAP probe) is silicon-proven and in-repo, alongside the RISC-V MCU SDK (`mcu/`). What's left is probe-less transports: UART bootloader and native-USB DFU, so a bitstream can be loaded without a debugger. |

## Honest caveats

- Routing success and config acceptance do not prove electrical conduction. The conservative graph must come from isolated silicon evidence, with negative evidence overriding vendor-mined or whole-design inferences.
- Functional feature parity is not yet complete, and no timing-driven Fmax closure exists. Both are active engineering frontiers.
- This is debug-probe + differential reverse engineering, not decap. Analog internals and hard-block gate-level RTL are outside scope; complete recovery of the digital configuration/toolchain behavior exposed by the bitstream remains the achievable target.
- Un-exercised corners stay honest-unknown until a design drives them. Each is crackable the same way, but each needs its exercising design or oracle.

## Bottom line

The open flow is real and silicon-proven for a useful subset, including a hardware-running SERV checkpoint. It is not yet an IceStorm-class, vendor-parity toolchain. The remaining work is measurable: finish the conservative routing graph, remove the checkpoint from large builds, add real timing and closure, generalize IO/BRAM/PLL/carry/MCU support, and continuously prove those claims on hardware.
