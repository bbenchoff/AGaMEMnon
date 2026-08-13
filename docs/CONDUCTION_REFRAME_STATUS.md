# Conduction reframe — live status

Live progress log for the investigation into whether the AG32's catalogued
"silicon-dead" routing edges are genuinely dead or an artifact of our own
characterization method. Newest entry on top. This is a research log, honestly
caveated; the authoritative support ledger remains [STATUS.md](STATUS.md), and
the narrative is [AF_EXE_REVERSE_ENGINEERING.md](AF_EXE_REVERSE_ENGINEERING.md).

Confidence discipline: this line has produced confident-but-wrong conclusions in
*both* directions already, so nothing here is promoted to STATUS.md or acted on
in the shipped router until it is board-verified with a valid control.

## Current headline (2026-08-13)

**Board-verified, reproduced:** 2 of 2 catalogued "silicon-dead" edges that we
could route to naturally — `RMUX21@(14,10)->RMUX87@(14,8)` and
`RMUX63@(10,4)->RMUX68@(9,4)` — actually **CONDUCT** when af.exe's own free router
uses them (live toggling signal read at the MCU dout, control lane valid,
reproduced across runs). Our original "dead" verdicts came from a sweep that
*forced* the edge by blacklisting its alternatives; the forcing, not the edge,
appears to be what kills conduction.

**Calibrated:** that is 2 of 14 catalogued edges. Random-seed sweeping only ever
reaches ~2 of the 14 (af.exe rarely volunteers a specific one), so a
placement-aimed method is needed to size the artifact rate across the rest. Not
yet "all edges are artifacts" — that claim is unearned until the broad reads land.

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
