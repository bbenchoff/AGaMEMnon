# Hardware qualification

AGaMEMnon's silicon-qualified feature set is tested on the AGM LQFP-48
development board containing an AG32VF303CCT6 with AGRV2KL48 fabric and
connected through an AGM CMSIS-DAP probe.

```text
DEVICE_ID  0x40200001  at 0x03000100
misa       0x40801125  (RV32IMAFC)
FCB STAT   0x000f0002  (active, no ID/header/CRC error)
```

Qualification images use the public Yosys, nextpnr `agrv2k`, and strict
AGaMEMnon bitgen path. Volatile tests load MCU firmware and fabric through
SRAM. Persistent tests start with a complete flash backup and verify every
programmed byte.

## Qualified capabilities

| Capability | Qualified scope |
|---|---|
| Codec and CRC | Compressed/raw conversion, valid FCB configuration, and CRC error detection |
| Static timing | No standalone timing oracle. Timing closure is a build-time model (conservative arcs plus 542 certified exact wire pairs) and is deliberately NOT a silicon claim: a retained trial closed timing at 100 MHz in nextpnr yet returned one static value across 500 silicon samples. Qualified designs are exercised at their own emitted rate; there is no measured Fmax |
| IO electrical attributes | Per-pad weak pull-up and open-drain, witnessed against an external logic analyzer. PIN_16 `CFG_PULL_UP`: after the probe drives the line low and releases, the pad reads high 3/3 with the bit set and low 3/3 with it clear (it holds high even against the probe's active pull-down). PIN_26 `CFG_OPEN_DRAIN` with the pad toggling at ~500 Hz: with the bit set the line toggles under an external pull-up but reads LOW 0/200 under a pull-down (high phase floats), 3/3; the push-pull control toggles under both. Config-bit locations for 22 pads in `agamemnon/chipdb/io_pad_electrical_L48.csv`. No pull-up resistance, drive-current, or slew value is measured, and eleven special-function pad sites take no such config |
| From-scratch base image | The default design-neutral base (`default_frame`, no canvas byte read) configures through the FCB (`FCB_STAT 0x000f0002`, stable on re-read); the stale-CRC vendor canvas — identical except the 4 CRC bytes — is rejected (`0x00000040`, `STAT_ERR_CRC`), isolating the CRC as the cause. Evidence: `qualification/fabric_base_evidence.jsonl` (2026-08-14 re-run with hashed image, firmware, and source). Configuration acceptance only; no claim about the function of unnamed reserved bit-lines |
| LUT and flip-flop logic | Inverters, registered feedback, counters, shifts, and routed sequential state |
| Global clock | Registered logic clocked from the single GCLK0 spine at the qualified seam selector, using the supported PLL configurations. One *isolated* distribution oracle exists (GCLK0 → X12Y3_ClkMUX02); beyond it and the tiles exercised incidentally by other qualified designs, per-tile clock arrival is unmeasured — the former "near and far tiles" phrasing had no coordinates behind it and is withdrawn |
| Physical input | L48 PIN_10, PIN_11, PIN_15, and PIN_19; registered input on PIN_19 |
| Physical output | Characterized L48 header outputs and PIN_25 through PIN_28, including concurrent use; plus exactly three top-edge pads, PIN_18, PIN_16 and PIN_15 (2026-08-15) — not the ten-pad PIN_10..PIN_19 ring; the other seven (PIN_10, PIN_11, PIN_12, PIN_13, PIN_14, PIN_17 and PIN_19) are unqualified. PIN_15 is pad tile (19,13) slot z1 on Pico GP2: 3,187,733 Hz alone with GP6/GP8 static, and 3,187,127 Hz beside PIN_16 at 3,188,253 Hz from one image that shares both the pad tile and the config tile (18,13). For PIN_18 and PIN_16: both toggling from one ordinary-CLI image (final production code path: Pico GP8 3,195,844 Hz and GP6 3,195,806 Hz; the earlier 403,449/405,596 Hz figures came from a pre-final build and are superseded — the claim is that each pad toggles and that the two are independent, not any particular rate), each toggling alone with the other static, neighbouring pads GP7/GP2/GP5/GP3 reading zero edges, all FCB 0x000f0002 with zero unmapped and zero predicted selectors. As of 2026-08-15 the left-edge four also reproduce from the ordinary CLI — `agamemnon build qualification/left_edge_outputs.v --pcf qualification/left_edge_outputs_L48.pcf --research-unsafe`, image sha256 `a63ab5bc26bb4852555fb93863f065ba020564ec77e801cd4d67d4bcf865aba3`, 35 pips / 0 unmapped / 0 predicted / 0 legacy-abs, measured at Pico GP12 404,383 Hz, GP13 405,612 Hz, GP16 405,168 Hz, GP17 411,144 Hz with GP8 (PIN_18, undriven) reading 0 Hz as the negative control, FCB 0x000f0002. Flow caveat, stated honestly, and it applies to the top-edge images too: the Python-architecture PCF placer composes experimental options, so these pad builds need `--research-unsafe` and release-strict rejects them |
| MCU GPIO bridge | GPIO4 four-bit inverted loopback over all 16 input combinations. On L48, exact GPIO5 output-data/output-enable lanes 0 and 1 plus return input lane 2 are separately qualified through pure-open images (one lane pair at a time, not simultaneously); the boundary requires terminal 8 on the seven inactive BBMUXS groups, proven by three retained failures where zero-filled terminals did not work |
| External AHB read | Simultaneous 32-bit fabric-to-MCU data |
| External AHB write | All 32 HWDATA lanes are exercised in protocol-valid four-bit groups. The exact public L48 profile integrates ID `0x4d`, complete-byte scratch, a three-bit read-only counter, and one-bit W1C status at offsets 0/4/8/C, including GPIO4.1 synchronous reset, exactly one controlled write wait, and zero-wait reads. Its byte passed all 256 values and 128 back-to-back pairs. Wait8 recomposition drives every upper HRDATA lane explicitly zero, so aligned halfword and word reads return exact zero-extended values; aligned byte and halfword write/read semantics are qualified with simultaneous HADDR[1:0] ingress; every nonzero HBURST encoding fails closed with HRESP and no state mutation. Misaligned CPU accesses fault deterministically in the hard core (mcause 5/7) and never reach the fabric. Hard MCU_RESETN and wider writable state remain unsupported; HRESP-to-MCU-fault behavior is retired |
| External AHB address | Registered `HADDR[4:2]` capture through `MCU_DIN76:78`; eight values observed 32 times each over 256 reads. An isolated pure-open `HADDR[5:4]` XOR additionally passed 256/256 addresses; simultaneous `HADDR[1:0]` logic ingress is qualified on the complete-byte waited bank |
| External AHB bus clock | Default `bus_clk = sys_gck` delivery to exact direct-D sites X14Y11 slice4 through slice7; an explicit three-bit counter produced all eight states and a 16-bit LFSR produced 500 distinct reads; 45 timer intervals measured exactly one LFSR step per undivided MTIME tick — a 1:1 *ratio*, which is the qualified quantity. The absolute rate was previously reported as 10 MHz by assuming MTIME ran at the vendor-nominal 10 MHz HSI; a later direct measurement put MTIME at 14.08 MHz, so the absolute frequency is an open question (see [MCU_CLOCKS.md](MCU_CLOCKS.md#measured-default-clock-on-an-sram-loaded-part)). GPIO4.1-fed synchronous reset held all state bits at zero and re-armed across three runs |
| External AHB constant slave | Full 32-bit `0x4147414d` reads at multiple addresses, no-effect write completion, 64 stable repeated reads, ready/OKAY response, and zero uninstantiated LUT route-throughs |
| Fabric local interrupts | Four distinct simultaneous routes to `local_int[3:0]`; independent causes 16–19 and matching `mip[16:19]` bits. The integrated command bank is a *sequential one-hot* selector over ONE shared pending/mask pair — not four simultaneous pending stores; that per-lane topology failed and is retained as negative evidence. Reads return zero, so no state-readback is claimed |
| General RTL scale | Randomized 16-, 32-, and 64-bit LFSR, xorshift, and nonlinear state machines; large routed SERV designs |
| Dedicated carry | Same-tile 4/8-stage chains, two simultaneous 3-stage chains, and one 32-bit chain across the qualified three-tile corridor |
| BRAM Port A | One characterized x18 path plus all nine X13Y4 read-only x9 data bits through exact per-lane projections and one simultaneous strict-open 256-word identity bundle; bits3, 4, and 5 independently match word-address bit3, bits6, 7, and 8 match word-address bits0, 1, and 2 respectively, all for 256/256 reads, and an independent HADDR11/AddressA12 projection distinguishes word addresses 0 and 512 for 64/64 alternating samples |
| BRAM Port B | One exact x2 read/control corridor |
| PLL | HSE=8 MHz, `SYSCLK` 4-248 MHz. `qualification/pll_freq_evidence.jsonl` holds 43 silicon-frequency rows (five profile rates plus 38 sweep rates), each locked, selected, and measured against the OpenOCD host wall-clock over a 1 s and a 4 s window; worst 0.058% off the requested rate. `(100,16)` and `(100,12)` need a 16/12 MHz HSE and cannot be exercised on this 8 MHz-HSE board, so they stay preamble/timing-only. No phase, duty-cycle, feedback, bypass, or non-8 MHz-HSE claim |
| SERV | True-dual-port blinky plus the named instruction-signature workload |
| Serial mux | Three simultaneous 9,600-baud inputs merged to a 115,200-baud output |
| SRAM configuration | Fabric and MCU firmware load, execute, and return observations without flash writes |
| RV32 MCU-only SRAM | Freestanding signature returned `RV32`, DEVICE_ID, `misa`, and an SRAM PC without a fabric image |
| Hard CRC unit | CRC-32/MPEG-2 known-answer of ASCII `123456789` == `0x0376E6E7`, SRAM-only, no fabric image |
| Hard DMA (`DMAC0`) | Memory-to-memory single-channel 4-word copy verified in SRAM, SRAM-only |
| Hard UART0 loopback | Internal (`LBE`) loopback echoed byte `0xA5` with clean status, SRAM-only |
| Hard UART0 external TX | TX only, on a physical L48 pad (PIN_10) through an open peripheral-route fabric, captured off-chip by an independent logic analyzer: 14 bytes decoded with 11 occurrences of the `00 FF 55 41` stimulus, byte-exact and reproduced across runs. RX, flow control, and the *programmed baud* are NOT qualified — the line ran at ~560 baud when 9600 was requested |
| Hard I2C0 master transmit | Framing only, on physical L48 pads (SDA PIN_11, SCL PIN_15): 288 decoded transactions, every one `addr=0x55` direction W, correct START/STOP/address/direction/data phases. The per-byte NACKs are the expected result — no slave is on the bus. Requires an external pull-up; without one the engine stalls and the capture reads flat zero. Reads, ACK against a real slave, clock stretching, repeated START, 10-bit addressing, and the programmed 100 kHz rate are NOT qualified |
| Hard SPI0 master transmit | MOSI/SCK/CSN on physical L48 pads (SCK PIN_12, MOSI PIN_14, CSN PIN_13): 233/233 decoded words all `0x55`, plus a `11 22 33 44` payload with 108 pattern matches. **MSB-first, and word boundaries require CS** — without CS the same capture decodes as garbage. Also qualifies the sub-word byte-lane fix (the controller shifts the high-order bytes of `PHASE_DATA`, so `ag32_spi_write` left-justifies). RX/duplex, RX sub-word lane placement, DUAL/QUAD, DMA, and multi-phase sequences are NOT qualified |
| Hard watchdog (`WATCHDOG0`) | Disabled-state register snapshot, plus a supervised timeout that warm-reset the MCU with `RST_CNTL` bit30 `SYS_RSTF_WDOG` set exclusively; SRAM-only warm reset, board restored |
| Machine timer interrupt | CLINT/MTIME interrupt fired and the trap was taken with `mcause` `0x80000007`, SRAM-only |
| RTC (config path only) | `BDCR` `RTCEN`+LSI-select stick and the backup domain is writable on silicon; the counter did not advance (no low-speed clock running), so timekeeping is not qualified |
| Main flash | Full backup, 4-KiB sector erase, program, readback, and byte comparison |
| USB-loaded RV32 application | 172-byte image written/verified at `0x80010000`, executed by `GO`, PC and LED GPIO observed, then sector restored byte-exact |
| Native AGaMEMnon USB transport | `probe --transport usb` returned loader 2.1 and DEVICE_ID `0x40200001`; a direct 32-byte read at `0x80000000` matched the resident loader image |
| Flash boot | Compressed AGaMEMnon image loaded from the existing factory pointer after power cycle |

## L48 harness wiring

The qualification fixture establishes these board-specific connections:

| AG32 L48 | Pico |
|---|---|
| PIN_25 | GP12 |
| PIN_26 | GP13 |
| PIN_27 | GP16 |
| PIN_28 | GP17 |

These mappings apply only to the qualified L48 package and board. They do not
describe identically numbered pins on L100, L64, Q32, or another PCB.

## Qualification rules

- FCB acceptance proves the image header, device ID, CRC, and configuration
  protocol; it does not prove path conduction.
- A passing isolated source-to-observed-sink test qualifies the traced path.
- A dead-edge classification requires repeated isolated failures with one
  unknown path edge.
- Whole-design correlation and unsensitized failures are diagnostic only.
- Software build and routed-netlist simulation results are labeled separately
  from hardware results.
- Qualification applies to the exact package, mode, and feature boundary
  exercised by the oracle.

> **Superseded by the conduction reframe — do not read the paragraph below as
> current.** The "14 isolated dead-edge classifications" framing has been
> retracted. Those failures came from a single large, *congested* MCU-exit design
> and were mis-attributed to individual edges: **5 of the 14 are board-proven to
> conduct** in clean/isolated builds and are now un-gated in the shipped router,
> and the remaining **9 are held as UNVERIFIED, not proven-dead**. Those 9 are
> bounded rather than judged: a forcing construction's STUCK reading is
> uninterpretable (matched sibling controls keeping a different non-catalogued
> crossing also read STUCK), so only positive readings count. The word
> "isolated" was the error — the evidence was never per-edge. The real limit is
> aggregate MCU-exit congestion, which is a routing/allocator problem in our own
> flow rather than silicon death. See `CONDUCTION_REFRAME_STATUS.md`.
>
> Two claims that must stay distinct: *per-edge, the dead catalogue was an
> artifact and the gate was over-restrictive* — versus — *wide/congested designs
> remain an open, unproven frontier*.

~~The release database contains 14 isolated dead-edge classifications. Negative
isolated evidence overrides positive route-corpus attribution.~~

## Boundaries of the hardware claim

- The BRAM result does not qualify every tile, width, initialization layout,
  write mode, collision mode, or arbitrary fresh route. X13Y4 read-only x9 is
  qualified for all nine visible data bits within the exact exercised per-lane
  projections.
  Three INIT projections on bits0..2 independently return word-address triplets
  `[2:0]`, `[5:3]`, and `[8:6]` for 256/256 reads, superseding the earlier
  interpretation that constant projections implied dead INIT/addressing.
  Separate bit3, bit4, and bit5 oracles match word-address bit3 for 256/256
  reads. Separate full-width projections make bits6, 7, and 8 match
  word-address bits0, 1, and 2 respectively for 256/256 reads. Their physical
  x9 lanes are DataOutA15, DataOutA16, and DataOutA7.
  Bit5 uses the corrected exact
  BufMUX13/RMUX92/RMUX75/RMUX20/BBMUXE07
  corridor; the earlier q4-shaped assignment remains retained negative
  evidence. A paired q4/q5 oracle additionally qualifies q4 through the exact
  BufMUX12/RMUX75 corridor and the source-dependent RMUX43-to-BBMUXE06
  selector `{1,6}`. The allocator reserves that exact corridor only for the
  simultaneous q4/q5 case; the resulting nine-output image returns values
  0..255 exactly once, with bits0..7 matching the word address 256/256. q8 is
  zero over that bounded range and retains its separate two-state proof. An
  address-bit9 INIT projection alternated word addresses 0 and
  512 and matched
  64/64 reads, qualifying HADDR11/AddressA12 and its X14Y7 slice3 footprint.
  Those earlier observations and additive negatives remain valid. The
  remaining high-address lanes/range, writes, dual-port operation,
  other modes/sites, and collision behavior remain unqualified.
- One BRAM configuration field now has measured behaviour and two have a
  measured bound. `PORTA_OUTREG` adds exactly **one** BRAM clock of Port-A
  read latency: a fabric-side cycle-sensitive oracle (500 samples x 3 runs,
  parity of `hrdata[2:0]`, SRAM-only, `FCB_STAT 0x000f0002`) read
  base = `{0x8,0xb,0xd,0xe}` EVEN and an extra-pipeline-register positive
  control = `{0x9,0xa,0xc,0xf}` ODD, and `PORTA_OUTREG` measured ODD,
  matching the control. `PACKEDMODE` and `CLKMODE` measured EVEN in that
  read-only mode (x18 Port-A read, identity ROM contents, 4-bit fabric
  address, Port-B unused, single clock domain). `PACKEDMODE` returned a bounded null in that read-only oracle, but as of 2026-08-15 it has **measured first-order behaviour** in both the write-path and dual-port oracles: one config byte (66,222) moves the write-path observable from `{0,5,A,F}` to `{0,4,8,C}` and collapses the dual-port observable from 7 distinct values to 2. **No mechanism is claimed** -- what the field does is unresolved. `CLKMODE` remains a **bounded null** across all three tested compositions (read, write-path, dual-port), which is a wider bound than before and still not a characterization. In the same campaign the fabric **write did not land** on a pre-registered three-image criterion (`wr_main`, the `wr_noop` control and the `wr_alt` mirror all read the no-write set); that does **not** separate "the silicon will not write" from "the emitter cannot express the write", and the deciding emitter-side suspect is the frozen `bram_dual_ctrl.csv` `CFG_TMUX` two-hot (selectors 104/111) possibly selecting `RMUX20@(15,4)` while every image routes WeA from `RMUX20@(16,4)`. Still open: BRAM writes, dual-port operation, the
  remaining config modes, and most B4 rows; the older MCU-AHB read sweep is
  blind to all B4 BRAM rows. The measured field lives at X13Y4, which is the
  whole PLACEMENT surface; the CONFIG surface
  (`agamemnon/engine/pips_bram_pll.csv`) separately covers X13Y1..X13Y4.
- The SERV signature workload is not a complete RISC-V compliance suite.
- The carry result does not qualify arbitrary seams or multiple long chains.
- The AHB write result covers every data lane in groups, not one simultaneous
  32-bit capture or every address/control/burst mode.
- The constant slave qualifies one combinational ready/OKAY endpoint. It does
  not itself qualify bus-clocked state, reset, waits, errors, byte access, or
  the writable register-bank wrapper. Separate exact-site counters and a
  long-period LFSR qualify bus-clock delivery, sequential computation, a
  timer-relative 1:1 bus-clock-to-MTIME ratio (not an absolute frequency), and
  GPIO-fed synchronous reset-to-zero/re-arm, not hard `MCU_RESETN` or equal
  post-release phase. A separate strict image
  integrates that same reset ingress with the qualified register bank.
- The HADDR[5] XOR qualifies one isolated logic-ingress corridor, not the
  complete address decoder or a protocol-valid sequential endpoint.
- The GPIO5 result qualifies only exact output-data/output-enable lanes 0 and
  1 returning through input lane 2 on L48. It also proves that inactive hard-
  boundary `BBMUXS` terminals need explicit safe selections. It does not
  qualify the full GPIO matrix, package pads, arbitrary direction changes, or
  simultaneous multi-lane use.
- The local-interrupt results are two separate claims and were previously
  conflated here. (a) The *routing* oracle
  (`mcu_local_int_evidence.jsonl`) qualifies simultaneous conduction and local
  cause identity only. (b) A later set of AHB command-bank images
  (`mcu_ahb_register_bank_evidence.jsonl`, trials
  `2026-08-05-l48-ahb-local-int{0,1,2,3}-command-bank-pure-open` and
  `-local-int-all-command-bank-lane{0..3}-pure-open`) does qualify retained
  pending, mask/unmask, acknowledge, two re-arms, masked hold, and GPIO4.1
  reset. Taking the narrower reading of (b): what is qualified is a
  *sequential one-hot* command bank with **one shared pending/mask pair**
  across the selected cause, not four independently retained pending bits, and
  reads deliberately return zero. State readback, active-pending pre-`mie`
  visibility, POR, PLL3/alternate clocks, and hard `MCU_RESETN` remain
  unqualified. An earlier per-lane mask/pending topology was tried and failed;
  those records are retained as negatives in
  `mcu_ahb_local_int1_evidence.jsonl`.
- Timing reports are not silicon Fmax guarantees because exact wire classes,
  skew, IO, hard-block, package, and PVT delays are incomplete.
- Option-byte programming and native USB DFU are not qualified product paths.
  The Pico UART bridge is USB-smoke-tested, but its target-side link remains
  unqualified until the documented five-wire addition is made.
- The hard-peripheral qualifications are SRAM-only, non-destructive runs. The
  CRC, DMA, UART0-loopback, watchdog, and machine-timer-interrupt results come
  from `examples/riscv_mcu` firmware. The UART0-external-TX, I2C0 and SPI0 rows
  come from workbench stimulus firmware that is *not* part of this repository;
  their ledger rows name it explicitly and pin its hash, but they cannot be
  reproduced from a checked-in source here. Those three are transmit-side
  framing/byte-exactness claims on physical pads, not protocol-completeness or
  bit-rate claims. The RTC result is config-path only and does not claim a
  running counter or timekeeping.
- **CAN is not qualified.** No CAN bits have been observed on a wire; the pad
  idles recessive-high and the board has no transceiver. Register-level
  transmit activity has been seen on the bench but is **not recorded in any
  ledger under `qualification/`**, so this record makes no CAN claim at all.
  USB host/OTG and the Ethernet MAC are likewise unqualified here (host and PHY
  absent); the hard USB *device* path is separately qualified through the
  flash-resident CDC uploader.
- **The analog blocks (ADC/DAC/comparator) are not covered by this record.**
  They sit on the External-AHB window rather than the MCU-MMIO peripheral
  surface, they are reached only through a fabric image that instantiates the
  **vendor `analog_ip` hard-macro wrapper** (AGaMEMnon's own bitgen does not
  emit that macro), and — importantly — the bench results described in
  [ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md) have **no append-only
  ledger row under `qualification/`**. Until such a row exists they are lab
  observations, not entries in this qualification record. The only analog
  material with ledger rows is read-only ADC0 *route* support
  (`analog_adc0_*_route_evidence.jsonl`), which carries no electrical or
  functional claim.

## Reproduce a volatile test

```bash
agamemnon build examples/designs/counter_ahb.v --uarch --verify \
  --write-routed counter_routed.json -o counter.bin
agamemnon verify counter_routed.json
agamemnon probe
agamemnon sram .tmp/clkcfg_stub.bin --fabric counter.bin
```

Build `.tmp/clkcfg_stub.bin` using
[`examples/firmware/README.md`](../examples/firmware/README.md).

Hardware commands require AGaMEMnon's qualified OpenOCD binary with AGM's
`riscv -dap` target extension and the packaged
`agamemnon/openocd/agrv2k.cfg`. Install it with `agamemnon install-openocd`
and check the connected target with `agamemnon doctor --probe-dap`. The
release's destructive-write/restoration gate is recorded in
[`evidence/openocd-windows-ag32.json`](evidence/openocd-windows-ag32.json).

The reproducible inputs, routed artifacts, hashes, and observations are under
`qualification/`. Their accepted scope is summarized in
[qualification/README.md](../qualification/README.md).
