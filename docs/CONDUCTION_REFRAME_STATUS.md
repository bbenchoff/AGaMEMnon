# Conduction reframe — live status

Live progress log for the investigation into whether the AG32's catalogued
"silicon-dead" routing edges are genuinely dead or an artifact of our own
characterization method. Newest entry on top. This is a research log, honestly
caveated; the authoritative support ledger remains [STATUS.md](STATUS.md), and
the narrative is [AF_EXE_REVERSE_ENGINEERING.md](AF_EXE_REVERSE_ENGINEERING.md).

Confidence discipline: this line has produced confident-but-wrong conclusions in
*both* directions already, so nothing here is promoted to STATUS.md or acted on
in the shipped router until it is board-verified with a valid control.

**Update 2026-08-18 (T26): the constant-slave claim is RESTORED via a pinned
checkpoint, but the underlying defect is only partially isolated.** See the T26
log entry below for the full account. In short: the fresh-build regression T22–
T24 found (below) was real, but its root cause is NOT the single wrong table
entry it first looked like. `qualification/mcu_ahb_constant_slave_routed.json`
is now pinned to the 2026-08-02 (f705d28) routed netlist, re-confirmed reading
`0x4147414d` on the L48 reference board this session — cite the claim for that
pinned artifact. A fresh `agamemnon build --uarch` of this exact design is
**not** currently guaranteed to reproduce it, because nextpnr's route choice
has drifted (from chipdb/table growth, not seed) into at least one confirmed,
still-open encoding defect (an `X14Y8` RMUX→IMUX→RMUX detour) plus one
unisolated cross-net interaction. Distinct from, and does not affect, the
per-edge conduction headline immediately below.

## Current headline (2026-08-13, updated)

**The mechanism is now board-pinned, and it is CONGESTION-context, not the edge
and not even the forcing.** For `RMUX21@(14,10)->RMUX87@(14,8)`, a catalogued
"silicon-dead" edge, the signal **CONDUCTS** in every clean/isolated build we can
read:
- af.exe-native routing through it (deadwit_675, GPIO4.0 toggles);
- our own nextpnr routing it *naturally* (relay control, GPIO4.2 toggles);
- our own nextpnr **forced** through the exact pip via edge-blacklist
  (route-verified: `OMUX02->RMUX21@(14,10)->RMUX87@(14,8)->...->exit`; GPIO4.2
  toggles), all with valid controls.

The **only** context it ever read "dead" was the original *congested 18-bit
counter* (the `silicon_converge` sweep, many simultaneous corridor nets). So the
per-edge "dead" verdict is a **congestion-context failure mis-attributed to a
single edge** — the edge itself conducts fine in isolation, forced or not.
`RMUX63@(10,4)->RMUX68@(9,4)` also conducts natively (deadwit_754); its forced
single-edge build isn't even constructible in our arch model (only 4 BBMUX-dest
pips modeled), consistent with the same picture.

**Two honest consequences:**
1. The per-edge `dead_edges_silicon.csv` catalogue is unreliable — its entries are
   congested-context failures, not intrinsic per-edge silicon death. Our
   per-edge conduction-gating was therefore over-restrictive (since fully
   corrected — the negative table is now empty), and our own bitgen
   already encodes these edges byte-exact (verified).
2. **But congestion at the MCU-exit corridor is a real, aggregate limit** — that
   is genuinely where conduction failed. So un-gating individual edges is
   justified, yet it does **not** by itself guarantee that *wide, congested*
   designs (fabric AHB master, full-word MCU writes) conduct. Wide-congested
   conduction is the true open frontier, and it needs its own silicon test plus a
   fuller BBMUX-corridor arch model (the current one hardcodes only 4 exit pips).

**Calibrated:** Current production count: 14 of 14 admitted; 0 conservatively
blocked as unverified (see the 2026-08-14 through 2026-08-16 entries). The
*mechanism* (congestion mis-attribution) is now board-supported for every edge
in the historical catalogue. This is still not a claim that arbitrary routing
or wide/congested designs work: those combinations remain unmeasured.

## Plan (in order)

1. **Mechanism** — DONE (board-pinned 2026-08-13; subsequently supported for
   every edge in the catalogue): rebuild the *same* edge the forced/blacklist way,
   confirm it reads STUCK while native conducts (same edge, opposite results =
   the verdict is a method artifact), and diff forced-vs-native bitstreams to
   expose exactly which neighbor/companion configuration the blacklist strips.
2. **Broad scope**: ~~LogicLock-aimed builds to route each of the remaining 12 dead
   edges deliberately (no blacklist), read each -> the real artifact rate.~~
   **Attempted 2026-08-14, re-scoped, then partly delivered** (see the top two log
   entries): forcing yields positives only — its negatives are proven
   uninterpretable by matched sibling controls. Switching to an *unconstrained
   readback* (a physical pad on the destination side) worked and admitted two more
   edges, bringing the total to 5 of 14 with **9 left** at that point. The direct
   PIN_25-to-PIN_18 witness closed one more, and direct pad-to-pad witnesses
   subsequently closed the entire catalogue — **14 of 14 admitted, none
   remaining** (see the 2026-08-15/16 log entries and
   `qualification/conduction_ungate_evidence.jsonl`).
3. **Promote** — DONE (2026-08-13 for the first two; completed 2026-08-16 with
   all fourteen admitted): the two board-verified edges are un-gated in the
   shipped router; see the top log entry. A forced verdict was never promoted as
   conduction — the forced build only proved the pip is load-bearing, while the
   *natural* and *native* builds carry the positive evidence. Zero-regression, pushed.
4. **Dive**: the wide MCU-boundary surface the extra corridor bandwidth should
   unlock — fabric AHB master, full 32-bit writes, the full request phase — since
   those are gated on "simultaneous wide routing across the MCU exit," which is
   exactly the corridor these edges live in.

## Log

### 2026-08-18 — T26: constant-slave regression — root-caused (partially), fixed via pinned checkpoint, one defect stays open

**Read this before citing the constant-slave claim.** Picks up T22–T24 below
(bisect target `f705d28`/`1957fd8` .. `629e843`, prime suspects `48cda69` and
`183e9b6`). Method was desk-first bisection (rebuild at the 2026-08-02
known-good commit and at HEAD, controlled A/B packs of identical routed
pip-trees under old-vs-new bitgen to isolate byte-level diffs) followed by
targeted L48 board re-verification of each candidate fix (SRAM-only,
reset-bracketed, zero flash writes).

