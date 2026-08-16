# MCU ↔ fabric External-AHB interface, and the path to wide transfers

This note documents the AG32 MCU↔fabric External-AHB boundary and the design
path to *wide* (full-word) MCU-AHB in the open flow. It is a **design/interface
reference derived from studying the vendor toolchain**, not a qualification
claim. What is actually silicon-qualified today is enumerated in
[`STATUS.md`](STATUS.md); this note never widens those claims. Anything not
qualified there remains fail-closed.

## The boundary contract

The AG32's RISC-V core is a hard block (`alta_rv32`). It exposes AHB to the
fabric through **named ports** that a fabric design binds to on the same nets —
there is no physical IO in this path; it is an internal fabric↔MCU edge:

| Port group | Direction | Meaning |
|---|---|---|
| `mem_ahb_*` | MCU master → fabric slave | the MCU reads/writes a fabric-resident slave (the "register bank" / External-AHB window at `0x60000000`) |
| `slave_ahb_*` | fabric master → MCU slave | a fabric master reads/writes MCU SRAM |
| `ext_dma_*` | both | DMA request/ack lines |
| `local_int` | fabric → MCU | fabric-sourced local interrupts |

A protocol-valid MCU write drives `mem_ahb_hwrite` + `mem_ahb_htrans[1]` in the
address phase and the 32-bit `mem_ahb_hwdata` in the completing data phase; the
slave returns `mem_ahb_hreadyout`/`mem_ahb_hresp` and, for reads, drives all 32
`mem_ahb_hrdata` lanes. The clock edge that matters for data capture is the
fabric bus clock, not the system clock.

## What is silicon-qualified today (open flow)

Per `STATUS.md`: single-transaction 32-lane HRDATA **read** (all lanes
simultaneously); protocol-valid 32-lane **write** proven in 4-bit groups (every
lane individually); an 8-bit writable register bank (ID/scratch/counter/W1C
status) with an inserted write-wait and **exact zero-extended 32-bit reads**
(all upper HRDATA lanes explicitly driven); **aligned byte and halfword
semantics** with simultaneous `HADDR[1:0]` logic ingress; fail-closed rejection
of every non-SINGLE HBURST encoding; `bus_clk = sys_gck` delivery; and fabric
local-interrupt routing/cause. Misaligned CPU accesses fault deterministically
in the hard core (mcause 5/7) and never reach the fabric. Hard `MCU_RESETN`
and wider public-bank integration remain **out / fail-closed**; deterministic
HRESP-to-MCU faults are retired on L48.

## The vendor idiom for a *wide* MCU-AHB slave

The vendor's shipped `ahb_slave` example is the canonical wide interface: a
fabric IP that wraps the boundary ports around a true-dual-port memory. Its
structure is a four-bridge chain around one dual-port RAM —
`ahb2apb` (bus-clock crossing + `hreadyout` back-pressure) → `apb2ram`
(byte-enabled APB→SRAM) → RAM port A; RAM port B → `ram2apb` (a DMA engine) →
`apb2ahb` (a master into MCU SRAM). Three things make it place at scale:

1. a **boundary wrapper** binding exactly `mem_ahb_*`/`slave_ahb_*`/`ext_dma_*`/
   `local_int` (generated around the fixed `alta_rv32` + `alta_pllve`);
2. a **spreading floorplan** — a reserved LogicLock-style region for the core
   logic near the MCU edge (not a single tile);
3. **clock-domain-crossing constraints** (`SYSCLK`/`BUSCLK` multicycle) for the
   sys↔bus boundary.

Driving the real vendor back-end through this design, synthesis + packing reach
~84% fabric (≈1,800 logics across ~120–130 tiles) — so a wide MCU-AHB slave is
**placeable in principle; fabric capacity and MCU-edge corridors are not the
limit.** The vendor's sanctioned route to a bitstream pre-packs the netlist with
its Quartus fork into back-end-native atoms, which sidesteps a net-inversion /
async-control legalization step the raw yosys→back-end path cannot do.

## The open-flow path to wide MCU-AHB

The open flow does **not** use that Quartus pre-pack; the `agrv2k` nextpnr placer
is precisely the component that performs the legalization the vendor offloads to
Quartus. So the open path to full-word MCU-AHB is:

