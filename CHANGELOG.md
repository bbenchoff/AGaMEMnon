# Changelog

All notable user-visible changes will be recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) in spirit. Version
numbers are not promises that an archive has been published; the Releases page
is authoritative for downloadable artifacts.

## [Unreleased]

### Parity-gap closure (2026-08-25)

- Added a final exact-image safety gate for retained silicon negatives. After
  CRC generation, strict bitgen hashes the canonical uncompressed image and
  refuses 17 demonstrated-wrong images spanning open defects `VP-AGM-001` and
  `VP-AGM-003` through `VP-AGM-009`, under every emission policy. This is a
  byte-exact fence: it neither closes those defects nor qualifies a changed
  placement, route, or configuration.
- Restored exact-map CI without moving a reviewed artifact: the public32
  composer replays the existing reviewed status-pending branch and rejects it
  if any hop leaves the strict graph or conflicts with another net. Public16,
  public32, GPIO5-W1C, and autonomous-W1C text pins now use canonical-LF
  hashing. On a clean checkout the composers use the packaged, hash-checked
  strict graph snapshot instead of requiring an ignored generated devdb; a
  live generated strict graph is preferred when present. The retained routed
  and image hashes are unchanged.
- Made `pyproject.toml` the source of truth for wheel package data and added the
  omitted `analog_*` and `physical_*` runtime tables. The installed-wheel smoke
  expands that declaration, verifies every declared file is present, and then
  packs/scaffolds the qualified profiles from an isolated installation.
- The complete hardware-free suite now reports 1451 passed, 49 skipped, and 0
  failed. This is an offline release-health result, not new silicon evidence or
  a broader parity claim.

### Campaign wind-down (2026-08-24)

- Closed a controlled 105-design vendor/open/model campaign: 25 narrow parity
  successes, 10 vendor-reference failures, 2 vendor-unstable designs, 52
  routability gaps, 13 correctness escapes, and 3 harness-incomplete designs.
  Six of 51 paired structural forms passed. These were hand-authored boundary
  vehicles and the sealed holdout remained n=0; no statistical or broad-parity
  claim is made.
- Added exact release-strict route/config support and normalized silicon
  evidence for paired SPI0/SPI1 TX, I²C0/I²C1 repeated-START transactions,
  UART1/UART2 TX, and the repaired UART0 TX/PIN_10 path. SPI TX covers all
  documented divider settings and direct raw-register byte-order semantics;
  I²C0 additionally covers one bounded four-point 500 us stretch profile.
- Corrected the SPI SDK TX lane packing (`VP-AGM-010`) and one exact UART0
  route selector (`VP-AGM-002`). Both closures are limited to their tested L48
  paths and contracts.
- Added fail-closed production guards for demonstrated silent-wrong surfaces.
  Typed `MCU_SPI0_MISO_INPUT` and `MCU_SPI1_MISO_INPUT` now refuse under
  `VP-AGM-008`; the affected initialized x1/x18 BRAM static/read profiles now
  refuse under `VP-AGM-006`. The recovered evidence remains available for
  diagnosis but is not promoted as working RX or BRAM behavior.
- Recorded open correctness defects `VP-AGM-001` and `VP-AGM-003` through
  `VP-AGM-009`: MCU feedback, FSM update, rotate/reset, add/reset, BRAM read,
  far-site clock/state delivery, generic physical ingress/SPI MISO, and one
  256-bit density composition. Clean selector accounting, byte-identical
  repack, or a correct routed model did not make these designs correct on
  silicon.
- Preserved the wide-design frontier as bounded evidence: X13Y12 ingress is
  recovered, while fresh `regbank16` remains no-image, `addsub16` exposes
  placement divergence, and the routed 256-bit user form diverges on its
  second transaction.
- Rewrote the public status, parity, roadmap, getting-started, CLI, routing,
  and reverse-engineering narratives around exact evidence tiers and explicit
  exclusions. Removed the claim that AGaMEMnon can never emit a failing
  bitstream.
- The post-campaign evidence gate passed 64 ledgers / 653 records. At wind-down
  the full suite reported 1443 passed, 49 skipped, and 2 protected public32
  reviewed-artifact failures; the 2026-08-25 entry above records their later
  closure without moving the reviewed artifact.
- All campaign hardware runs used identified L48 targets, control-first
  sessions, volatile SRAM loads, zero AG32 flash writes, final reset, apparatus
  restoration, and append-only evidence.

### Added

- AG32 family coverage foundation (T25): a new part-level registry
  (`agamemnon/engine/family.py`) transcribes the seven real AG32 part numbers
  (`tools/AG32_RefManual.txt` Sec 1.2) over the existing four-package
  `device.py` model, carrying flash size, PSRAM presence, and ADC/DAC channel
  counts per part. A new `AGAMEMNON_PART`/`--part` selector records which
  part a build targets (cross-checked against `AGAMEMNON_DEVICE`/`--device`
  for package consistency) without changing architecture selection.
  `claim_policy`'s release-strict device gate no longer blanket-rejects every
  non-`AGRV2KL48` device regardless of surface: it now gates on the exact
  physical/electrical option a build activates (`ELECTRICAL_OPTIONS`), so a
  pad-free, fabric-logic-only build is build-supported on every AGRV2K
  package (the fabric is identical family-wide), while a pad-touching build
  (`--pcf`, `--leds`, `AGAMEMNON_LEFT_PAD_OUT`, ...) still fails closed off
  `AGRV2KL48`. Building for a part is never a silicon claim for that part --
  silicon claims stay per-board. A new coverage-matrix generator
  (`tools/generate_family_coverage_matrix.py`, source data
  `agamemnon/sdk/family_coverage_matrix.json`) renders
  `docs/FAMILY_COVERAGE_MATRIX.md`: rows are the seven parts, columns are
  {config-accept, pad-out, pad-in, OE, flash prog/backup, PSRAM, peripherals},
  cells are tiered {silicon-qualified / build-supported / recovered-only /
  n/a} and validated against the family/device registries so a part can never
  be marked silicon-qualified without a recorded qualified board.
  `AGRV2KL48`'s default build is unchanged (byte-identical pack-regression
  goldens).
