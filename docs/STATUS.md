# Supported feature matrix

> Status freshness notice (2026-09-06): the dated campaign counts and defect
> diagnoses below are historical snapshots, not current fence totals. At this
> branch's base `ea4d502f0c4d2d6dc300822c7ee06978bd35164e`, the executable
> registry contains **41 image fences and 31 logical-design fences: 72 entries
> across 16 defect IDs** (VP-AGM-001, 003�009, 012�019). Containment is not repair.
> No fences were removed by this documentation correction. Experimental branch
> results and newer campaign ledgers require their own revision and evidence
> binding; the old eight-ID table must not be used as a current scoreboard.


This is the authoritative public support boundary as of 2026-08-25. A feature
is supported only at the scope stated here and in its cited qualification row.
Decoded fields, successful placement, a valid CRC, FCB acceptance, a clean
strict-pack report, and even a correct routed logical model are individually
useful evidence; none alone proves correct silicon behavior.

## Evidence terms

| Term | Meaning |
|---|---|
| **Silicon-qualified exact subset** | A hash-bound image or composition passed an observable contract on the named part, package, board, route, clock, and mode. |
| **Build-supported** | The public flow is expected to build and its offline checks pass; this is not a board-behavior claim. |
| **Recovered only** | Data or an experimental path exists but release support has not been admitted. |
| **Fail-closed** | The production path deliberately refuses a demonstrated or unresolved surface. |
| **Correctness escape** | AGaMEMnon emitted a clean image that failed a preregistered model-backed silicon contract. |

The generated [FPGA parity ledger](FPGA_PARITY_LEDGER.md) and
[claim-policy ledger](CLAIM_POLICY_LEDGER.md) provide the feature-level view.
The normalized evidence gate currently validates **64 ledgers / 653 records**.

## Release health

The parity-gap-closure baseline full test run is:

```text
1457 passed, 49 skipped, 0 failed
```

The exact public32 composer now reproduces the existing reviewed checkpoint by
replaying its reviewed status-pending branch and revalidating every hop against
the current strict graph and wire owners. No route, image, or reviewed hash was
moved. A future candidate mismatch remains a hard review gate under
[LANDING_A_CHIPDB_CHANGE.md](LANDING_A_CHIPDB_CHANGE.md); it must not be repinned
merely to keep this count green.

The focused routing, selector, research-manifest, D0, MCU, and evidence checks
pass. The demonstrated correctness escapes are **RELEASE-SAFE**: containment is
met, so no retained known-wrong image or route-independent logical fingerprint
can ship. This does not make a mostly green test suite a universal silicon
proof; root-cause work remains hardware-gated.

Strict bitgen also refuses 17 byte-exact canonical images with retained
silicon-negative results, covering open defects `VP-AGM-001` and `VP-AGM-003`
through `VP-AGM-009`. The check runs after CRC generation and before output is
written, under every emission policy. Before any selector table is read, a
second registry refuses seven exact synthesized logical graphs for retained
`VP-AGM-001`/`003`/`004`/`005`/`008`/`009` failures. That projection excludes
placement and routing annotations, so rerouting the same graph cannot bypass
the negative. Across the 13 benchmark escapes, the byte-exact and
route-independent fingerprint fences contain 13/13 demonstrated negatives,
with zero fingerprint collisions across 73 retained routes. Containment is the
release-safety gate and is met. Root cause is a separate hardware-gated track:
0/13 are fully root-caused, without weakening release safety. A changed logical
graph or other configuration remains subject to its own support gate and
silicon qualification.

## 105-design parity campaign

The controlled campaign used fixed contracts, independent models/adapters,
fresh vendor references where usable, release-strict open images, and
control-first SRAM-only board sessions. It closed with:

| Verdict | Designs |
|---|---:|
| Parity success | 25 |
| Vendor reference failed | 10 |
| Vendor unstable | 2 |
| AGaMEMnon routability gap | 52 |
| AGaMEMnon correctness escape | 13 |
| Harness incomplete | 3 |
| **Total** | **105** |

### Post-campaign update, 2026-09-02: two escapes were route-dependent

Two of the thirteen correctness escapes have since been **re-qualified**, taking the campaign's
escape count to **11**:

| design | defect | outcome |
|---|---|---|
| `area_a_rotate4_user` | VP-AGM-004 | passes 3/3, signature `0x03c1ebf2` exact |
| `area_a_addsub1_user` | VP-AGM-005 | passes 3/3, signature `0x955559ec` exact |

Neither needed an RTL or a lowering change. Rebuilt unchanged with
`--top top --uarch --release-strict --freq 10` at this repository's `main`, in a clean worktree,
both match their preregistered mailboxes exactly in control-first SRAM-only board sessions. Both
retained escape images had simply chosen a route that did not deliver; the current router chooses
differently.

