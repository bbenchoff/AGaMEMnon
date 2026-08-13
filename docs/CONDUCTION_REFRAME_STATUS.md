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
3. **Promote (only if it holds)**: un-gate the *conduction-verified* edges in the
   open router (never a forced verdict again), zero-regression, commit + push.
4. **Dive**: the wide MCU-boundary surface the extra corridor bandwidth should
   unlock — fabric AHB master, full 32-bit writes, the full request phase — since
   those are gated on "simultaneous wide routing across the MCU exit," which is
   exactly the corridor these edges live in.

## Log

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