- Fresh-source `examples/serv_blinky/serv_blinky.v` now builds, places,
  routes, and strict-bitgens release-strict end to end (3,027 data PIPs, 0
  unmapped/predicted/legacy selectors) and passes `agamemnon verify`. Two
  fixes: `qin_pack.externalize_multi_selffb` rewrites own-Q feedback loops
  beyond the four-site direct-D pool with an external identity-LUT buffer
  (the same construction already silicon-qualified at sixteen simultaneous
  register-bank lanes), instead of requiring more direct-D sites; and
  `lock_bram_portb_corridors` now claims the SERV register file's exact,
  source-matching `DataInA`/`WeA` write corridor before `AddressA[3..12]`,
  so an address bit whose own "exact" table silently doesn't apply to a
  fresh, internally-driven design can no longer fall through to an
  unconstrained search and steal the write corridor's pip first. No
  admission gate, selector table, or conduction data changed. This is a
  build-and-simulation result only -- the fresh route is not silicon-
  qualified, and the retained, silicon-qualified `--template serv-blinky`
  exact-replay checkpoint is unaffected and remains byte-identical.
- `agamemnon build <source> --uarch --pcf <pcf>` (no `--research-unsafe`) now
  builds release-strict for the left-edge four L48 outputs, nine of the ten
  top-edge outputs (all but PIN_15), and the qualified L48 input corridors,
  with zero unmapped/predicted/legacy selectors. `AGAMEMNON_VENDOR_OUT_SLICE`
  is promoted to release maturity for exactly the four presentations
  `pad_output_qualified_L48.csv` requires, gated by a new dedicated
  value-bounded `claim_policy` check (mirrored from the existing
  `AGAMEMNON_DIRECT_D_SITES` precedent) so no other value is release-admitted.
  Fifteen new retained routed-JSON artifacts are pinned in
  `pack_regression.json` and repack byte-identically under release-strict.
  Every one of the fifteen new-vehicle images FCB-configured the real L48
  device to `0x000f0002` over a non-destructive SRAM session
  (`io_evidence.jsonl` trial
  `pad-uarch-pcf-release-strict-vehicle-config-accept-20260817`). The Pico
  toggle/electrical re-witness of this vehicle's own images has since closed
  for all ten output images -- the left-edge four and nine of the ten
  top-edge outputs each toggle under both Pico pulls on exactly their
  intended lead and no other (`io_evidence.jsonl` trial
  `pad-uarch-pcf-toggle-rewitness-20260817`), matching the pre-existing
  research-unsafe-vehicle electrical claim pad-for-pad. The five qualified
  L48 input demonstration builds still only FCB config-accept on this
  vehicle; their toggle re-witness came back an honest negative (the
  observed output pad read a fixed level regardless of the Pico's applied
  bias) and is not claimed electrically requalified. PIN_15 as an output
  still fails to route under `--uarch` and still needs `--research-unsafe`.
- Opt-in fresh-source X13Y3 and X13Y4 x18 full-depth read compositions. The
  same exact corpus passes all 512 words and observes all nine address lanes
  independently at both sites. X13Y1 and X13Y2 retain the same partial
  `0x100` address signature, so this does not yet enable generic or
  arbitrary-site BRAM inference.
- The expanded
  exact corpus covers 526 address/data/clock/control hops and 409 selector
  fields, seven identity-slice footprints, and site-relative ROM control.
- Exact X13Y1..Y4 BRAM terminal and selector-cell metadata from five
  simultaneous four-cell vendor routes, plus a reference-only 2,112-edge
  structural corpus. SRAM-only zero-LUT L48 oracles first read distinct marker
  bytes from all four hard arrays in one AHB word (`0x88442211`, 256/256), then
  exercised all 512 x18 Port-A addresses at all four sites simultaneously with
  zero first-read, settled-read, or upper-half errors (`0x2de187b4` at word
  256). Production routing remains X13Y4-only until open-flow site corridors
  are independently qualified.
- SDK archive smoke coverage for a fresh installed-wheel
  `--qualified-bram-write` source-to-route build using the archive's bundled
  nextpnr, with exact raw and compressed image hash checks. Archive smoke CLI
  calls now run outside the checkout so source files cannot shadow the wheel.
- I2C0 multi-byte and repeated-START qualification: three fresh SRAM-only runs
  wrote `2A A6`, changed direction with a repeated START, and read
  `5A C3 7E` with the exact master ACK/ACK/NACK sequence against a checked-in
  RP2350 open-drain register oracle.
- UART0 external TX/RX qualification: separate exact images qualify physical
  L48 PIN_10 TX and PIN_31 RX at requested 9600/38400/115200 baud; a combined
  zero-LUT image routes UART0 TX to PIN_30 and PIN_31 to RX, and three fresh
  full-load runs transferred 4096 exact bytes each way simultaneously at all
  three rates through the DAP CDC. At 38400, 7E1/8E1/8O1/8N2 each transfer
  256 bytes both ways with the expected parity-flag matrix and intact
  payloads. Absolute bit-rate calibration and hardware flow control remain
  open.
- I2C0 active open-drain interoperability on exact L48 SDA PIN_11 / SCL
  PIN_15 routes. An RP2350 software slave at address `0x55` ACKed both address
  directions and a write of `0xA6`, then returned `0x5A` on a separate read.
  `ag32_i2c_read(..., last=1)` now accepts the controller's expected terminal
  `RXNACK` status while still returning arbitration and timeout failures.
