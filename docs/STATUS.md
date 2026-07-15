# AGaMEMnon support status

This document is the current evidence-backed boundary of the open AG32 /
AGRV2K toolchain. “Builds” means the software path completes with strict
bitgen. “Silicon-qualified” means a hardware oracle exercised the generated
image. Configuration acceptance alone is not treated as functional evidence.

## Release path

The supported fabric flow is:

```text
synthesizable Verilog
  -> Yosys AGRV2K mapping
  -> nextpnr-generic --uarch agrv2k
  -> strict AGaMEMnon bitgen
  -> uncompressed SRAM image + compressed flash image
```

The path does not invoke `af.exe`, Supra, Quartus, or a routed vendor
checkpoint. The recommended backend is selected with `agamemnon build
--uarch`. The Python generic architecture adapter remains available for small
fixtures and reverse-engineering reproduction, but it is not the scale release
backend.

## Functional coverage

| Area | Current state | Qualified boundary |
|---|---|---|
| LUT/FF RTL | Silicon-qualified | Combinational logic, registered feedback, counters, shifts, FSM-style logic, physical-input registers, and large sequential designs |
| General routing | Silicon-qualified with strict selector encoding | Release graph admits exact physical selector pairs and unanimous tile-relative pairs; bitgen refuses predicted, legacy, or unresolved release selectors |
| Placement scale | Silicon-qualified subset | 72 randomized 16/32/64-bit RTL builds pass; the current dual-port SERV example routes through the public strict flow and runs on silicon |
| Clocks | Silicon-qualified subset | Global fabric clock reaches near and far logic tiles; supported PLL ratios are listed below |
| Physical outputs | Silicon-qualified L48 subset | Characterized header paths plus PIN_25, PIN_26, PIN_27, and PIN_28 individually and concurrently |
| Physical inputs | Silicon-qualified L48 subset | PIN10, PIN11, PIN15, and PIN19; combinational input and one PIN19 registered path |
| MCU GPIO bridge | Silicon-qualified | Four-bit MCU-to-fabric-to-MCU inverter loopback across all 16 input combinations |
| External AHB bridge | Silicon-qualified subset | All 32 fabric-to-MCU read lanes simultaneously; all 32 MCU write-data lanes in protocol-valid four-bit groups; a simultaneous full-word write and broader protocol modes remain open |
| Dedicated carry | Silicon-qualified opt-in | Same-tile 4/8-bit and dual 3-bit trials, plus one 32-bit chain across the recovered 33-site, three-tile vendor corridor |
| BRAM | Mixed | One characterized Port-A x18 route and one exact Port-B x2 read/control corridor are silicon-qualified; broader placement, widths, tiles, initialization, and collision modes are not |
| PLL | Byte-exact and silicon-used subset | `(SYSCLK,HSE)` of `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`, and `(100,16)` MHz; the SRAM loader restores the encoded PLL and measured 10/25/50/100-MHz divider probes scale as expected |
| Timing | Conservative, fail-closed estimate | Vendor-worst cell arcs plus worst delay per driving mux family; a 100-MHz TFF/counter smoke and SERV timing closure are hardware-backed |
| Bitstream codec | Byte-exact | LZW decode/encode, 99,936-byte raw image, CRC-32/BZIP2, LUT editing, and `.agasc` round trip |
| SRAM programming | Silicon-qualified | Load fabric and MCU firmware to SRAM, configure through FCB, run, and read results |
| Flash programming | Silicon-qualified main-flash path | Backup, 4-KiB sector erase, program, readback, and byte verification through the open controller implementation |
| Flash boot | Silicon-qualified existing compressed layout | Open compressed fabric image boots from the factory option-pointer location after power cycle |

## Routing trust model

The release selector table contains 659,759 conflict-free physical edge
encodings. A further 62,044 tile-relative encodings are admitted only where
every physical observation agrees. Conflicting keys are omitted rather than
majority-voted. Both architecture generation and bitgen enforce this boundary.

The device database contains 14 edges with isolated negative silicon evidence.
Negative isolated evidence overrides positive corpus attribution. Static or
live whole designs do not classify every edge they contain; three strong
whole-design suspects and two earlier correlation suspects were isolated and
proved live.

The qualification rule is therefore:

- exact configuration encoding is necessary but does not prove conduction;
- a passing isolated path promotes every previously unknown edge on that path;
- a dead edge requires repeated isolated negative evidence;
- placement correlation and unsensitized whole-design failure remain
  inconclusive.

## Scale evidence

The hardware-free randomized matrix contains 72 independently seeded LFSR,
xorshift, and nonlinear mixed machines at 16, 32, and 64 bits. All synthesize,
place, route, close their requested target, pass strict bitgen, and expose the
expected routed-netlist observation states.