Two consequences worth carrying forward:

- **The external-D lowering is exonerated for these designs.** Their retained diagnoses attributed
  the failure to composing synchronous control into D-path logic instead of the vendor's native
  `SyncReset`. The identical lowering computes the right answer when the route delivers, and
  external-D synchronous clear was separately silicon-witnessed correct the same day.
- **Tier-1 admission is not sufficient inside the fabric.** Both escape images were
  `--release-strict`, so every edge they used carried position evidence, and they still did not
  deliver. That is a stronger statement than the MCU-boundary result in
  [MCU_BOUNDARY_TIER_EVIDENCE.md](MCU_BOUNDARY_TIER_EVIDENCE.md), where tier-1 chains delivered
  12/12 — release-strict is necessary at the boundary but is not a guarantee internally.

The `silicon_negatives` fences for VP-AGM-004 and VP-AGM-005 are **unchanged**: they are bound to
the old image hashes, and those images are still silicon-wrong.

Paired user/structural parity passed for 6 of 51 attempted structural forms:
SPI0 TX, SPI1 TX, I²C0, I²C1, UART1 TX, and UART2 TX. The designs were
hand-authored boundary vehicles and the sealed holdout set was **n=0**. The
result is high-value defect discovery and narrow proof, not a parity rate for
unseen RTL. Full definitions and exclusions are in
[VENDOR_PARITY.md](VENDOR_PARITY.md).

## Release flow

```text
Verilog
  -> Yosys technology mapping
  -> generated AGRV2K device database
  -> nextpnr
  -> strict bitgen
  -> uncompressed SRAM image + compressed flash image
```

The design-neutral body, 164-byte preamble, feature overlays, compression, and
CRC are generated openly. `fabric_default.bin` remains only as a stale-CRC,
non-loadable decode reference and differential anchor. The generated base is
byte-exact to the decoded body and has configured the L48 FCB successfully.
This proves base generation and configuration acceptance, not the behavior of
every design overlay.

`agamemnon build --uarch` uses the tiered routing model: witnessed edges and
encoding-certain edges are exposed, ambiguous selectors are refused, and tier-2
use is recorded in `<output>.confidence.json`. `--release-strict` limits routing
to exact witnessed admissions. Both modes still depend on the per-feature
gates below; neither is a general correctness certificate.

## Support matrix

| Surface | Current public state | Exact boundary and principal exclusions |
|---|---|---|
| LUT4 / local combinational logic | Silicon-qualified exact subsets | Multiple small Boolean, shift, add/subtract, fanout, and handshake vehicles pass. FSM, rotate, feedback, and dense compositions have open correctness escapes; no arbitrary-RTL claim. |
| Flip-flops / state | Silicon-qualified exact subsets | Small counters, LFSRs, selected direct-D footprints, and retained exact designs pass. Reset/update and five-region state escapes show that generic state placement is not qualified. |
| General routing | Partial, fail-closed by selector evidence | Large conflict-free physical and unanimous-relative selector corpora are available. Coverage of observed corpus rows is not coverage of all device routes; 52 campaign vehicles did not route. |
| Dedicated carry | Silicon-qualified exact subsets | Qualified same-tile short chains, one X20 33-site corridor, and one exact inter-tile seam. Other columns, seams, placements, branching, and large compositions remain open. |
| External AHB slave | Silicon-qualified exact subsets | Full HRDATA corridor recovery, exact constant endpoints, retained byte/16-bit banks, local-interrupt commands, and one reviewed public32 map. Its composer reproduces that immutable reviewed checkpoint; this does not qualify a fresh candidate. Generic banks, wider fresh state, higher/full-window decode, misaligned/signed access, broad burst behavior, hard reset, alternate bus clocks, arbitrary placement, and AHB master/DMA remain open. |
| Fabric local interrupts | Silicon-qualified exact subset | One exact four-cause command composition delivers local causes 16–19 with mask/ack/set and synchronous reset behavior. Generic pending banks, hard reset, alternate clocks, and asynchronous sources remain open. |
| Physical outputs | Silicon-qualified exact L48 subsets | Exact top-edge/left-edge routes and current campaign outputs on PIN_12/PIN_16. This does not qualify arbitrary routes, electrical modes, bidirectionality, or other packages. |
| Physical inputs | Mixed exact evidence; generic path not qualified | Several earlier retained exact L48 input demonstrations pass. The campaign's independent PIN_10 and PIN_12 held-input compositions both stayed low despite correct routed logic; they remain `VP-AGM-008`. Do not transfer an exact-path result to a new ingress composition. |
| Bidirectional/OE | Silicon-qualified exact subsets | Selected PIN_25–PIN_28 OE corridors and exact I²C0/I²C1 open-drain routes pass. Generic direction changes, broad simultaneous readback, electrical/PVT margins, and other pins remain open. |
| BRAM | Narrow retained exact profiles; affected modes fail closed | Selected X13Y4 read/write replays and exact corridors have prior evidence. New initialized x1 and x18 Port-A vehicles preserved modeled INIT/config fields but read zero on alternate output routes (`VP-AGM-006`). The two demonstrated static/read profiles now refuse. No arbitrary site, width, port, clock, write, collision, or inference claim. |
| PLL output frequency | Silicon-qualified bounded subset | With an 8 MHz HSE, 43 requested SYSCLK rates from 4–248 MHz were measured and locked; two additional byte-exact profiles require unavailable 12/16 MHz HSEs. Phase, duty, feedback/bypass, other outputs, other HSEs, and distribution to arbitrary state remain open. |
| Clock reach / regions | Correctness escape outside exact points | A matched PLL/shift point passes, but a five-site registered design spanning far regions produced zero state despite a correct routed model (`VP-AGM-007`). The exact five-tile constellation now refuses at its tested 100 MHz / 8 MHz profile even if routing changes; this is not evidence that every route is dead or that the PLL divider is wrong. Other constellations and profiles remain unqualified. |
| Timing | Conservative estimate, not sign-off | Exact timing overlays exist for a bounded local subset; most wires retain worst-family fallback. Clock skew, IO, BRAM, PLL, package, broad PVT, and complete Fmax behavior are not modeled. |
| Packages | L48 exact; other maps recovered/build-only | L100, L64, L48, and Q32 bond maps exist. Silicon qualification is primarily AG32VF303CCT6/L48; no qualification transfers by package pin number. |
| Analog boundary | MCU/register subset only | Selected ADC/DAC/comparator register and loopback observations exist, but the public bitgen does not emit the vendor analog macro. External analog behavior, calibration, scanning, DMA, and broad comparator modes are open. |
| Programming | Qualified transport subsets | Volatile DAP loads, L48 flash backup/program/verify, and the installed USB CDC uploader have exact evidence. Persistent writes remain opt-in and require backup/verify; UART mask-ROM target wiring is not fully qualified. |