- SPI0 active slave-driven receive qualification on an exact L48 IO1 route.
  An RP2350 PIO oracle drove prefixes of `12 34 56 78` at widths one through
  four. Raw receive words hold reversed bytes in their low lanes and stale
  upper state; `ag32_spi_write_read()` now returns natural, right-justified wire
  order. The earlier sampled-high lane control is retained independently.
- All fourteen historically blocked routing edges are now admitted. The final
  edge, `RMUX15@3,4->RMUX68@6,4`, is silicon-qualified by a compact,
  clock-free PIN_25-to-PIN_18 sibling/target A/B. Each selected hop was the
  sole non-clock `x=3.5` crossing on the measured input net, the two arms
  shared the fixed consumer and complete output route, carried zero selector
  debt or mux conflict, FCB-accepted, and reproduced the exact eight-state
  inverse truth table under both pulls.
- A thirteenth of the fourteen historically blocked routing edges,
  `RMUX09@14,4->RMUX28@14,8`, is silicon-qualified by a clock-free direct
  PIN_25-to-PIN_18 baseline/sibling/target campaign. The target and
  same-destination sibling terminate immediately at
  `X14Y8_SLICE0.I[0]/IMUX00`, share identical physical input ingress and
  complete output routes, carry zero selector debt or mux conflict, and all
  three arms reproduced the exact eight-state inverse truth table under both
  pulls.
- A twelfth of the fourteen historically blocked routing edges,
  `RMUX69@14,6->RMUX76@14,10`, is silicon-qualified by a clock-free direct
  PIN_25-to-PIN_18 baseline/sibling/target campaign. The selected edge is the
  sole `y=9.5` crossing on the measured input net and terminates locally at
  `X14Y10_SLICE10.I[0]`; all three arms reproduced the exact eight-state
  inverse truth table under both pulls with zero selector debt or mux conflict.
- The `ALTA_BRAM9K` surface now exposes scalar `AsyncReset0` and the exact
  measured `IMUX32 -> TileAsyncMUX00` route. Emission replaces the complete
  selector field with `{2,7}`, clearing inherited sel 3. This is route/config
  reproduction only: the live natural `TMUX13 -> KMUX3` open matrix retained
  INIT in both pulsed directions, while both `TMUX09`-tail attempts failed
  their liveness gates before BRAM behavior could be read. A later
  registered-source four-arm matrix corrected that apparatus and qualifies one
  exact fixed-address X13Y4 x18 write A/B through `TMUX09 -> KMUX03`; generic,
  edited, and inferred hard-BRAM writes remain unqualified.
- Exact L48 PIN_25 combined-cell output enable: a constant-source A/B
  qualifies release/drive-low polarity and simultaneous static readback, while
  a local self-toggle through the same six-pip corridor proves dynamic OE by
  toggling only with an external pull-up (~1.04 MHz). High-rate readback, the divergent
  RMUX20 branch, active drive-high, generic/open-drain/registered OE, and
  other pins/corridors remain unqualified; stepped external PIN_10-controlled
  OE with simultaneous readback was later production-qualified
  (2026-08-16 trial).
- An eleventh of the fourteen historically blocked routing edges,
  `RMUX21@14,9->RMUX87@14,7`, is silicon-qualified by a clock-free
  PIN_19-to-PIN_25 A/B. Its already admitted same-destination sibling and the
  target were each the sole non-clock `y=8.5` crossing, carried zero selector
  debt and no mux-ownership conflict, FCB-accepted, and reproduced the exact
  eight-state identity table under both external pulls.
- A tenth of the fourteen historically blocked routing edges,
  `RMUX21@14,8->RMUX87@14,5`, is silicon-qualified by the same clock-free
  PIN_19-to-PIN_25 method. Its same-destination sibling and target were each
  the sole non-clock `y=7.5` crossing, carried zero selector debt,
  FCB-accepted, and reproduced the exact eight-state identity table under both
  external pulls.
- A ninth of the fourteen historically blocked routing edges,
  `RMUX80@15,7->RMUX33@15,4`, is now silicon-qualified by a clock-free direct
  PIN_19-to-PIN_25 witness. Its same-destination sibling and target were each
  the sole non-clock crossing, carried zero selector debt, FCB-accepted, and
  reproduced the exact eight-state identity table under both external pulls.
- Decimal L48 PIN_12 as one exact scalar, single-consumer direct combinational
  input: `InputMUX07@(20,13)->RMUX56@(20,12)`, exact LUT `I[2]` at
  `X19Y12_SLICE2`, inverted observation at qualified PIN_16, and zero selector
  debt. This does not qualify fanout, registered capture, thresholds, or other
  packages.
- Silicon qualification for all ten decimal top-edge L48 package outputs,
  PIN_10 through PIN_19, through pinned exact compositions. The closing
  PIN_10/PIN_11 singles and pair also validate replacement of stale IOMUX
  selector fields.
- One exact 16-bit External-AHB held-scratch checkpoint with one write wait,
  external LUT feedback, SRAM-churn retention, repeated reads, and GPIO reset.
  The default exact L48 public profile now composes canonical ID32
  `0x4147414d` with zero-extended scratch16/counter3/W1C1 at +4/+8/+c;
  three complete SRAM-only silicon runs passed the full word/subword and state
  matrix. This is one pinned four-word composition, not a generic bank.
- A separately selectable exact public32 GPIO5-W1C profile. It removes the
  qualification bit1 set hook and routes MCU GPIO5 DATA0/OUT_EN0 into the
  retained clocked W1C set stage. One negative, one dual-source OR control, and
  three production SRAM runs causally qualify sustained-level set, hold/clear,
  set priority, and reset dominance with the complete public32 matrix retained.
  The source is software-controlled qualification stimulus, not a package-pin
  input or asynchronous interrupt.
