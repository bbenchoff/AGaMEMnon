# Conduction reframe — live status

Live progress log for the investigation into whether the AG32's catalogued
"silicon-dead" routing edges are genuinely dead or an artifact of our own
characterization method. Newest entry on top. This is a research log, honestly
caveated; the authoritative support ledger remains [STATUS.md](STATUS.md), and
the narrative is [AF_EXE_REVERSE_ENGINEERING.md](AF_EXE_REVERSE_ENGINEERING.md).

Confidence discipline: this line has produced confident-but-wrong conclusions in
*both* directions already, so nothing here is promoted to STATUS.md or acted on
in the shipped router until it is board-verified with a valid control.

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
   per-edge conduction-gating is therefore over-restrictive, and our own bitgen
   already encodes these edges byte-exact (verified).
2. **But congestion at the MCU-exit corridor is a real, aggregate limit** — that
   is genuinely where conduction failed. So un-gating individual edges is
   justified, yet it does **not** by itself guarantee that *wide, congested*
   designs (fabric AHB master, full-word MCU writes) conduct. Wide-congested
   conduction is the true open frontier, and it needs its own silicon test plus a
   fuller BBMUX-corridor arch model (the current one hardcodes only 4 exit pips).

**Calibrated:** 2 of 14 catalogued edges individually tested; the *mechanism*
(congestion mis-attribution) is well-supported, the *magnitude* across all 14 is
not yet measured. No "all edges are fine" claim, and no "wide designs will now
work" claim — both are unearned until tested.

## Plan (in order)

1. **Mechanism** (in progress): rebuild the *same* edge the forced/blacklist way,
   confirm it reads STUCK while native conducts (same edge, opposite results =
   the verdict is a method artifact), and diff forced-vs-native bitstreams to
   expose exactly which neighbor/companion configuration the blacklist strips.
2. **Broad scope**: LogicLock-aimed builds to route each of the remaining 12 dead
   edges deliberately (no blacklist), read each -> the real artifact rate.
3. **Promote** — DONE (2026-08-13): the two board-verified edges are un-gated in the
   shipped router; see the top log entry. A forced verdict was never promoted as
   conduction — the forced build only proved the pip is load-bearing, while the
   *natural* and *native* builds carry the positive evidence. Zero-regression, pushed.
4. **Dive**: the wide MCU-boundary surface the extra corridor bandwidth should
   unlock — fabric AHB master, full 32-bit writes, the full request phase — since
   those are gated on "simultaneous wide routing across the MCU exit," which is
   exactly the corridor these edges live in.

## Log

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
was corrected. The twelve unverified edges stay conservatively blocked, now labelled
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