The HRESP-to-MCU-access-fault claim is RETIRED. The exact two-cycle response
was electrically active, but the attached MCU reported zero load or store access traps;
the response phase crossed into the following transfer. This does not weaken
the protocol core's fail-closed handling of unsupported transfers; it means
HRESP is not claimed as a deterministic MCU exception mechanism on this target.

The historical conduction campaign remains closed at its exact denominator.
**Current production count: 14 of 14 admitted; 0 conservatively blocked as
unverified.** This says those 14 catalogued edges conduct in bounded witnesses;
it does not qualify arbitrary routing or the congested composition that first
misclassified them.

Two older IO claims remain intentionally explicit alongside the newer
`VP-AGM-008` counterexamples:

- **PIN_12 is qualified only as a scalar single-consumer direct combinational input**
  in its retained inversion composition. New held-input compositions
  on PIN_12 and PIN_10 fail, so the exact claim does not generalize to fanout,
  registered capture, or another route.
- PIN_25 dynamic OE is qualified through one local-self-toggle corridor, and
  stepped external PIN_10 control plus simultaneous readback is qualified
  through the exact RMUX15 entry. High-rate readback remains unqualified, as
  does the divergent RMUX20 branch.

## Hard peripherals and current campaign boundary

Hard peripherals use MCU MMIO but still depend on exact fabric-to-pad routes.
The table therefore separates controller behavior from physical-route breadth.

