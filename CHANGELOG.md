# Changelog

All notable user-visible changes will be recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) in spirit. Version
numbers are not promises that an archive has been published; the Releases page
is authoritative for downloadable artifacts.

## [Unreleased]

### Added

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
  their liveness gates before BRAM behavior could be read. Open hard-BRAM
  writes therefore remain unqualified.
- Exact L48 PIN_25 combined-cell output enable: a constant-source A/B
  qualifies release/drive-low polarity and simultaneous static readback, while
  a local self-toggle through the same six-pip corridor proves dynamic OE by
  toggling only with an external pull-up (~1.04 MHz). Simultaneous dynamic
  readback, external PIN_10 control, generic/open-drain/registered OE, and
  other pins/corridors remain unqualified.
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
