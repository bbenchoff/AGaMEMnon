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
| LUT and flip-flop logic | Inverters, registered feedback, counters, shifts, and routed sequential state |
| Global clock | Registered logic in near and far tiles using the supported PLL configurations |
| Physical input | L48 PIN_10, PIN_11, PIN_15, and PIN_19; registered input on PIN_19 |
| Physical output | Characterized L48 header outputs and PIN_25 through PIN_28, including concurrent use |
| MCU GPIO bridge | Four-bit inverted loopback over all 16 input combinations |
| External AHB read | Simultaneous 32-bit fabric-to-MCU data |
| External AHB write | All 32 HWDATA lanes exercised in protocol-valid four-bit groups |
| External AHB address | Registered `HADDR[4:2]` capture through `MCU_DIN76:78`; eight values observed 32 times each over 256 reads |
| General RTL scale | Randomized 16-, 32-, and 64-bit LFSR, xorshift, and nonlinear state machines; large routed SERV designs |
| Dedicated carry | Same-tile 4/8-stage chains, two simultaneous 3-stage chains, and one 32-bit chain across the qualified three-tile corridor |
| BRAM Port A | One characterized x18 dynamic path |
| BRAM Port B | One exact x2 read/control corridor |
| PLL | Restored 10-, 25-, 50-, and 100-MHz configurations after SRAM loading |
| SERV | True-dual-port blinky plus the named instruction-signature workload |
| Serial mux | Three simultaneous 9,600-baud inputs merged to a 115,200-baud output |
| SRAM configuration | Fabric and MCU firmware load, execute, and return observations without flash writes |
| RV32 MCU-only SRAM | Freestanding signature returned `RV32`, DEVICE_ID, `misa`, and an SRAM PC without a fabric image |
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

The release database contains 14 isolated dead-edge classifications. Negative
isolated evidence overrides positive route-corpus attribution.

## Boundaries of the hardware claim

- The BRAM result does not qualify every tile, width, initialization layout,
  write mode, collision mode, or arbitrary fresh route. The strict x9 ingress
  and active readback remain functionally static despite a passing isolated
  HADDR source and bit-identical vendor/open initialization pattern.
- The SERV signature workload is not a complete RISC-V compliance suite.
- The carry result does not qualify arbitrary seams or multiple long chains.
- The AHB write result covers every data lane in groups, not one simultaneous
  32-bit capture or every address/control/burst mode.
- Timing reports are not silicon Fmax guarantees because exact wire classes,
  skew, IO, hard-block, package, and PVT delays are incomplete.
- Option-byte programming and native USB DFU are not qualified product paths.
  The Pico UART bridge is USB-smoke-tested, but its target-side link remains
  unqualified until the documented five-wire addition is made.

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