1. reproduce the boundary wrapper (the named-port contract above);
2. a spreading placement over the MCU-adjacent tiles (not the single-tile
   default);
3. sys↔bus CDC handling;
4. **MCU-edge routing-corridor coverage** in the strict conduction graph.

Item 4 remains a major limiter. The retained exact L48 checkpoint now proves a
**simultaneous 16-of-16-lane posted capture** on silicon: sixteen unconditional
bus-clocked HWDATA captures return on their matching HRDATA lanes across 64
protocol-valid write/read patterns. It has zero own-Q cells and one shared write
decode. This is deliberately narrower than a register bank: it retains data only
through the tested write-to-read turnaround and does not qualify address decode,
commit/wait/W1C behavior, reset, or arbitrary placement. The complete qualified
writable public bank remains eight bits. That posted-capture checkpoint is hash-pinned in
`qualification/mcu_ahb_posted_capture16_routed.json` and now replays exactly
from source: 58/58 BELs and 39/39 per-net PIP sets match, selector debt is zero,
and the emitted image is byte-identical to the silicon-qualified payload. This
is exact checkpoint replay, not arbitrary 16-lane placement. Corridors are recovered from vendor route
witnesses (`place.tx` cell→tile, routed-design pips, decoded image) and admitted
through the standard hash-gated review; they never enter as a silicon/behavioral
claim without their own qualification.

The next checkpoint supersedes that capture-only frontier without changing the
public profile. `mcu_ahb_register_bank16_external_feedback_waited` inserts the
qualified write wait and gives each of the sixteen low lanes an external
LUT-buffer feedback path. On L48 it passed 100 aligned word patterns with zero
immediate, SRAM-churn-retention, or repeated-read errors; GPIO4.1 reset cleared
all lanes. The retained route repacks byte-identically and a hard qualified-
checkpoint replay emits the same image. This is one exact **16-bit held
scratch**, not a complete 16-bit register bank. A deterministic retained-route
composition additionally proves that writes to aligned offsets +4, +8, and +c
do not alter the word at +0. A further exact composition adds independent byte
+0/+1 and aligned halfword +0 storage while rejecting byte +2/+3 and aligned
halfword/word foreign offsets. The read-gated derivative qualifies low-16
aligned word reads at +0/+4/+8/+c as `[state, 0, 0, 0]` through a ten-run causal
matrix. Three repeated SRAM-only runs additionally qualify CPU-visible aligned
unsigned `LBU +0/+1` and `LHU +0` lane selection and zero extension; upper-lane
subword selections matched the same raw word. A hash-bound two-INIT derivative
moves the exact scratch to public offset +4 and passes three complete runs of
word/halfword/byte writes, decoded reads, foreign-offset rejection, retention
and reset. The later exact public16 profile composes that storage spine with
ID8, counter3, and W1C1 in four passing SRAM-only runs. Misaligned and signed
loads, raw HRDATA[31:16], canonical 32-bit identity, production status-set
ingress, higher/full-window decode, bursts on that composition, arbitrary
placement/width, other packages, and a generic 32-bit ABI remain unqualified.

The hard HSIZE[1] signal is no longer merely catalogued. A retained exact
BufMUX04-to-InputMUX05-to-RMUX34-to-IMUX14 corridor drives an identity LUT and
returns one for 256 word reads and zero for 256 halfword plus 256 byte reads at
a fixed address. The generic relative RMUX selector was wrong; the engine now
owns the vendor-measured `CFG_RMUX5 {42,48}` codeword. This qualifies one live
control corridor. The exact held checkpoint separately composes HSIZE[1:0],
HADDR[1:0], HTRANS and HWRITE into qualified aligned word/halfword and byte
storage semantics; neither result implies free placement.

**Scope:** this note is interface documentation and a design path. Byte and
halfword semantics, zero-extended word-read completion, and non-SINGLE burst
rejection are qualified in the register-bank ledger; wide (32-bit writable)
MCU-AHB, `MCU_RESETN`, and error signaling stay fail-closed until separately
qualified; misaligned CPU accesses are characterized as hard-core faults that
never reach the fabric.