**Finding 1 — real defect, but insufficient.** `chipdb/mcu_edge_feeder_exit_pairs.csv`
had no exact tuple for `X14Y11_RMUX03 -> X13Y11_BBMUXE09`, so bitgen used the
`BBMUXE_PAIR[3]` source-index fallback. `48cda69` (2026-08-14) correctly
changed that fallback from `(1,6)` to `(2,4)` for every RMUX03 edge that had a
witness — but `(1,6)` was, by coincidence, the actual 2026-08-02 silicon-correct
encoding for this one specific, previously-unwitnessed edge (a
per-destination-terminal property, not a per-source-index one — a genuine
counterexample to `48cda69`'s own "zero contradictions" claim for source index
3). Desk-proof: packing the pinned (buggy, 149-pip) routed JSON with the
pre-/post-`48cda69` fallback value changes exactly one named feature
(`X13Y11 BBMUXE9`'s selector, `{1,6}` vs `{2,4}`). Fixed by adding the exact
tuple (`13,11,BBMUXE09,14,11,RMUX03,1;6`), which bitgen always checks before
the fallback, so `48cda69`'s correction for the edges it actually covers is
untouched (`tests/test_boundary_mux_selectors.py` now pins both as legitimate,
per-terminal exceptions for source index 3). **Board result: insufficient
alone** — the fixed-only image still read `0x795fe3dd`, byte-identical to the
unfixed one. Why: `BBMUXE09` feeds logical HRDATA bit 22, and bit 22 was never
actually wrong (`0x4147414d` and `0x795fe3dd` agree there). The fix is real,
independently silicon-grounded, and kept — it just was not the cause of this
regression, which is why "the dict transposition commit is a prime suspect"
turned out to be the wrong lead despite passing every desk check.

**Finding 2 — the real 10-bit cause, only partially fixed.** Tracing all 10
actually-wrong bits' pip chains (`0x4147414d ^ 0x795fe3dd`, bits
4,7,9,13,15,19,20,27,28,29) found they share one upstream trunk:
`X14Y11_OMUX14` (the GND-constant driver's presentation) `-> X14Y11_RMUX37 ->
X14Y8_RMUX71 -> X14Y8_IMUX17 -> X14Y8_RMUX69`, fanning out to
`RMUX93@(14,12)`/`RMUX93@(14,11)`/`RMUX86@(14,11)` directly and via
`RMUX92->RMUX90@(14,11)` to three more `BBMUXW` terminals — the identical
`X14Y8` RMUX→IMUX→RMUX detour `48cda69`'s own commit message already flagged
as "a separate, still-open defect" for a different design's lane 9. Forcing
nextpnr around it (`AGAMEMNON_EDGE_BLACKLIST` on the two detour pips, under a
`research-unsafe` policy override used *only* to permit that option — chipdb
otherwise untouched) produced an alternate 155-pip route that **fixed 9 of the
10 wrong bits** (read `0x4107414d`) but **introduced a new wrong bit** (18,
`X13Y11_BBMUXE05<-X14Y11_RMUX03`) whose entire declared pip chain is
byte-identical across the golden/rerouted/buggy netlists — i.e. a cross-net
side effect from rerouting elsewhere, not a wrong table value on that edge.
Not shipped (trades one regression for a smaller one) and not resolved
further this session; it needs its own investigation (a shared-config-byte or
nextpnr arc-cost/ownership interaction is the leading suspect). This is new,
direct, board-confirmed evidence for the "wide/congested MCU-exit corridor"
open frontier this log already flags below — not a simple isolated data bug.

**Shipped fix.** `qualification/mcu_ahb_constant_slave_routed.json` is
re-pinned to the retained 2026-08-02 (`f705d28`) 156-pip routed netlist
(previously never checked in — the pinned artifact this whole investigation
started from was always the *buggy* 149-pip route). Packing that netlist with
current HEAD bitgen, including the Finding-1 fix, reproduces
`bitstream_sha256 b2047ed2cea3bc2e80307aac2d76e8cfda54975b899671c375591a008bad6e04`
byte-for-byte — the exact bitstream hardware-confirmed twice on 2026-08-02.
Re-confirmed this session on the physical L48 reference board (72 direct
reads + 6 mailbox reads, 0 exceptions, `0x4147414d`, `FCB_STAT 0x000f0002`,
`DEVICE_ID 0x40200001`; SRAM-only, board left clean). `qualification/pack_regression.json`
and `qualification/mcu_ahb_constant_slave_evidence.jsonl` (trial
`2026-08-18-t26-regression-fix`) carry the full record.

**ADDENDUM 2026-08-19 (A1b) — Finding 1 is RETRACTED on board evidence; `48cda69` was right.**
The first full suite after T26 failed 10 tests: seven `test_qualified_pack_regression` byte-identity
checks (the five `mcu_ahb_public32_*` variants and two `status_overlay_*_public32`) plus three
`test_sdk_workflow` qualified-profile replays. Isolated by A/B to the Finding-1 chipdb row alone —
all seven designs route the same `X14Y11_RMUX03 -> X13Y11_BBMUXE09` pip, so the exact tuple re-encodes
them too. That was settled on the L48 reference board in one session, SRAM-only, each pair being the
same routed netlist packed twice (3 config bytes + CRC apart) and run through the design's own
unmodified oracle:

| design | codeword | image | board result |
|---|---|---|---|
| `public32_gpio5_w1c_exact_map` | `(2,4)` fallback | `bc338504…` (= the 2026-08-15 silicon golden) | **PASS**, nine error groups zero, ID32 `0x4147414d` |
| `public32_gpio5_w1c_exact_map` | `(1,6)` T26 tuple | `8673ae0d…` | **FAIL**, ID32 `0x4107414d`, errors `[64,64,459780,0,0,0,513,3,0]` |
| `mcu_ahb_constant_slave` (156-pip) | `(1,6)` T26 tuple | `b2047ed2…` | PASS, 72/72 + 6/6 |
| `mcu_ahb_constant_slave` (156-pip) | `(2,4)` fallback | `3ef719a0…` | **PASS**, 72/72 + 6/6, FCB `0x000f0002` ×6 |

`0x4147414d ^ 0x4107414d = 0x00400000` — **bit 22, exactly the lane `BBMUXE09` feeds**, and it is live
in `public32`. So `(2,4)` is the silicon-correct value for this pip; `(1,6)` is *wrong* there and merely
*harmless* in the constant slave, which does not observe that lane. **The exact tuple has been removed**,
`48cda69`'s fallback stands, and `qualification/mcu_ahb_constant_slave_routed.json`'s pack pin is now the
`(2,4)` image `3ef719a0…`, which is itself board-verified in this trial (a strict improvement: we no
longer reproduce a historical image carrying a value we now know to be wrong).

**Why Finding 1 looked right and was not — the durable lesson.** It was inferred from byte-reproducing
the retained 2026-08-02 golden. But that golden predates `48cda69`, so it *necessarily* carries the old
value, and on a lane the constant slave does not observe **both encodings pass**. **Byte-identity against
a hardware-witnessed golden is therefore not a unique correctness criterion** — the golden cannot
arbitrate a field it does not exercise. Arbitrate with a design that *observes* the field. The
`tests/test_boundary_mux_selectors.py` "per-destination-terminal codeword" exception T26 added is
withdrawn with the row: there is no witnessed counterexample to source-index codewords after all.

**One correction that changes an open question.** T26's forced-reroute experiment (run with the refuted
`(1,6)` row applied) reported its single residual wrong bit as **18**, but the value it read,
`0x4107414d`, differs from correct in **bit 22** — the `BBMUXE09` lane. That residual error is fully
explained by the `(1,6)` row itself, not by a cross-net config interaction. **Hypothesis, now the most
promising lead on the actual regression: blacklisting the `X14Y8` detour *without* the row fixes all ten
bits.** The 155-pip alternate netlist was not retained, so this needs a fresh nextpnr run with the
blacklist. Until that is tested, the `X14Y8` detour stays the open defect and the "cross-net
interaction" reading should be treated as probably an artifact of the refuted row.

Evidence: `qualification/mcu_ahb_constant_slave_evidence.jsonl` trial `2026-08-19-a1b-codeword-matched-ab`;
board scripts in `AG32-Docs/tools/t26_codeword_ab/`.

**Honest scope of "fixed."** This restores the claim for the pinned/checked-in
artifact (which is what `pack_regression.json` and the SDK actually ship) but
NOT for a truly from-scratch `agamemnon build --uarch` of this design: nextpnr
picks a different (149-pip) route today than it did on 2026-08-02 purely from
chipdb/table growth (the build's own `cap=2 seed=4` is unchanged), and that
route hits Finding 2's still-open detour defect. Matches the pattern several
sibling `mcu_ahb_*` designs already use (`--qualified-checkpoint` / pinned
`qualified_profile`) for exactly this class of risk — this design just was not
using it. **For T27:** any OTHER shipped MCU-AHB claim that is fresh-built on
demand (no checked-in pinned routed JSON, no `--qualified-checkpoint`) is
exposed to the same drift risk regardless of whether it happens to route
through these exact edges; claims that replay a pinned/hash-bound artifact
(most of the `public32`/`public16` exact-map family) should be unaffected but
have not been independently re-run this session.

### 2026-08-18 — T24: constant-slave L48 DECISIVE REREAD — confirms LIVE TOOLCHAIN REGRESSION, not L64/package-specific

**TOP PRIORITY, read this before citing the constant-slave claim.** T22/T23
(below) could not run the decisive check because only the L64 unit was
attached. Brian physically swapped in the L48 reference board; T24 is that
run, using the unmodified push-button script
`AG32-Docs/tools/l64_bringup_20260818/l48_decisive_reread.py`, same 6-cycle
reset→reconfigure→run procedure, same sha-pinned artifacts
(`bitstream_sha256 fc6919c2…`, firmware `4e1213c3…`).

**Board identity:** the script's built-in guard confirmed the attached board's
16 KiB flash-prefix hash does **not** match the retained L64 factory backup
(rules out this being the L64 unit re-attached by mistake), so it proceeded
rather than refusing with exit 3. It also printed a WARNING that the live
prefix does not match the retained `STOCK_FACTORY_flash_256k.bin` snapshot of
the L48 reference unit either. Checked further this session: that STOCK
snapshot dates to 2026-06-29/07-02 (`git log`), roughly seven weeks and
dozens of legitimate flash-writing qualification sessions before this run
(2026-08-02 constant-slave qualification, MCU+PLL silicon campaign,
wave-recalib, etc.), so a diverged flash prefix on the same physical dev
board is expected, not a red flag. The debug-probe serial number
(`48305042083436371929a4…`) is identical to the one used throughout the L64
session, consistent with Brian's description (same probe, target board
swapped). Net: high confidence this is a non-L64 unit (most likely the L48
reference), but the flash-prefix fingerprint itself does not independently
re-derive "L48" the way it independently ruled out "L64" — the stale
STOCK_FACTORY backup should be refreshed so future runs get a clean positive
match instead of a warning.

**Result: 72/72 direct bank reads + 6/6 mailbox reads = `0x795fe3dd`, zero
exceptions**, identical in every particular to the L64 result (T23). FCB_STAT
was `0x000f0002` and DEVICE_ID `0x40200001` every one of the 6 cycles;
`misa 0x40801125` reconfirmed at session end on a plain reset with zero flash
writes issued at any point (board left clean).

**This lands branch 2 of the T22/T23 open question.** `0x795fe3dd` is now
confirmed on two physically distinct dice/packages (L64 and this board) for
the byte-identical `fc6919c2…` build — the shipped `docs/STATUS.md` L48
constant-slave claim (`0x4147414d`) is **not reproduced by the current
toolchain HEAD**, even on hardware most consistent with the qualified
reference unit. New analysis this session, beyond T22/T23:

- `0x4147414d ^ 0x795fe3dd = 0x3818a290`: **10 of 32 bits differ**, not one.
  That rules out the single-stuck-lane failure shape T22/T23 were modeled on
  (compare the unrelated but structurally similar `counter2_carry_seam`
  negative below, which was exactly one stuck bit from one bad codeword).
  Getting the identical wrong 10-bit pattern on two independent dice from a
  deterministic, conduction-blind, congestion-blind constant fan-out is very
  hard to explain as an analog/silicon margin effect (it would need the same
  ~third of 32 wide-fanout lanes to fail in the identical direction on two
  separate chips); it is far more consistent with a deterministic bitgen/
  selector-encoding defect that reproduces identically on any unit built from
  this exact bitstream.
- The routed JSON's `$PACKER_GND_NET`/`$PACKER_VCC_NET` pip-trees
  (`AG32-Docs/tools/l64_bringup_20260818/constant_slave_routed.json`) show
  this design's fan-out uses `X14Y11_RMUX03 -> X13Y11_BBMUXE09` and
  `X14Y11_RMUX03 -> X13Y11_BBMUXE05` directly at the MCU-edge boundary
  funnel, plus seven distinct `BBMUXW00`–`BBMUXW06` entrances. `RMUX03` is
  one of exactly the two feeder codewords commit `48cda69` ("Fix two
  transposed boundary-mux codewords", 2026-08-14) found wrong in the
  hand-typed `bbmuxe_fanin.csv` dict, with the identical failure signature
  ("the emitter finds *a* codeword, writes a structurally valid selector,
  reports 0 unmapped... only silicon disagrees, as one lane that never
  varies"). Commit `183e9b6` ("Promote exact L48 public32 map", 2026-08-16)
  separately added a new exact-tuple admission gate for RMUX→BBMUXW
  entrances that this design's seven BBMUXW lanes are directly exposed to.
  Both commits are ancestors of the `fc6919c2` build (git_head `7247e134`/
  `6e7b51b`), so their fixes/changes are *included*, not excluded — meaning
  either the `48cda69` fix is incomplete (a third/further wrong codeword in
  the same table, not caught by the dict-vs-harvest diff that found only two),
  or `183e9b6`'s new BBMUXW admission logic independently introduces a
  different wrong-selector class, or both interact. **Not confirmed which —
  flagged for the next session, not fixed here** (out of scope for this
  read-only decisive-reread task).
- **Bisect target range** (unchanged endpoints from T22, now narrowed by
  content): 2026-08-02 qualification (`f705d28`/`1957fd8`, hardware-confirmed
  `0x4147414d` twice, including a from-scratch rebuild with a different
  `bitstream_sha256`) through `629e843` (2026-08-17, T22 already showed
  byte-identical bitgen/routing path from there through current HEAD for the
  relevant files). Within that ~63-commit window, `48cda69` (2026-08-14) and
  `183e9b6` (2026-08-16) are the two commits that touch the exact subsystem
  (MCU-boundary-funnel BBMUXE/BBMUXW selector table and admission) this
  design's entire fan-out routes through, and neither has been build-bisected
  yet (no intermediate commit has been rebuilt+hardware-checked this
  session).

**Golden pinned regardless of attribution:** per T22's own flagged gap ("this
design also has zero `pack_regression.json` byte-identity coverage"),
the exact routed JSON and bitstream for this `fc6919c2` build are now pinned
as `qualification/mcu_ahb_constant_slave_routed.json` in
`qualification/pack_regression.json` (environment
`AGAMEMNON_HSE=8, AGAMEMNON_SYSCLK=10`, matching every sibling `mcu_ahb_*`
entry; `python -m agamemnon.cli pack` on that JSON reproduces `fc6919c2…`
byte-exact). This is a drift trip-wire, not a correctness claim — it pins
what the toolchain currently emits so any *further* change is caught, while
the emitted value itself is exactly the one under active dispute above.

Full transcript and structured record: T24 trial in
`qualification/mcu_ahb_constant_slave_evidence.jsonl`.

### 2026-08-18 — T23: constant-slave L64 mismatch REPRODUCED (0/96 exceptions) — not a bring-up glitch, attribution still open

T22 (below) desk-cleared a regression but could not run the decisive L48
reread, since only the L64 unit was attached. T23 asked a narrower question
first: is the L64-observed `0x795fe3dd` even real, or was it a first-session
artifact? Answer: real. One continuous OpenOCD session ran 6 independent
`reset halt` → reconfigure → run cycles of the same, byte-verified
`bitstream_sha256 fc6919c2…` on the same physically-attached L64 unit (fresh
16KiB flash-prefix hash re-confirmed against the retained L64 backup); each
cycle read the firmware's mailbox (FCB_STAT + 3 bank reads + a post-write
readback) plus a DEVICE_ID sanity read plus 12 further direct in-config bank
reads with no intervening reconfigure. Full detail and the raw transcript are
in `qualification/mcu_ahb_constant_slave_evidence.jsonl`, trial
`2026-08-18-t23-l64-const-mismatch-reproduced`.

Result: **96/96 bank reads returned `0x795fe3dd`, zero exceptions**, across
both config-time (6 reconfigures) and read-time (12 back-to-back reads within
one configuration) axes. FCB_STAT was `0x000f0002` every cycle (the fabric did
configure) and the DEVICE_ID sanity read was `0x40200001` every cycle (the
read path itself is sane, not stuck). This closes the "T21 was a session
glitch" hypothesis outright — the mismatch is a real, stable, reproducible
result on this physical L64 unit for this exact bitstream. It does **not**
resolve *why*: T22's desk audit already showed every desk-computable layer of
this same bitstream (cycle-sim, routed-JSON pip-tree reconstruction, bitgen's
mux-ownership check) independently agrees on `0x4147414d`, so the fault is
either a byte-level encoding bug below that layer (which would also affect
L48) or something specific to the L64 unit/package/silicon — undistinguished
either way. `tools/l64_bringup_20260818/l48_decisive_reread.py` (in
AG32-Docs) is a push-button, sha-pinned rerun of the identical 6-cycle
procedure, ready the moment the L48 board is swapped in; it already refuses
correctly when pointed at the still-attached L64 unit (exercised this
session, exit code 3, no SRAM operation attempted). Treated as a candidate
data point for the wide/congested-MCU-exit-corridor frontier below — **not**
yet a claim either way.

### 2026-08-18 — T22: constant-slave 32-way VCC/GND fan-out mismatch, desk-cleared of regression, silicon question still open

`examples/designs/mcu_ahb_constant_slave.v` is a single-source, 32-sink
combinational fan-out — exactly the "wide" shape this log's Dive item (4)
flags as the open frontier, just via two constant generator cells
(`$PACKER_VCC_NET` / `$PACKER_GND_NET`) instead of live logic. A first-session
LQFP-64 board read `0x795fe3dd` from this design's AHB constant read
(`qualification/l64_bringup_evidence.jsonl`), while that identical
bitstream's own `--verify` cycle-sim, and the 2026-08-02 L48-qualified value,
both say `0x4147414d`.

Desk audit (full detail in `qualification/mcu_ahb_constant_slave_evidence.jsonl`,
trial `2026-08-18-t22-const-mismatch-desk-audit`): the four commits landed the
same night as the L64 session do not touch this design's build/bitgen path at
all (confirmed by file-level diff, not just build reproduction), so this is
not a regression. Independently of the cycle-sim, parsing the routed JSON's
two constant nets' `ROUTING` pip-trees against `mcu_hrdata_lanes.csv`
reconstructs all 32 HRDATA bits to `0x4147414d` by a completely different
path, and bitgen's own cross-net mux-ownership conflict check raised nothing.
Every desk-computable layer agrees with the qualified value; the L64
mismatch is not explained there. The decisive check — SRAM-inject this exact
bitstream on the qualified L48 reference and read it back — was not run: only
the L64 unit was physically attached this session (confirmed by a read-only
flash-prefix hash match against its retained factory backup), and the L64
unit stays idle for this investigation per policy. If the L48 reread also
mismatches, this is real evidence for the wide-congested-conduction frontier
(a single-source 32-way fan-out through the same MCU-exit corridor family as
the rest of this log) rather than an L64-package artifact; if it reads
`0x4147414d`, the L64 unit/package is the outlier. Neither is confirmed yet.

### 2026-08-16 — FINAL DIRECT PAD-TO-PAD WITNESS: 14 of 14 admitted

`RMUX15@3,4->RMUX68@6,4` is board-proven and removed from
`dead_edges_silicon.csv`, closing the historical catalogue. The replacement
for the earlier inconclusive construction keeps qualified PIN_25 ingress,
fixes the consumer at `X6Y4_SLICE11`, and makes the sibling or target hop the
only non-clock `x=3.5` crossing. The prior control had continued east and then
doubled back to an X5 consumer; this compact A/B shares the fixed consumer and
complete PIN_18 output route.

The sibling `RMUX15@2,4->RMUX68@6,4` used 5,983 cut bans and 28/28 mapped data
PIPs. The target used 5,975 cut bans and 25/25 mapped data PIPs. Both had zero
legacy-absolute, predicted, or unmapped selectors and no cross-net physical-mux
conflict. Each FCB-accepted and returned the exact inverse of GP12's eight-state
sequence on GP8 under both pulls. SRAM only; Pico pins restored to inputs; board
reset clean; no flash write.

### 2026-08-16 — seven more direct pad-to-pad witnesses (13 of 14 admitted)

Between the 2026-08-15 edge-7 witness and the final edge above, seven further
catalogued edges were board-proven with the same direct pad-to-pad method and
removed from `dead_edges_silicon.csv`, one commit per edge:
`RMUX26@15,4->RMUX09@14,4`, `RMUX33@15,4->RMUX39@14,4`,
`RMUX80@15,7->RMUX33@15,4`, `RMUX21@14,8->RMUX87@14,5`,
`RMUX21@14,9->RMUX87@14,7`, `RMUX69@14,6->RMUX76@14,10`, and
`RMUX09@14,4->RMUX28@14,8`. Per-edge records are in
`qualification/conduction_ungate_evidence.jsonl`.

### 2026-08-15 — DIRECT PAD-TO-PAD WITNESS: edge 7 conducts (6 of 14 admitted, 8 left)

`RMUX68@9,4->RMUX74@11,4` is now board-proven and removed from
`dead_edges_silicon.csv`. The earlier pad witness for this edge and its sibling
both read static, so that experiment remains useful as a method negative but no
longer determines the edge verdict: its source was a clocked relay construction
with an unqualified upstream composition.

The replacement removes that ambiguity. Physical decimal L48 `PIN_25` (Pico
GP12) enters through its exact vendor corridor
`InputMUX00@(0,4)->RMUX11@(1,4)->IMUX09@(1,4)`, passes through two kept
combinational LUTs, crosses x=9.5 exactly once, and leaves through the already
qualified `PIN_18` output (Pico GP8). A dummy toggle register exists only so the
FCB test stub completes; it is not on the measured data path.

The ordinary, unforced image is the matched positive control. Its only non-clock
cut crossing is `RMUX68@9,4->RMUX81@11,4`; it config-accepted and returned the
repeated inverted truth table `0->1, 1->0, 0->1, 1->0`. The target build used a
fresh 6,368-edge cut ban from the current production RRG and a scratch chipdb
with only the target's historical negative removed. Its routed JSON contains
`RMUX68@9,4->RMUX74@11,4` consecutively on `observed`, with no other non-clock
cut crossing. It mapped 18/18 data PIPs with zero predicted, legacy-absolute, or
unmapped selectors, config-accepted at `FCB_STAT=0x000f0002`, and returned the
same repeated truth table. Both crossings use selector pair `[3,8]`; only the
destination group differs (`CFG_RMUX13` control versus `CFG_RMUX12` target).

This is positive self-validating conduction evidence, not an inference from a
static result. It also qualifies the exact PIN_25 plain-input corridor used by
this composition, not the complete four-link bidirectional node. Evidence is in
`qualification/conduction_ungate_evidence.jsonl`; the reproducible builder is
`AG32-Docs/tools/agamemnon/engine_work/build_blocked7_direct.py`.

After promotion, that same builder was rerun against the production chipdb (with
no scratch override) and regenerated the measured target image byte-for-byte:
SHA-256 `7b6e0dd5f296f73e85eba134933e17645d47750a50b885a7208e2b98e2f21066`.
The admitted edge is therefore exercised by the normal production graph, not
only by the diagnostic construction that first established conduction.

### 2026-08-15 — a second instance of the reframe, and this one was a two-byte bug in our own emitter
The reframe's thesis is that failures we attributed to silicon were ours. Here it is
again, in a form worth remembering because *three* separate campaigns were stalled on it
and nothing in the build flagged it.

`agamemnon/chipdb/bbmuxe_fanin.csv` is the vendor-corpus harvest of the MCU-edge boundary
funnel: 14 feeder tracks, each with exactly one observed selector codeword
(`n_variants = 1` on every row). It has shipped, declared on the routing feature, the whole
time. `features/routing.py` did not read it — it carried a hand-typed copy, and that copy
disagreed on two feeders: `RMUX43` held `(0,6)`, which is `RMUX63`'s codeword, and
`RMUX03` held `(1,6)`, which is `RMUX43`'s. A 43/63 digit transposition and a shifted
entry. Nothing compared the dict to the file.

What that produces is the nastiest possible failure shape: the emitter finds *a* codeword,
writes a structurally valid selector, and reports **0 unmapped**. The boundary mux then
selects a track the design never drives. Every downstream check passes; only silicon
disagrees, and it disagrees quietly, as one lane that never varies.

Two campaigns were misattributed to the part as a result:

- **The 16-lane AHB scratch.** Lane 5 read stuck HIGH. It exits over
  `X14Y12_RMUX43 -> X13Y12_BBMUXE07`, so the mux was pointed at `RMUX63` — which in that
  very image carried `$PACKER_VCC_NET`. That is why the symptom was stuck *high*
  specifically. Correcting two config bytes on an otherwise unchanged netlist takes group 1
  from `exact=29/64` to `exact=64/64`. That intermediate image read 15 of
  16 lanes exact. **Superseded 2026-08-15:** relocating capture9 from the
  historically negative X15Y12 slice4 site to silicon-live X14Y11 slice7 made
  the retained posted-capture checkpoint exact on all 16 lanes. This remains a
  posted capture, not a 16-bit register bank.
- **The X15 downward carry seam.** Trial `2026-07-14-intertile-carry-x15-seam-sweep` was
  retained as `fail_isolated` — "the upstream bit0 varied but downstream bit1 never
  varied" — and produced the standing resolution *do not expose generalized downward seam
  pips*. `cnt[1]` exits over `X14Y12_RMUX43 -> X13Y12_BBMUXE03`. Re-packing the retained
  routed artifact with the correction and re-reading it gives `distinct=4`, both lanes
  varying, over the dedicated crossing `X15Y2_CARRYOUT15 -> X15Y1_CARRYIN00`. The seam
  conducts. The negative is withdrawn as unproven; one instance is not a sweep, so the
  architecture gate is unchanged until the y=4..9 sweep is re-run.

  Then the control that sweep never ran, because correlation is not causation and the
  claim is worth nothing without it: put the wrong codeword *back* into the passing image
  and change nothing else. The patched image comes out **byte-identical to the bitstream
  the failing trial pinned** (`2bca0de0…`), and on the board it reproduces that trial's
  exact observation — `distinct=2`, only lane 0 varying. Flip the one selector field and
  the same silicon counts: `distinct=4`, lanes `[0,1]`, 126/125/125/124. Two configuration
  bytes, back to back on one board session.

A third thing fell out for free. The emitter drops every carry hop before selector
emission, which had left it genuinely unresolved whether the inter-tile crossing needs
configuration at all. It does not: that chain counted correctly in an image that emitted
*zero* bits for the hop. Inter-tile carry is dedicated hardware chosen by placement, not a
routed mesh net.

Two corollaries are now banked in the ledgers and enforced by
`tests/test_boundary_mux_selectors.py`:

1. **Strict-clean emission proves nothing about a boundary terminal.** "0 unmapped" means
   an encoding was found, not that it was the right one. Any future
   *strict-clean therefore correct* inference about a boundary mux is unsafe.
2. **A hand-typed constant that duplicates a shipped data file must be tested against it.**
   The new test asserts `BBMUXE_PAIR` equals `bbmuxe_fanin.csv` row for row, that every
   fallback entry agrees with every exact exit-pair table, and that the south/east
   boundaries satisfy `BBMUXS_PAIR[i] == BBMUXE_PAIR[(i + 24) % 96]` — an offset law that
   independently requires both corrected values.

One process note, since it cost a cycle: the first diagnosis of lane 5 was wrong and is
withdrawn in the ledger. A probe compared cells named `BBMUXE07` while `pips_mcuedge.csv`
names them `BBMUXE7` unpadded, so it compared an empty set and reported "zero differences",
which read as evidence. That is the third time in this campaign that zero-padded resource
names have silently defeated a comparison. A probe that finds *no* differences should be
required to say how many things it actually compared.

### 2026-08-14 (later) — UNCONSTRAINED READBACK: two more edges un-gated (5 of 14 now admitted, 9 left)
The structural limit named in the previous entry is **solved**. Move the witness
off the MCU-dout path and onto a **physical pad on the destination side of the
cut** (`relay_pad.v` + `build_padwitness.py`, composing the proven PIN_18
pad-output flow with the one-shot cut ban): a toggle FF on the SRC side relays to
a register at the pad-route source `X14Y9_SLICE0` on the DST side, which drives
PIN_18 straight to an external logic analyzer. The observation channel never
crosses the cut, so the rest of the build stays lightly constrained — exactly the
property the dout witness lacked.

The pad runs at SYSCLK/2, far above the analyzer's polled rate, so an **aliased**
scan is the right detector: a conducting path gives a mix of highs and lows, a
dead one a constant level, and flipping the probe's own pull distinguishes driven
from floating.

| edge | banned crossings | PIN_18 (pull-up / pull-down) | verdict |
|---|---|---|---|
| `RMUX08@12,4->RMUX32@14,4` | 4,123 | 98/102 · 84/116 | **TOGGLE → un-gated** |
| `RMUX74@11,4->RMUX08@12,4` | 5,527 | 102/98 · 93/107 | **TOGGLE → un-gated** |
| `RMUX68@9,4->RMUX74@11,4` | 6,368 | 200/0 · 200/0 | STATIC — but its matched sibling (`RMUX68@8,4->RMUX74@11,4`) is **also** STATIC, so uninterpretable; stays gated |

Both un-gated edges already carried positive `silicon_ff2` evidence and vendor
corpus usage (65 and 6 designs), so removing their blacklist rows admits them.
`dead_edges_silicon.csv`: 11 → **9 rows**. `RMUX09@14,4->RMUX28@14,8` and
`RMUX69@14,6->RMUX76@14,10` now fail to route at all once the ban is fully
honoured — a bounded, unresolved state, not a verdict.

**Two workbench bugs this exposed, both fixed — and both would have silently
corrupted any similar analysis:**
1. **Zero-padded wire names.** The pad flow writes `X12Y4_RMUX08` where the relay
   flow writes `X14Y10_RMUX21`, so raw-string hop comparison silently missed real
   witnesses on every edge whose resource index has a leading zero. All hop
   matching now normalizes the index. (Re-checking earlier runs with the fix found
   one genuine missed witness.)
2. **The BRAM pip loader ignored the edge blacklist.** BRAM route-throughs are
   long-range — the `TMUX->KMUX->InputMUX` chain jumps eight tiles in one hop — so
   a "forced" route could hop the cut through the BRAM column and quietly
   invalidate the forcing. The loader now honours the blacklist like every other.

### 2026-08-14 — third edge un-gated; and forcing-construction NEGATIVES are proven uninterpretable
A generalized per-edge campaign over the 12 then-blocked edges (`force_dead12.py`).

**Method.** Iterative escape-banning cannot work: a geometric cut between an edge's
endpoints carries **4,113–12,489 enumerated crossings**, so banning the router's
observed detours a few at a time never converges (the one edge that did converge
that way, in 7 iterations, was luck). The construction that *does* work is a
**one-shot full-cut ban** — blacklist every enumerated crossing of the cut except
the edge under test, so the relay net has exactly one legal way across and a
completed route provably uses it. That needed a file-based blacklist
(`AGAMEMNON_EDGE_BLACKLIST_FILE` in the workbench arch), since 11k edges vastly
exceed the 32,767-character Windows environment-variable limit.

**Positive.** `RMUX87@(14,8)->RMUX68@(14,7)` reads **TOGGLING** on silicon in two
*independent* forced constructions — iterative (24/25) and one-shot full-cut with
11,450 edges banned (26/23) — with the design-neutral base image as a validated
STUCK control, its hop route-verified on the live relay net both times, and the
edge already carrying positive `silicon_ff2` evidence plus 7 vendor-corpus
appearances. **Un-gated**: `dead_edges_silicon.csv` 12 → **11 rows**.

**The important negative — about the METHOD, not the silicon.** Five other edges
read STUCK under the same construction. Before banking any of that, matched
**sibling controls** were built: identical cut ban, identical qa/qb placement,
identical destination node, but keeping a *different, non-catalogued* feeder as the
single legal crossing. **All four constructible siblings also read STUCK.** So a
full-cut forced build (4.8k–19.2k banned edges) does not generally yield a working
image, and a STUCK reading from it says nothing about any edge. The five targets
stay **unverified**, exactly as before — nothing was banked from them. Positive
readings remain valid (a toggling signal is self-validating), which is precisely
why the one admitted edge is admitted.

This independently reproduces the reframe's central claim from the opposite
direction: heavily constrained constructions fail for reasons unrelated to
per-edge conduction — the same confound that produced the original catalogue.

**Structural limit.** Four of the eleven cannot be tested this way at all: the
readback (`dout`) net must re-cross the same cut and cannot share the single legal
crossing (`RMUX08@12,4->RMUX32@14,4`, `RMUX09@14,4->RMUX28@14,8`,
`RMUX69@14,6->RMUX76@14,10`, `RMUX74@11,4->RMUX08@12,4`). A fifth
(`RMUX68@9,4->RMUX74@11,4`) failed to route under the ban. **What would actually
close these:** an *unconstrained* readback — a second, independent observation
channel (a physical pad on the DST side, or a fabric-local capture register read
over External-AHB) so the witness route needs no cut crossing at all, letting the
build stay lightly constrained enough to function. Evidence:
`qualification/conduction_ungate_evidence.jsonl`
(`conduction-ungate-rmux87-14-8-rmux68-14-7-20260814`,
`conduction-cutforce-method-negative-control-20260814`).

### 2026-08-13 — write-side CORRECTION: the direct-D 4-site pool is a self-imposed limit
Interrogating the silicon FAIL ("how did we do this before / how would af.exe do it?") corrected
the whole approach. The AGRV2K slice's **direct-D self-feedback selector works at every slice** —
af.exe places own-Q registers anywhere and routes normally; there is **no "4-site pool" in the
vendor flow.** That pool is *ours* (we only generically silicon-verified 4 sites). The qualified
8-bit register bank did **not** use generic own-Q auto-placement either: it uses (a) an
**unconditional** capture register (`write_data_pipe`) + an AHB write-wait so HWDATA crosses a
plain register before retirement (the RTL comment: an enable/reset mux *"would turn each hard
HWDATA lane back into several LUT consumers before the FF"*), and (b) **exact per-lane
hand-placement** of its own-Q state bits at specific silicon-verified sites (the STATUS grind:
`X14Y12 slice15`, `X14Y11 slice0`, ...) — i.e. already *more than 4* own-Q sites, replayed as an
exact checkpoint. My multi-site attempt used **neither** method — a naive generic `qin_pack`
multi-pin to the auto-pool + 2 experiment sites — which produced non-qualified routing that broke
even the 4 already-qualified sites on silicon. So the "negative" was my broken construct, not the
sites. **Corrected path (sea-change applied to writes):** pursue the exact-per-lane /
unconditional-capture register-bank method scaled wider, where the real limiter is
write-**ingress** corridor width (write24 already routes 24 ingress lanes) — not generic direct-D
multi-pin. The 4-site pool is a self-imposed verification limit, exactly like the conduction
blacklist.

### 2026-08-13 — direct-D pool widening: builds + sim-pass, FAILS on silicon (honest negative)
Extended `qin_pack` (experiment-gated, guardrailed, suite green 560/33) to multi-pin own-Q
feedback cells across the direct-D pool, and built two write-HOLD-read banks on the candidate
sites: `write5hold` (5 lanes, +`X15Y8_SLICE12`) and `write6hold` (6 lanes, +`X15Y8_SLICE12` &
+`X14Y11_SLICE8`). Both route + strict-bitgen clean and read back correctly in the routed-netlist
sim (9 / 10 distinct read-values). **On silicon (SRAM) both FAIL:** FCB config loads
(`STAT=0x000f0002`) but readback is stuck — write5 all 5 lanes stuck; write6 lanes 0-4 stuck
**including the four already-qualified sites `X14Y11_SLICE4..7`**, while only lane 5
(`X14Y11_SLICE8`) varied and tracked. Because the *qualified* sites also read stuck in these
images, this is **not** a clean per-candidate-site verdict — it means the widened multi-site
placement / multi-cell observe-F rewiring does not conduct on silicon (config-legal +
sim-correct ≠ conducts). Candidate sites are **not** qualified; no wider write-hold-read bank is
promoted; the `qin_pack` multi-pin change is **reverted** (kept as a local reproducer patch).
Lone positive datum: `X14Y11_SLICE8` tracked in write6 — a lead that individual candidate paths
can conduct while the multi-site arrangement breaks the rest. So the qualified write-hold-read
bank stays at 4 sites, and the wide-writable-state frontier remains open.

### 2026-08-13 — provenance of the 12 still-blocked edges: 11/12 have positive silicon-sweep evidence
Cross-referenced the 12 still-blacklisted edges against the positive conduction CSVs. **11 of
the 12** already carry our-own-silicon-sweep conduction evidence: 9 appear in **both**
`ff2_conduction.csv` (ff2_sweep, FF->FF directed) **and** `harvest_conduction.csv`
(harvest_sweep, pips of conducting designs); 1 in harvest only (`RMUX09@14,4->RMUX28@14,8`);
1 in ff2 only (`RMUX69@14,6->RMUX76@14,10`). Only `RMUX15@(3,4)->RMUX68@(6,4)` rests on
vendor-corpus mining alone (no silicon-sweep hit). With the 2 board-verified edges, that means
**13 of the 14** catalogued "silicon-dead" edges have positive silicon evidence, and the dead
classification rests on the congested-counter negative the reframe already showed to be a
context artifact.

**Discipline held — no bulk un-gate.** These 11 remain conservatively blocked in the shipped
router, consistent with the v0.3.0 STATUS text ("remaining edges stay blocked pending an
isolated per-edge silicon test"). Sweep evidence proves they are *not intrinsically dead*, but
the per-edge un-gate bar this project set is a dedicated isolated test (as done for the 2), not
a bulk sweep. They are now precisely ranked candidates for that board campaign (9 strong: both
sweeps; 2 moderate: one sweep; `RMUX15` is the lone corpus-only holdout).

### 2026-08-13 — write-side silicon (A) + direct-D root cause
Ran the 24-lane write image on silicon (SRAM, non-destructive, board left clean): FCB config
LOADS (`STAT=0x000f0002`) but readback is stuck **0/64 exact, all 24 lanes constant**. Cause:
the desk-built image is "and" mode (`captured <= hwdata & {N{write_data_phase}}`), which does
**not hold** the value into the separate read transaction, so write-then-read cannot observe
it — a design-shape outcome, not a proven mesh-conduction failure. A true write-**hold**-read
needs own-Q self-feedback (direct-D).

Root cause of the 4-wide write-hold-read bank, now pinned in code: `qin_pack.py:184` auto-pins
**only a single** own-Q feedback LUT (`X14Y11_SLICE7`); for >1 it deliberately fail-closes
(*"multiple feedback cells remain unplaced and fail closed until a multi-site pool is
qualified"*), then `_json_admits_direct_d` (`cli.py:249`) rejects the unbound cells. So a wider
writable bank needs BOTH (a) `qin_pack` extended to multi-pin the pool AND (b) **silicon
qualification** of the experiment candidate sites `X15Y8_SLICE12` / `X14Y11_SLICE8`. That
campaign is underway (desk build of 5/6-lane hold banks → silicon verify with the same
`ahb_step_stub`, which reads a *hold* correctly). No wide-write silicon claim is promoted; the
24-lane build remains desk-only.

### 2026-08-13 — write-side probe: the un-gate is NOT a write-width lever (honest negative)
A desk-only build probe (no silicon) tested whether the un-gated corridor edges widen
simultaneous MCU->fabric writes. **They do not.** A single image now routes and
strict-bitgens **24 simultaneous HWDATA write-data lanes** (past the old 8-in-one-image),
but the un-gated edge `X14Y10_RMUX21->X14Y8_RMUX87` is present-but-unused (0 lanes), and a
routing-cone analysis shows it is disjoint from where the write constraint actually binds.
The real write-width limiters are three, none of them the un-gated edge:
1. the own-Q **direct-D placement pool** capped at 4 qualified sites (`X14Y11 slice4-7`) —
   this is what caps the *qualified* write-hold-read register bank;
2. per-lane **entry-cone coverage** at X14Y9 for X13Y9-entry lanes (a pure-write 32 fails
   ~lane 21);
3. the **read-side exit funnel** at X13Y11/12 (co-limiter for write-hold-read above ~24).
So the reframe's payoff is routing *correctness*, not a direct write-width unlock. The
24-lane build is desk-only (routes + strict bitgen); silicon verification and the
direct-D / exit-funnel fronts remain open and board-gated. This keeps the two headlines
distinct: per-edge conduction = artifact (done); wide writes = a separate, multi-front
frontier that the un-gate does not resolve.

### 2026-08-13 — PROMOTED: two board-verified edges un-gated in the shipped router
Cashed the diagnosis out into the deliverable. Removed `RMUX21@(14,10)->RMUX87@(14,8)`
and `RMUX63@(10,4)->RMUX68@(9,4)` from `agamemnon/chipdb/dead_edges_silicon.csv`
(14 -> 12 rows). Both edges are already present in the positive conduction CSVs
(`ff2_conduction.csv`, `harvest_conduction.csv`, `corpus_conduction.csv`) and were
only being stripped by `CONDUCT.difference_update(EDGE_BLACKLIST)` in `routing.py`,
so deleting the blacklist rows makes `is_trusted` admit them with no other code
change. The gate **mechanism** (negative evidence has absolute precedence over
positive attribution) is deliberately unchanged; only the negative-evidence **data**
was corrected. The twelve unverified edges of that date (nine as of 2026-08-14 — see the newest
entries) stay conservatively blocked, now labelled
unverified rather than proven-dead. Reconciled the stale framing in `STATUS.md`,
`FPGA_PARITY_LEDGER.md`, `VENDOR_PARITY.md`, and `ARCHITECTURE.md`, and added the
machine-readable record `qualification/conduction_ungate_evidence.jsonl` (registered
in the evidence manifest; the research-knowledge manifest was re-pinned for the
shrunk CSV). Full suite: **559 passed / 33 skipped, no new failures** (the single
pre-existing `agrv2k.cc` overlay-sync failure is unrelated). Zero regression.

### 2026-08-13 — original 18-bit counter no longer routes the disputed edge; congested repro is router-infeasible
The original 18-bit counter is where the whole `dead_edges_silicon.csv` catalogue
came from (the `silicon_converge` sweep). Faithfully rebuilt today via
`trigger_pull.py build_converged(bit=4)`:
- **It no longer uses `RMUX21@(14,10)->RMUX87@(14,8)` at all.** Today's
  constructive placer (condplace) clusters the counter onto 6 adjacent tiles near
  the MCU exit (X1Y4–X6Y4) and routes through 7 *unrelated* carry hops (e.g.
  `RMUX81@(6,4)->RMUX45@(10,4)`, `RMUX93@(14,4)->RMUX93@(10,4)`), not the disputed
  edge. This holds both with the edge explicitly allowed (Build A) and under
  today's standard full blacklist (Build B): identical placement, disputed edge
  unused in both. So the design that produced the "dead" verdict does not, today,
  even generate the routing need that produced it.
- A deliberately **congested** variant that forces many corridor nets through the
  exact `RMUX21` entry (`force_rmux21_congested.py`: 16 feeders, blacklisting the
  other 15) is **not routable by our flow** — nextpnr-generic livelocks and times
  out at 900 s (EXIT=1). We cannot currently reconstruct the original congested
  composite that produced the dead verdict.

**Consequence:** the per-edge dead verdict for this edge was a
**sparse-conduction-map-era characterization artifact** — further support for
un-gating the individually conduction-verified edges. **But** the genuinely
congested reproduction is **router-infeasible in our own flow** (livelock), so the
aggregate MCU-exit congestion limit is *untested here, not silicon-refuted* — and
is now known to be gated partly by our router's inability to pack that corridor,
not only by silicon. The two headlines stand unchanged: per-edge = artifact
(un-gate carefully); wide/congested payoff = open frontier.

### 2026-08-13 — corridor read-bandwidth: healthy to 13 nets, no degradation
Built + read three designs pushing simultaneous nets through the far-tile->MCU-exit
corridor (the RMUX@(10,4)->BBMUXS@(10,5) chokepoint). 8-net builds (natural AND
LogicLock-forced-far placement) all 8/8 TOGGLING; a 6-group AND-canary detector
(each group = strict conduction-AND of 4 feeders) all healthy; deliberate negative
control read STUCK0 (detector validated). **No degradation up to 13 verified
simultaneous corridor nets.** Could not push higher: af.exe's pre-placement PACKER
clusters coupled cells before LogicLock runs, capping independently-verified far
crossings at ~13 (a tooling ceiling, not a silicon one). So raw net-count <=13 is
NOT the killer, and the original 18-bit *counter* failure (carry-forwarding
pattern) is still not reproduced — its cause is narrower than "N simultaneous
nets." READ-direction only; write-side untested. New reusable technique: LogicLock
LL_ORIGIN works from the native af.exe flow if you target the post-synth atom name
(`macro_inst|syn__NNNN_`), not the RTL net name.

### 2026-08-13 — mechanism pinned: CONGESTION-context, not the edge
Read both taskB relay builds on silicon. `dout`=GPIO4.2 in both. FORCED build
(our nextpnr, blacklist onto `RMUX21@(14,10)->RMUX87@(14,8)`, route-verified the
pip is load-bearing on the qa->qb net) reads TOGGLING; NATURAL control also
TOGGLING. Combined with af.exe-native (deadwit_675) also toggling, the edge
conducts in all three clean/isolated builds. Only the congested 18-bit counter
ever read it dead => the "dead" verdict is a congestion-context artifact
mis-attributed to the edge. Also confirmed our bitgen encodes both hops
byte-exact vs the conducting vendor bitstream (no sel-encoding bug). Forced
single-edge build of RMUX63 was NOT constructible (arch models only 4 BBMUX-dest
pips) — a toolchain coverage gap, and further evidence the original verdicts came
from congested composite designs, not clean per-edge tests.

### 2026-08-13 — mechanism contrast running
Same-edge forced-vs-native experiment on `RMUX63` on the board; bitstream diff to
follow. A stray lucky-seed sweep (a prior agent's runaway background job) was
found colliding for the board and was stopped cleanly via the task harness; no
data lost (it had already produced the 2/2 result). Board serialized to one
agent.

### 2026-08-13 — 2/2 native conduction confirmed
`RMUX63@(10,4)->RMUX68@(9,4)` read TOGGLING on silicon in an af.exe-native build
(seed 754), joining `RMUX21@(14,10)->RMUX87@(14,8)` (seed 675). Both catalogued
"dead"; both conduct natively. Lucky-seed sweep (~180 builds) reached only these
two of the 14.

### 2026-08-13 — first board proof
An af.exe-native bitstream carrying a live toggling signal through the catalogued
"dead" edge `RMUX21@(14,10)->RMUX87@(14,8)` read TOGGLING on silicon, reproduced
3x with a valid control. First hard evidence that a "dead" verdict was a
forcing/context artifact rather than intrinsic silicon.