The current SERV example uses about 350 slices and one inferred 512x2 true
dual-port BRAM. Its final public strict build routes 2,186 data PIPs, closes a
10 MHz target at an estimated 22.42 MHz, and emits no predicted, legacy, or
unresolved selectors. On L48 silicon, reset held onboard PIN_25 low, release
produced both output states across 8,000 samples, and reasserting reset held it
low again. RTL simulation observed 7,768 instruction fetches and 3,883 stores.
A separate dependent trial reached the exact 32-bit store value 5. This
qualifies the focused `addi`/`sw` workload and simultaneous register-file
ports, not general RISC-V instruction, exception, or interrupt compliance.
Broader eight-operation and dependent four-instruction signature programs
passed RTL and strict P&R but did not reach their PC/signature observations on
silicon. They remain negative qualification evidence, not supported workloads.

## Dedicated carry

`build --uarch --hard-carry` lowers eligible arithmetic to `AG32_FA`, inserts
one physical head seed per independent chain, places each chain contiguously,
and emits normal LUT-to-FF capture with `BYPASSEN=0`.

Multiple short chains fit in the hardware-qualified same-tile footprint when:

```text
sum(arithmetic bits) + number of chains <= 9
```

One eight-stage chain and two independent three-stage chains have passed on
silicon. A single long chain may use the exact recovered vendor order through
33 sites: one seed plus as many as 32 arithmetic stages across X20Y11,
X20Y12, and X20Y10. The 32-bit trial varied both endpoint bits on silicon.
Other spill locations, multiple long chains, branching, and malformed chains
fail closed, so hard carry remains opt-in.

## BRAM

The shipped BRAM database for the integrated physical bel contains 110 A/B bel
pins, 289 BRAM routing edges, and 533 configuration records. Yosys can infer a
single `ALTA_BRAM9K` for an ordinary two-read-port memory, and the backend
carries independent A/B clocks, enables, addresses, data, widths, and write
controls through strict P&R and bitgen.

The silicon boundary is narrower. An archived Port-A x18 route still produces
dynamic hardware values with the current bitgen. An exact isolated x2 Port-B
read/control route also produced four sequential values on silicon across 500
samples with zero predicted or unresolved selectors. This qualifies that
selected corridor, not arbitrary fresh placement: other fresh Port-A and
Port-B routes have remained static despite FCB acceptance and exact selector
encoding. Other widths and tiles, narrow-mode `INIT_VAL` packing, and
read/write collision semantics are not qualified.

## Timing and PLL

`build --freq MHz` passes a target to nextpnr and treats a timing failure as a
build failure. Cell timing includes conservative LUT, FF setup/hold/clock-to-Q,
and carry arcs. Wire timing uses the largest decoded WORST value for each
driving mux family because physical T0/T1/T4/TG class binding is incomplete.

This is useful conservative routing guidance, not a complete Fmax model. Exact
native wire-class mapping, clock skew, IO, BRAM, PLL, package timing, movable
timing-driven placement, and PVT/Fmax characterization are outside the current
model.

PLL emission fails closed outside `(100,8)`, `(50,8)`, `(25,8)`, `(10,8)`,
and `(100,16)` MHz. Other outputs, phase shifts, duty cycles, and bypass modes are
not integrated. The checked-in SRAM configuration stub switches to HSI while
streaming the image, then follows the SDK PLL-enable/lock sequence and selects
PLL again. Divider probes measured the expected scaling across 10, 25, 50,
and 100 MHz.

## Package and IO coverage

The package legality model knows the vendor pin sets for AGRV2KL100,
AGRV2KL64, AGRV2KL48, and AGRV2KQ32. Only AGRV2KL48 has a recovered physical
`PIN_n -> IOTILE` bond map. Physical PCF builds for the other packages fail
closed. Within L48, input qualification is limited to the listed pins and
paths; coverage must not be inferred for other banks or sides.

The L48 qualification harness was fingerprinted as PIN_25 -> Pico GP12,
PIN_26 -> GP13, PIN_27 -> GP16, and PIN_28 -> GP17. Each output passed an
isolated trial and all four passed concurrently. These are L48 package-pad
results; the same `PIN_n` labels must not be reused as physical claims for
L100, L64, or Q32.

## Programming boundary

The open flash-controller implementation does not use the vendor `agrv` flash
driver. SWD access still requires an OpenOCD executable with AGM's unpublished
RISC-V-over-ADIv5-DAP `riscv -dap` target extension. Stock upstream and
oss-cad-suite OpenOCD builds do not provide it.

UART bootloader and native USB DFU transports are not implemented. Writing a
new option-byte fabric pointer is present only as the opt-in, explicitly
unverified `image --write-options` operation. The supported persistent recipe
uses the existing factory compressed-config pointer and preserves the
decompressor sector.

## Not supported

- arbitrary dedicated-carry placement beyond the recovered 33-site corridor;
- complete BRAM tile/mode/corridor coverage beyond the selected x2 Port-B path;
- one-shot simultaneous 32-bit MCU writes and broader AHB address/control/burst modes;
- complete PLL outputs and modes;
- physical bond maps for L100, L64, or Q32;
- exhaustive IO-bank electrical coverage;
- exact timing classes and clock skew;
- probe-less UART or USB programming;
- a published-source replacement for the OpenOCD `riscv -dap` extension.