- A separately selectable exact public32 autonomous-event W1C profile. The
  existing synchronous counter emits one reset-rearmed count-seven event with
  no AHB set write or GPIO stimulus. Negative, OR-control, and three production
  SRAM runs retain the full public32 matrix and prove the bounded event/hold/
  clear/re-arm contract. This is one exact HCLK-synchronous source, not a
  generic application socket, asynchronous CDC boundary, or interrupt ABI.
- Direct hard-BRAM output controls withdrew the former X13Y4 x2 write claim.
  INIT=1/write-zero stayed one and INIT=0/write-one stayed zero; the old result
  observed a fabric-side read-first/transparency wrapper. Production no longer
  bypasses those input emulation DFFs automatically.

### Fixed

- The `mcu_ahb_constant_slave` external-AHB endpoint's shipped `0x4147414d`
  claim (docs/STATUS.md) stopped reproducing on a fresh `--uarch` build
  sometime between 2026-08-02 and 2026-08-17 (hardware-confirmed reading
  `0x795fe3dd` on two distinct AG32 units instead). Root cause was two-fold:
  (1) `chipdb/mcu_edge_feeder_exit_pairs.csv` was missing an exact tuple for
  `X14Y11_RMUX03 -> X13Y11_BBMUXE09`, so bitgen used the `BBMUXE_PAIR[3]`
  source-index fallback, which 2026-08-14's transposition fix correctly
  changed for every *other* RMUX03 edge but happened to break this one
  previously-untested edge (now fixed with an exact tuple; see
  `tests/test_boundary_mux_selectors.py`'s pinned per-terminal exception);
  (2) that fix alone was insufficient -- the actual 10 wrong bits trace to a
  still-open `X14Y8` RMUX->IMUX->RMUX routing detour that nextpnr now reaches
  due to unrelated chipdb growth (not a code/seed change), and forcing a
  reroute around it fixes 9 of 10 bits but exposes a separate, unisolated
  cross-net interaction. `qualification/mcu_ahb_constant_slave_routed.json`
  is re-pinned to the retained, hardware-confirmed 2026-08-02 routed netlist
  as an interim fix; a from-scratch `agamemnon build --uarch` of this design
  is not currently guaranteed correct (see docs/USAGE.md and
  docs/CONDUCTION_REFRAME_STATUS.md's 2026-08-18 T26 entry). Board-verified
  on the L48 reference unit.
- A constant-tied BRAM write-enable (`WeA`/`WeB` driven by a plain `1'b1`,
  e.g. `mem[addr] <= din;` every cycle with no dynamic write-enable and no
  live Port-B read) used to be silently disconnected by
  `pack_bram_localize_const` in `agrv2k.cc`. Under `AGRV2K_BRAM_HARDCONST`
  (always on for `--uarch` builds) any constant-tied BRAM control pin was
  dropped on the assumption that the generic control blob
  (`bram_rom_ctrl.csv` vs `bram_dual_ctrl.csv`, selected in
  `features/bram.py` from `portb_read` + `WeA` connectivity) supplies the
  right default -- but that default is write-DISABLED for any design that
  isn't also live-reading Port B, so an unconditional write silently
  degraded to a read-only ROM image with no error. Reproduced live: the
  disconnect log line ("hard-defaulted N ... BRAM constant input(s)") fires
  for a minimal single-BRAM write design, and for at least one netlist shape
  the resulting inconsistent packed state crashed nextpnr with an unrelated-
  looking `std::out_of_range` instead. `pack_bram_localize_const` now refuses
  instead of guessing: a constant-1 `WeA`/`WeB` aborts packing with a named,
  actionable `log_error` instead of either silently dropping the pin or
  crashing. This shape has never been silicon-qualified for the generic
  control-blob path (see `--qualified-bram-write` for the individually
  qualified corridor); the two existing qualified TMUX09 write profiles
  (`bram-tmux9-i1-d0-we0`/`we1`, real routed `WeA` nets, not constants) were
  rebuilt fresh end to end and are byte-identical to their pre-fix output --
  zero behavior change for anything already qualified. New tests:
  `test_pack_bram_localize_const_refuses_a_constant_high_write_enable`,
  `test_inferred_write_bram_with_constant_high_we_fails_loud_not_silent`,
  `test_genuine_readonly_bram_does_not_trip_the_write_enable_guard` in
  `tests/test_bram_constant_write_enable.py`.
- A memory that `memory_libmap` declines to place on the ALTA_BRAM9K block
  RAM -- e.g. a plain 512x1 memory with an asynchronous/combinational read,
  which the block-RAM library's clocked-only "srsw" ports cannot express --
  used to fall through to `memory_map` (one flip-flop per bit plus an
  address-decode LUT tree) with zero visible signal under the default `-q`
  build: `memory_libmap` prints nothing when it never attempts a mapping,
  and `-q` suppresses the informational `stat` counts that would otherwise
  show it. Reproduced live: exactly this shape silently expanded into 512
  DFFs + ~1000 LUT4s (roughly a quarter of this device's flip-flop budget
  and half its LUT budget) with yosys exiting 0. `synth_pads.tcl` now checks
  for leftover `$mem`/`$mem_v2` cells right before `memory_map` would lower
  them and prints an always-visible `AGAMEMNON WARNING` (raw `puts stderr`,
  so it survives `-q`) naming the cell. This does not fail the build --
  "small/odd memories fall through to FFs" is an existing, accepted,
  size-based outcome documented in this same script, and yosys's own
  `memory_libmap` already hard-errors when an explicit
  `(* ram_style = "block" *)` truly cannot be satisfied; only the silent
  case (no attribute, no message) was the bug. New tests:
  `test_synth_pads_source_contains_the_leftover_memory_guard`,
  `test_async_read_memory_silently_expanding_to_ffs_now_warns`,
  `test_forced_block_ram_still_hard_errors_on_an_unfittable_shape`,
  `test_ordinary_write_bram_does_not_trip_the_leftover_memory_warning` in
  `tests/test_bram_unmapped_memory_warning.py`.

- D0's route-invariance regression check (Rule 2, `_real_route_invariance_check`
  in `agamemnon/engine/routing_admission.py`) silently passed when its
  retained-qualified-artifact registry (`qualification/pack_regression.json`)
  was literally absent, contradicting its own documented contract that
  "absence of the ability to verify is treated exactly like a positive
  mismatch. Both reject." This is live today for every installed release
  wheel: `pyproject.toml`'s `[tool.setuptools.package-data]` never lists
  `qualification`, so the registry this check reads never ships outside the
  source checkout. The D0 default-promotion approval gate remains unapproved
  in the shipped chipdb, so no currently-passing build was affected, but the
  gap would have silently no-opped Rule 2 the moment a real default-promotion
  approval artifact ships. The check now raises `RoutingAdmissionError` when
  the registry file is missing, matching the existing behavior for an
  individually unbuildable retained artifact. The `stub_route_invariance`
  test fixture (which intentionally bypasses Rule 2 to isolate other D0
  mechanics) now points at a real, present, empty-artifacts registry instead
  of a nonexistent path, so it no longer depends on the closed gap. New test:
  `test_route_invariance_fails_closed_when_the_registry_file_is_literally_absent`
  in `tests/test_d0_default_promotion.py`. No admission gate was loosened;
  the shipped, unapproved D0 gate's live behavior is unchanged.

- `agamemnon/program.py`'s SRAM-inject stack pointer (`SRAM_SP`) and the
  shipped SDK's `agamemnon/sdk/link_sram.ld` `__stack_top` both moved from
  `0x20008000` to `0x20020000` (top of the 128 KiB SRAM). The old value sat
  inside the staged fabric-image window (`[0x20002000, 0x2001a668)` for the
  fixed 99,944-byte uncompressed image), so a deep firmware call stack could
  silently corrupt the staged image before/during FCB streaming. Every
  historical qualification script already used `0x20020000`; only the two
  shipped defaults were stale. `startup.S` loads `sp` from `__stack_top`
  directly on entry, so the linker constant -- not the OpenOCD register
  preset -- is what actually governs the runtime stack for every template
  that uses the default `@sdk/link_sram.ld`. Not the cause of any known
  failure; found and fixed as an unsafe-by-construction issue during a
  hazard audit. Board-verified: the `mcu-fpga-registers` template rebuilt
  against the fixed linker script and SRAM-injected the retained
  `l48-public32-exact-map-2026-08-15` qualified profile still FCB-configures
  to `0x000f0002` on silicon.
- `agamemnon build` now fails closed, before any board time is spent, when a
  project's `[fabric].qualified_profile` and `[mcu].sources` are a mismatched
  pair. A board-observed `mcu-fpga-registers` self-test FAIL (`result[11]`,
  reported after the `SRAM_SP`/`__stack_top` fix above) was root-caused to
  this, not to that fix: matched-control replay showed the default
  `src/main.c` + `l48-public32-exact-map-2026-08-15` pairing passes cleanly
  and identically both before and after the linker change (6/6 SRAM-inject
  trials, each preceded by a fresh full reset). The FAIL reproduces on demand
  only by hand-editing `qualified_profile` to a bit1-hook-retiring derivative
  (`l48-public32-gpio5-w1c-exact-map-2026-08-15` or
  `l48-public32-autoevent-w1c-exact-map-2026-08-16`, both of which document
  "the old AHB bit1 self-test hook is inert") while leaving `[mcu].sources`
  on the default `src/main.c`, which still exercises that hook -- exactly
  the "outside the qualified profile's documented scope" symptom, isolated to
  a single `result[7]` mismatch with every other register-bank check passing
  (3/3 trials). The three shipped `qualified_fabric_profiles.json` entries
  with a matching template firmware example now record a
  `companion_main_source`; `agamemnon build` cross-checks it via the new
  `project.check_qualified_profile_mcu_pairing`. Profiles with no matching
  template firmware (`l48-public16-exact-map-2026-08-15`,
  `l48-complete-byte-waited-2026-08-05`) or that back a non-firmware template
  (`l48-serv-blinky-2026-07-15`) are unaffected. Separately flagged for
  review, not fixed here: the shipped `main_gpio5_w1c.c` and
  `main_autoevent_w1c.c` self-tests' free-running-counter coverage check
  (`result[6] == 0xff`) is timing-sensitive to each firmware's own exact
  instruction count even when correctly paired with its own profile --
  `main_gpio5_w1c.c` reproducibly reports `0xf7` (3/3), and
  `main_autoevent_w1c.c` varies run to run (`0xf5`/`0xfd`/`0xff`); the
  latter's verdict word is also `result[10]`, not `result[11]`. Neither is
  caused by this change or by the linker fix.
- Root-caused and fixed the free-running-counter coverage self-check flagged
  above. It is not a hardware defect: `devdb_generator`-style analysis of the
  loop showed the fixed 512-iteration trip count only proves `result[6] ==
  0xff` coverage for whichever exact instruction timing (compiler, `-O`
  level, AHB wait states across the CPU<->fabric clock-domain-crossing
  bridge) it happened to be tuned against. `main_gpio5_w1c.c` and
  `main_autoevent_w1c.c` now poll in a bounded loop that exits once every
  one of the counter's 8 states has actually been observed (`seen ==
  0xffu`) instead of after a fixed count, capped at 65536 polls so a
  genuinely stuck or miswired counter still fails closed rather than
  spinning forever. The verdict still requires exact `result[6] == 0xffu`;
  nothing was relaxed. New regression tests
  (`test_counter_coverage_self_check_is_robust_to_poll_timing` in both
  `test_mcu_ahb_public32_gpio5_w1c_exact_map.py` and
  `test_mcu_ahb_public32_autoevent_w1c_exact_map.py`) fail against the old
  fixed-trip-count shape and pass against the fix; hardware re-qualification
  of the two companion profiles is a follow-up HIL task.
- `test_status_overlay.py::test_bundled_strict_device_snapshot_is_mechanically_reproducible`
  was the session's one known-flaky test. Root cause: it preferred reading
  the live, gitignored `agamemnon/engine/uarch/agrv2k/devdb_strict/` nextpnr
  build directory whenever it happened to exist on disk, falling back to the
  hash-pinned committed snapshot only when absent -- so "mechanically
  reproducible" actually depended on whether an unrelated, ad hoc,
  continuously-regenerated uarch/conduction-qualification build on the
  developer's machine still agreed with whatever commit last froze the
  shipped `status_overlay_dev_*.csv.gz`/manifest snapshot. The gzip/manifest
  emitter itself (`tools/generate_status_overlay_devdb.py`) was confirmed
  deterministic (fixed `gzip(..., mtime=0)`, fixed compresslevel, fixed
  table order, fixed JSON formatting -- two independent runs on the same
  input are always byte-identical); this was a test-hermeticity bug, not an
  emitter nondeterminism bug. The test now always reconstructs its canonical
  input from the pinned, hash-verified manifest (never the ambient
  directory) and asserts two independent generator runs are byte-identical
  to each other and to the committed snapshot; if a live `devdb_strict`
  build also happens to be present it is additionally checked for
  determinism and internal hash-consistency, without asserting it matches a
  point-in-time freeze it is not required to match. `.gitattributes` also
  now marks the two shipped `status_overlay_dev_*.csv.gz` artifacts
  `binary` and pins `status_overlay_devdb_manifest.json` to `eol=lf`, so
  `text=auto`/autocrlf can never perturb these hash-pinned bytes on a
  Windows checkout.
- `program.cmd_flash` (the DAP/SWD flash transport, the default for
  `agamemnon flash`) only skipped its backup step when `--backup` was
  omitted (`if a.backup: ...`) instead of refusing to write at all --
  unlike `uart_program.flash_image` and `usb_program.cmd_usb_flash`, which
  both raise before touching hardware. `cli.py`'s `cmd_transport_flash`
  dispatcher happened to enforce `--backup` uniformly before calling any of
  the three, which masked the gap for normal CLI use, but `program.cmd_flash`
  itself was unsafe-by-construction for any other or future direct caller of
  the module. It now refuses immediately (before `_require_ag32()` or any
  hardware access) when `--backup` is missing, matching the other two
  transports. New test `test_dap_flash_refuses_without_backup_before_touching_hardware`
  in `tests/test_program_safety.py` fails against the old conditional shape
  and passes against the fix.
- `project.write_flash_plan`'s generated `build/flash-layout.json` recorded
  each region's `file` path with `str(Path(...).relative_to(...))`, which
  uses the host OS's native separator -- the same project built on Windows
  emitted `"file": "build\\mcu.bin"` while POSIX emitted
  `"file": "build/mcu.bin"`, a real byte-for-byte cross-platform
  non-determinism in a project-generated manifest. Switched to
  `.as_posix()`, matching the convention already used elsewhere in this
  codebase (`tools/bundle/build_bundle.py`'s `artifact_record`,
  `project.check_qualified_profile_mcu_pairing`'s own source normalization).
  The existing
  `test_project_flash_layout_records_hashes_and_rejects_overlap` fixture
  never exercised a nested output path, so it could not have caught this;
  it now builds into a `build/` subdirectory and asserts the recorded
  `file` fields are forward-slashed with no backslash anywhere in the
  output on this Windows test host.

### Investigated

- A fresh HEAD rebuild of `examples/designs/mcu_ahb_constant_slave.v` read
  `0x795fe3dd` from AHB `0x60000000` on a first-session LQFP-64 unit
  (`qualification/l64_bringup_evidence.jsonl`), while that identical
  bitstream's own `agamemnon build --uarch --verify` cycle-sim, and the
  2026-08-02 L48-qualified value, both predict `0x4147414d`. Audited
  whether this is a regression from the four same-night commits
  (`684549d`, `ebb4845`, `ea197bf`, `901a9e3`): it is not -- none of the
  three touch `features/mcu_ahb.py`, `features/routing.py`, `bitgen.py`,
  or any `mcu_hrdata_lanes.csv`-family chipdb table, and the one file that
  did change (`agrv2k.cc`) is scoped to BRAM `WeA`/`WeB` constant-write-
  enable packing, unreachable by this BRAM-free design. Independently of
  the routed-netlist cycle-sim, parsing the routed JSON's `$PACKER_VCC_NET`
  / `$PACKER_GND_NET` `ROUTING` pip-trees against
  `mcu_hrdata_lanes.csv`'s `logical_bit` map reconstructs all 32 HRDATA
  bits to the same `0x4147414d`, and `ROUTING_FEATURE.validate_mux_ownership`
  raised no cross-net mux conflict during bitgen. So every desk-computable
  layer of this exact, byte-identical-on-two-rebuilds bitstream agrees on
  the intended encoding; the L64 mismatch is unexplained at that layer and
  was not resolved this session, because only the L64 unit (confirmed by a
  read-only flash-prefix hash match against its retained factory backup)
  was physically attached -- the L48 reference board needed for the
  decisive silicon check was not available, and policy keeps the L64 unit
  idle for this investigation. Full detail, including the exact follow-up
  test, is recorded as trial `2026-08-18-t22-const-mismatch-desk-audit` in
  `qualification/mcu_ahb_constant_slave_evidence.jsonl`. Also noted in
  passing: this design has no `pack_regression.json` byte-identity
  coverage, so this specific wide single-source 32-way constant fan-out
  has no regression gate today.

- Follow-up to the above: is the L64 `0x795fe3dd` read reproducible, or was
  it a first-bring-up/session artifact? Ran the same byte-verified
  `bitstream_sha256 fc6919c2…` through 6 independent
  `reset halt` → reconfigure → run cycles on the same physically-attached
  L64 unit (freshly re-confirmed by a 16KiB flash-prefix hash match), each
  cycle followed by a DEVICE_ID sanity read and 12 further direct in-config
  bank reads with no intervening reconfigure. Result: 96/96 reads of
  `0x60000000` returned `0x795fe3dd`, zero exceptions, across both
  config-time and read-time; `FCB_STAT` was `0x000f0002` and DEVICE_ID was
  `0x40200001` every single cycle. This rules out a session/bring-up
  artifact -- the mismatch is real and stable on this unit -- but does not
  by itself attribute it to L64 silicon/package versus a toolchain
  bitgen-encoding bug that would also affect L48; that discrimination still
  needs the L48 hardware reread. `tools/l64_bringup_20260818/
  l48_decisive_reread.py` (in AG32-Docs) is a push-button, sha-pinned rerun
  of the identical procedure, ready for that board swap; it already
  refuses correctly when run against the still-attached L64 unit. Recorded
  as trial `2026-08-18-t23-l64-const-mismatch-reproduced` in
  `qualification/mcu_ahb_constant_slave_evidence.jsonl` and a
  `docs/CONDUCTION_REFRAME_STATUS.md` log entry.

## [0.3.0] - 2026-08-13

### Added

- Hard MCU peripheral qualification on L48 silicon (SRAM-only, non-destructive):
  CRC-32/MPEG-2 known-answer, DMAC0 memory-to-memory copy, UART0 internal
  loopback, a supervised watchdog warm-reset, and a machine timer interrupt,
  plus an RTC config-path driver. Evidence in
  `qualification/hard_peripheral_evidence.jsonl`.
- PLL closed-form divider emitter with the silicon-frequency-qualified HSE=8
  range (SYSCLK 4-248 MHz; 43 measured rows in
  `qualification/pll_freq_evidence.jsonl`).
- Vendor-observed MCU-edge feeders banked as conduction-gated routable RRG pips.
- `docs/AF_EXE_REVERSE_ENGINEERING.md` - the reverse-engineering narrative of the
  vendor `af.exe` back-end.
- `docs/CONDUCTION_REFRAME_STATUS.md` - live research log for the conduction
  reframe.
- `docs/FABRIC_DEFAULT_CANVAS.md` - byte-exact anatomy of the `fabric_default.bin`
  vendor canvas and the tracked path to removing it.
- `qualification/conduction_ungate_evidence.jsonl` - board evidence for the two
  un-gated conducting edges.

### Changed

- Conduction model reframed. The catalogued "silicon-dead" routing edges are a
  congestion-context characterization artifact, not intrinsic per-edge silicon
  death (board-proven for 2 of 14). The two board-verified edges
  `RMUX21@14,10->RMUX87@14,8` and `RMUX63@10,4->RMUX68@9,4` are removed from the
  negative-evidence set and admitted by the strict router; the remaining twelve
  stay conservatively blocked as unverified. The gate mechanism (negative
  evidence has absolute precedence over positive attribution) is unchanged.
  `STATUS.md`, `VENDOR_PARITY.md`, `FPGA_PARITY_LEDGER.md`, and `ARCHITECTURE.md`
  are reconciled to the reframe.

## [0.2.0] - 2026-08-11

### Added

- Misaligned CPU accesses are characterized on silicon: the hard core raises
  synchronous access faults (mcause 5/7) for misaligned fabric-window
  transfers and address-misaligned faults (mcause 4/6) for SRAM, with zero
  completions and zero state mutation, so the aligned transfer surface is
  complete and the slave's misaligned path is CPU-unreachable.
- The External-AHB waited register bank now returns exact zero-extended
  32-bit reads: every upper HRDATA lane is explicitly driven zero through
  strict route-only branches, silicon-qualified per lane and as one image.
- Aligned byte and halfword access semantics are silicon-qualified on the
  complete-byte bank with simultaneous `HADDR[1:0]` logic ingress; the
  protocol core gains `WRITABLE_MASK` subword masking.
- Every non-SINGLE HBURST encoding now fails closed in the public protocol
  core with `HRESP` and no state mutation; burst acceptance is retired.
- A register-window soft UART core ships sim-only (offline loopback and
  fail-closed regression; no route, silicon, or electrical claim).
- The 1024-address X13Y4 x9 BRAM read record is retained with its
  qualification source; the x9 full-address ingress stays experimental.
- Native Windows x64 installed-wheel reproduction now joins the Linux and
  macOS cold-install gates on every public CI run.
- Six exact AGRV2KL48/L48 RMUX30 selector rows are admitted behind the
  fail-closed, hash-bound `experimental-strict` gate. They remain disabled by
  default and are denied under `release-strict` policy.

## [0.1.1] - 2026-08-09

### Fixed

- Direct-D routing admission now requires every tagged state element to have a
  unique placement in the exact qualified L48 site pool before nextpnr runs.
- Replaced the release smoke project's unqualified counter with a maintained
  combinational-IO project while retaining `fpga-blink` as a deprecated
  compatibility alias.
- Optional left-pad bridge lookup now fails closed with a routing diagnostic
  instead of asserting when the architecture does not expose that bridge.

## [0.1.0] - 2026-08-09

### Added

- Package-specific L100, L64, L48, and Q32 bond maps with provenance and
  explicit qualification state.
- Semantic `agamemnon explain` and `agamemnon diff` commands.
- A cycle-accurate Python External-AHB oracle and matching clean Verilog slave
  test model.
- Declarative generation and inspection of the complete 164-byte preamble,
  including the five qualified PLL profiles.
- A CI path-leak policy and sanitized machine paths in checked-in artifacts.
- A documentation-integrity checker for maintained local links and heading
  anchors, enforced in CI.
- End-to-end CI that builds the qualified SERV signature workload through
  pinned Yosys, the pinned AGRV2K nextpnr backend, strict bitgen, and routed
  verification.
- Complete published AG32 PLIC source definitions, CLINT/PLIC helpers, a
  direct trap substrate, and SRAM-safe exception/software/timer interrupt
  examples.
- Open hard-CRC and programmable APB-watchdog drivers, a non-destructive
  CRC-32/MPEG-2 known-answer candidate, and a read-only watchdog snapshot.
- `agamemnon qualify`, with a read-only host report, artifact hashing, and a
  machine-readable support matrix separated by part, package, board,
  transport, and feature.
- Clean SDK archive smoke testing for offline install, version/doctor checks,
  routed-fixture verification, and maintained MCU/FPGA project compilation.
- Hash-bound SDK component/license inventory and wheel preflight for required
  runtime data and the disclosed vendor-origin fabric baseline.
- Verified Windows/Linux OSS CAD Suite and xPack RISC-V GCC asset pins plus a
  two-host release workflow that builds pinned nextpnr and smoke-tests each
  finished archive.
- One-command Windows/Linux SDK installers that verify the archive, perform an
  offline wheel install, activate bundled tools, and run diagnostics.
- Clean-wheel allow-listing that excludes research-only chip databases, plus
  a hash-pinned universal `tomli` wheel for offline Python 3.8-3.10 installs.
- Fail-closed MCU alternate-function and fabric-routing policy tied to exact
  part, package, board, fabric, and silicon evidence.
- Safe exact L48 wire timing on 9,375 route PIPs, with the conservative family
  model retained everywhere exact timing is absent.
- Seven byte-exact L48 PLL ratios with preamble hashes and rejection of every
  unsupported frequency pair.
- The completed 39-row BRAM configuration-encoding admission, exposed only by
  explicit experimental-strict policy and with untested compositions rejected.
- Hash-bound register-bank and SERV project profiles reproduced from installed
  wheels on Windows, Linux, and native macOS.

### Fixed

- Replaced executable pickle runtime graphs with a versioned, bounded AGDB
  schema (about 8.4 MB instead of 66.8 MB).
- Removed runtime `sys.path` mutation and split shared selector, database,
  inspection, preamble, and simulation concerns into importable modules.
- Removed the Git LFS checkout requirement; all source and data files are
  ordinary Git objects and CI scans for unresolved path leaks.
- Reconciled all maintained documentation with the current CLI, package maps,
  runtime databases, generated preamble, transport safety rules, and hardware
  evidence; corrected stale flash-restore and USB examples.
- Fabric builds now use one frequency for nextpnr timing and the emitted PLL,
  with a qualified 10 MHz default and fail-closed validation of supported
  `SYSCLK/HSE` ratios.
- OpenOCD release preparation now keeps patch inputs LF-normalized on Windows,
  and hosted-runner Git upgrades are recorded as source-fetch-tool drift
  without weakening compiler or linked-library version locks.
- SDK ZIP and tar.gz assembly now normalizes member order, timestamps,
  ownership, permissions, and the gzip header, so identical staged inputs
  produce identical archive bytes and SHA-256 sidecars.
- Strict bitstream emission now rejects Q32, L64, and L100 before synthesis;
  their decoded bond maps remain inspectable without inheriting L48 evidence.

### Initial release foundation

#### Added

- Open Verilog-to-bitstream flow using Yosys, the AGRV2K nextpnr backend, and
  strict AGaMEMnon bit generation.
- Manifest-backed MCU, FPGA, and combined project templates.
- Freestanding RISC-V startup, linker layouts, register headers, and an
  incremental open HAL.
- `--version` and `doctor` diagnostics.
- Independent `doctor` readiness tiers for inspection, MCU builds, FPGA
  builds, DAP, USB, and UART.
- DAP/SWD, flash-resident USB CDC, and Pico-controlled mask-ROM UART
  programming interfaces with explicit recovery boundaries.
- Silicon qualification records for the supported L48 subset, including MCU
  bridge, IO, clocks, carry, BRAM, SERV, and serial-mux workloads.
- AG32 newcomer overview, provenance notice, support policy, and contribution
  templates.
- Reproducible Windows, Linux, and macOS OpenOCD releases from pinned official
  source, Gerrit 9590, and the AGaMEMnon ADIv5 repair, including complete GPL
  source, hashes, provenance, and SPDX SBOM.
- `agamemnon install-openocd` with verified download, automatic discovery, and
  optional authenticated GitHub download support.

#### Changed

- Installation documentation distinguishes source installation from the
  hash-verified SDK archives published by the tag workflow.
- Release bundles may omit OpenOCD and remain useful for MCU/fabric builds.
  Bundles that include it consume AGaMEMnon's paired binary and complete GPL
  source release.
- Qualified board naming is consistently `AG32VF303CCT6` with `AGRV2KL48`
  fabric.

#### Known limitations

- The tag workflow publishes SDK archives for Windows x64 and Linux x64;
  macOS uses the portable wheel plus separately published OpenOCD and external
  FPGA tools.
- Linux and macOS Intel OpenOCD are build- and parser-qualified but still need
  physical host-specific USB/DAP bench runs.
- Physical routing silicon qualification remains L48-specific; the other
  package maps are recovered and explicitly unqualified.
- The open MCU HAL and hard-peripheral qualification are incomplete.
