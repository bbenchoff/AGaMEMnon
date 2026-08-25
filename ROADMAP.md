# Roadmap

AGaMEMnon's next phase is correctness and breadth, not a declaration of full
vendor parity. The 2026-08-24 campaign produced narrow silicon proofs and a
larger set of precise failures: 25 parity successes, 52 routability gaps, and
13 correctness escapes among 105 hand-authored designs, with no sealed
holdout. [STATUS.md](docs/STATUS.md) is authoritative for current support;
this file lists unfinished work.

## P0: restore a review-clean release boundary

1. **Review the public32 checkpoint drift.** The current full suite has two
   protected failures because the public32 candidate hash no longer matches
   the reviewed artifact. Follow
   [LANDING_A_CHIPDB_CHANGE.md](docs/LANDING_A_CHIPDB_CHANGE.md): inspect the
   semantic route/config delta, reproduce the board contract if the candidate
   is intentional, and change the reviewed hash only after that evidence. Do
   not repin merely to obtain a green suite.
2. **Turn demonstrated silent-wrong families into explicit refusals.** Typed
   SPI0/SPI1 MISO and affected initialized-BRAM profiles already fail closed.
   Add similarly generalized pre-emission guards when the identifiable trigger
   for `VP-AGM-001`, `003`–`005`, `007`, and `009` is known. Until then, keep
   their artifacts excluded and the surrounding support claims exact.
3. **Keep evidence release-clean.** Every qualification update must preserve
   append-only ledgers, deterministic manifests, path-leak checks, authorship,
   board identity, volatile-first execution, and final reset/restoration.

## P1: explain the correctness escapes

These defects survived clean synthesis/routing, strict selector accounting,
byte-identical repack, and model-backed checks. They are therefore higher
priority than adding adjacent examples.

| Defect | Next discriminating work | Required closure |
|---|---|---|
| `VP-AGM-001` feedback | Isolate the MCU read-data feedback composition with matched placement/route A/Bs and an independent observable | General cause and emitter/router repair; original contract passes |
| `VP-AGM-003` FSM | Trace the missing `fsm_state[0]` update across clock, data, and cell configuration with a minimal sensitized vehicle | Exact failure mechanism, permanent regression, silicon pass |
| `VP-AGM-004` rotate | Separate reset/startup from rotate datapath behavior; keep the already-corrected selector exonerated | Repair that generalizes beyond one image |
| `VP-AGM-005` add/reset | Minimize the wrong reset snapshot across default-LUT and hard-carry forms | Shared reset/update cause identified and fixed |
| `VP-AGM-006` BRAM | Differentially recover the missing static/read-path field or prove the alternate output corridor causal | x1 and x18 contracts pass from fresh strict builds before read profiles reopen |
| `VP-AGM-007` clock reach | A/B clock/data delivery by region with the same five fixed sites and correct routed discriminator | Region/clock mechanism plus generalized placement/emission rule |
| `VP-AGM-008` ingress | Recover the complete pin-specific input chain and separate physical pad enable from route conduction | Held PIN_10/PIN_12 and typed SPI0/SPI1 MISO contracts all pass before generic ingress reopens |
| `VP-AGM-009` density | Reduce the 256-bit divergence while preserving the transaction-2 failure; test clock/power/routing-density hypotheses | Generalized remedy that passes the exact 1,024-transaction contract |

No raw bitstream surgery, design-specific route pin, target relaxation,
unreviewed selector admission, or test-hash repin counts as a fix.

## P2: make wide MCU/fabric designs route and remain correct

The X13Y12 ingress coverage gap is solved, but the next width step is not:

- `regbank16` remains a bounded no-image result downstream of the recovered
  ingress;
- `addsub16` reaches the intended density policy but exposes placement
  divergence;
- the user 256-bit state vehicle required 13 attempts and then failed on
  silicon; the structural rewrite produced no image;
- the retained public32 map is an exact replay, not a generic bank generator.

Work in this order:

1. add deterministic placer diagnostics for resource/corridor pressure and
   explain why user/structural equivalents diverge;
2. improve legal placement and negotiated routing without admitting ambiguous
   selectors or overfitting a single design;
3. qualify fresh simultaneous HWDATA/HRDATA state beyond the retained 16-bit
   scratch footprint;
4. add reservation-aware application overlays around the exact AHB core;
5. pursue AHB master/DMA only after wide slave state is repeatable and correct.