| Peripheral | Qualified exact subset | Not qualified / refused |
|---|---|---|
| UART | UART0 internal loopback; retained UART0 PIN_30/PIN_31 application duplex; campaign UART0/1/2 TX on L48 PIN_10 at nominal 9,600/38,400/115,200, with fixed payload/framing contracts | UART3/4 TX; campaign RX for UART0–4; arbitrary framing/payloads; flow control, break, interrupt/DMA, other pads/packages, PVT, absolute reference-clock accuracy |
| SPI | SPI0 and SPI1 TX, fixed mode-3/MSB-first/active-low-CS contracts, 1–4-byte cycles, documented dividers, and direct raw TX-register byte order on exact L48 routes | Typed SPI0/SPI1 MISO is **fail-closed** under `VP-AGM-008`: paired duplex images returned `0xffffffff` while vendor images and the external slave passed. No generic RX/duplex, dual/quad, DMA/POLL/interrupt, other modes/pads/packages, PVT, or absolute SCK claim. An older retained exact SPI0 receive image is evidence only for that immutable composition, not permission to emit a new typed MISO route. |
| I²C | Exact I²C0 and I²C1 address-`0x55` write `2A A6`, repeated START, read `5A C3 7E`, ACK/ACK/NACK, STOP on PIN_11/PIN_15; I²C0 also has one four-point 500 us stretch profile | 10-bit addressing, arbitration/multimaster, arbitrary lengths, simultaneous controllers, interrupt/DMA, longer/unbounded stretching, electrical/timing margins |
| CRC | CRC-32/MPEG-2 `123456789` known answer | Other polynomial/width/reflection modes |
| DMA | One DMAC0 four-word SRAM copy | Peripheral-linked, chained, or broader DMA |
| Watchdog | Disabled-state snapshot and supervised warm reset | Broader watchdog modes |
| CLINT timer | One machine-timer interrupt with `mcause=0x80000007` | Complete interrupt/timing behavior |
| RTC | Configuration/readback path | Timekeeping: no qualified low-speed clock |
| CAN | Register/config/transmit-state observations only | No bits observed on a transceiver-backed wire; no protocol claim |
| USB | Flash-resident CDC device uploader | Host/OTG and ROM-USB recovery |
| Ethernet | Register data only | MAC/PHY operation; no PHY fixture |

## Open correctness defects

| ID | Surface | Observed boundary |
|---|---|---|
| `VP-AGM-001` | MCU ALU feedback | Model and adapters agree; open silicon diverges at a read-data feedback composition. |
| `VP-AGM-003` | FSM update | Vendor follows the model; open silicon loses one next-state bit at step 16. |
| `VP-AGM-004` | Rotate/reset execution | Exact selector recovery did not repair a four-bit rotate vehicle that fails before command-space qualification. |
| `VP-AGM-005` | One-bit add/sub reset | User and explicit-carry images share the wrong reset snapshot. |
| `VP-AGM-006` | BRAM read path | Initialized x1 and x18 exact-config vehicles read zero; affected production profiles refuse. |
| `VP-AGM-007` | Wide clock/state reach | Five placed registers remain zero although the routed logical discriminator is correct. |
| `VP-AGM-008` | Physical ingress / SPI MISO | PIN_10/PIN_12 inputs stay low and SPI0/SPI1 MISO stays high in the tested compositions. Typed SPI MISO refuses. |
| `VP-AGM-009` | 256-bit state/density | The user form routes on attempt 13 and matches the routed model, then diverges on silicon at transaction 2; the artifact is excluded from qualification. |

`VP-AGM-002` is narrowly closed for UART0 TX/PIN_10 by an exact selector
correction. `VP-AGM-010` is narrowly closed for the qualified SPI TX API by a
lane-packing correction. Neither closure generalizes to neighboring routes or
modes.

## Routability and the wide-MCU frontier

The campaign's dominant result is 52 clean no-image outcomes. The router is
not merely missing one last selector table: user and structural rewrites often
have very different feasibility, and apparently modest width/density changes
can exhaust the current graph or placement policy.

The wide MCU frontier is bounded as follows:

- the ingress / X13Y12 coverage problem has exact solutions;
- a fresh wider `regbank16` composition still emits no image;
- a wide `addsub16` reaches the density policy but shows placement divergence;
- a 256-bit user state vehicle routes only after 12 failures and is then wrong
  on silicon, while its structural counterpart does not route.

No design-specific route pin, unsafe selector admission, timeout relaxation, or
hash repin is an accepted closure. The next step is generalized placement,
routing, and physical-correctness work with independent silicon controls.

## SERV scope

`serv-blinky` is a retained, hash-bound exact route and loader. It is useful as
an immutable replay and CPU-scale integration example. The campaign did not
establish fresh arbitrary SERV parity: fresh-source variants were either not a
qualified parity harness or remained bounded by current placement/routing and
BRAM limits. The retained result is not RV32I compliance, arbitrary direct-D
placement, generic BRAM write support, or proof that a newly routed SERV image
will work.

## What is explicitly not claimed

- no statistical parity rate or sealed-holdout result;
- no arbitrary Verilog, placement, route, clock, BRAM, or IO correctness;
- no broad equivalence to the vendor back-end;
- no silicon qualification for other packages by inheritance;
- no guarantee that FCB acceptance or a clean strict-pack report implies
  functional behavior;
- no authorization to use research-unsafe images as release artifacts.

For the investigation record, see
[AF_EXE_REVERSE_ENGINEERING.md](AF_EXE_REVERSE_ENGINEERING.md),
[CONDUCTION_REFRAME_STATUS.md](CONDUCTION_REFRAME_STATUS.md), and
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). For unfinished work, see the
top-level [ROADMAP.md](../ROADMAP.md).