## P3: peripheral breadth

The campaign closed TX and one repeated-START transaction, not whole
controllers.

- **UART:** UART3/4 TX; RX campaigns for UART0–4; framing variants, break, flow
  control, FIFO pressure, interrupt/DMA, clock accuracy, alternate pads and
  packages.
- **SPI:** repair physical MISO first; then RX/duplex, modes beyond the current
  fixed contract, dual/quad, DMA/POLL/interrupt, simultaneous controllers,
  timing/PVT, and alternate pads.
- **I²C:** broader lengths, STOP-delimited sequences, I²C1 stretching,
  longer/unbounded stretch, 10-bit addressing, arbitration/multimaster,
  simultaneous I²C0/I²C1, interrupts/DMA, and electrical margins.
- **GPIO/IO:** general ingress and bidirectional direction changes; per-pin
  pulls, drive strength, slew, Schmitt behavior, voltage banks, and other
  packages.
- **Remaining hard blocks:** timers, CAN with a transceiver, USB host/OTG,
  Ethernet with a PHY, ADC/DAC external analog fixtures, comparators, RTC with
  a low-speed clock, and peripheral-linked DMA.

Every new family needs a fixed observable contract, independent model where
applicable, fresh controls, multiple vendor seeds or an explicit unusable
reference verdict, fresh open builds, and exact scope exclusions.

## P4: fabric hard blocks and clocking

- Recover and qualify the BRAM static/read surface before adding modes.
- Extend BRAM sites, widths, ports, address range, writes, mixed widths,
  independent clocks, output registers, and collision semantics one bounded
  contract at a time.
- Resolve far-site clock/state delivery before claiming broad PLL reach.
- Qualify clock regions, seams, global networks, gating, reset, alternate PLL
  outputs, phase/duty/feedback/bypass, and additional HSE sources.
- Expand carry evidence beyond the exact same-tile/X20/seam footprints and
  test large carry compositions under density.
- Replace conservative timing families with exact cell/wire/clock/IO/BRAM
  models and multi-corner silicon correlation. Until then timing is guidance,
  not sign-off.

## P5: routing and architecture breadth

- Quantify actual graph/topology coverage separately from the recovered-corpus
  denominator.
- Recover missing special-block and IO feeders with conflict-aware provenance.
- Improve placement/routing success on the 52 campaign gaps through general
  algorithms, not per-design patches.
- Add metamorphic and independently generated workloads only after escape
  triggers have effective fail-closed guards.
- Create a genuinely sealed holdout suite; keep it sealed until models,
  adapters, and admission rules are frozen. Report its denominator separately
  from hand-authored development vehicles.
- Keep `research-unsafe` provenance explicit and never promote majority or
  predicted selector knowledge without the required evidence.

## P6: packages, boards, and deployment

- Complete L64 investigation without inheriting L48 claims; resolve its AHB
  mismatch before promotion.
- Qualify Q32 and L100 on actual boards, using physical bond maps rather than
  same-numbered-pin assumptions.
- Add AG32VH PSRAM decoding and fixtures as a separate track.
- Preserve the safe programming order: identify, backup, volatile test, write
  only with explicit authorization, verify, and restore/recover.
- Finish target-side mask-ROM UART qualification and interrupted-operation
  recovery.
- Maintain hash-verified Windows/Linux SDK bundles and the qualified OpenOCD
  installer; make toolchain/runtime mismatches diagnostic rather than routing
  failures.

## P7: CPU-scale and real designs

The retained SERV route remains a useful exact replay. It is not fresh design
parity or RV32I compliance. Re-enter CPU-scale work only after wide placement,
BRAM behavior, and correctness guards improve:

1. fresh-route the retained workload repeatedly with no route pins;
2. prove register-file writes directly rather than through wrapper-visible
   transparency;
3. expand instruction, branch, load/store, exception, CSR, interrupt, and trap
   coverage;
4. add unrelated application designs and a sealed holdout set;
5. report build success, model correctness, silicon correctness, and vendor
   comparison as separate outcomes.

## Promotion rule

A roadmap item moves to [STATUS.md](docs/STATUS.md) only when its public source,
route/config provenance, strict build, independent checks, board identity,
observable contract, negative controls, restoration record, and scope
exclusions are reviewable. “The tool emitted an image” and “the FCB accepted
it” are milestones, not completion.
