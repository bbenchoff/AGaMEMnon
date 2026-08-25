# AGaMEMnon

AGaMEMnon is an open toolchain and MCU SDK for the AGM AG32: an RV32IMAFC
microcontroller joined to a small AGRV2K FPGA fabric. It takes Verilog through
Yosys, nextpnr, strict bitstream generation, and programming without invoking
the vendor fabric back-end.

The device combines a 256 KiB flash / 128 KiB SRAM RISC-V MCU and its hard
UART, SPI, I²C, CAN, USB, Ethernet, timer, ADC/DAC, and GPIO blocks with 2,112
LUT4s, 2,112 flip-flops, four BRAMs, a PLL, global clocks, an MCU/fabric AHB
boundary, and a programmable IO ring. The [AG32 overview](docs/AG32_OVERVIEW.md)
explains the parts, packages, clocks, boot paths, and naming.

> [!IMPORTANT]
> AGaMEMnon is a **fail-closed, qualified subset**, not a broad vendor-parity
> replacement today. Release-strict emission proves that every emitted feature
> and selector is admitted by the current evidence policy; it does not prove
> that an arbitrary composition will behave correctly on silicon.

## Current evidence boundary

A controlled 105-design campaign closed on 2026-08-24 with 25 narrow parity
successes, 10 unusable vendor references, 2 vendor-unstable designs, 52 open
routability gaps, 13 AGaMEMnon correctness escapes, and 3 incomplete harness
runs. Six of 51 paired structural forms passed. The designs were deliberately
hand-authored boundary vehicles, and the sealed holdout set remained **n=0**;
these counts are not a statistical or general parity claim.

The strongest new exact L48 results include:

- UART0, UART1, and UART2 transmit on PIN_10 at nominal 9,600, 38,400, and
  115,200 baud;
- SPI0 and SPI1 transmit across the documented divider settings and direct raw
  transmit-register byte-order semantics;
- I²C0 and I²C1 open-drain write/repeated-START/read transactions, plus one
  bounded four-point 500 us stretch profile on I²C0;
- selected physical outputs, small fabric logic/arithmetic/state vehicles, and
  exact MCU AHB and interrupt compositions.

The same campaign found cleanly packed images that were wrong on silicon:
initialized BRAM reads returned zero, two generic physical-input compositions
stayed low, SPI0/SPI1 MISO stayed high, a five-region registered design lost its
state, and a 256-bit state design diverged on transaction two. Typed SPI MISO
and the demonstrated BRAM profiles now refuse in release-strict mode. Other
escape artifacts are excluded from qualification while their causes remain
open. See [Status](docs/STATUS.md) and [Vendor parity](docs/VENDOR_PARITY.md)
before treating any nearby design as supported.

## What this project replaces

The normal fabric flow is a Windows-only Quartus II fork around a closed
back-end that packs, places, routes, and emits the image. AGaMEMnon replaces
that path with recovered, reviewable data and open algorithms:

```text
Verilog -> Yosys -> AGRV2K chip database -> nextpnr -> strict bitgen -> image
```

The bitstream container, CRC, global preamble, design-neutral base, many cell
fields, and large routing-selector corpora are decoded. The open flow can
regenerate its base image and emit supported overlays without copying a vendor
design image. Recovered data is still vendor-derived; [NOTICE.md](NOTICE.md)
records that provenance boundary.

The difficult remaining problem is not merely decoding legal bit values. The
vendor back-end itself can produce functionally wrong designs, and the open
flow has now done so too. Placement, routing, configuration, clock delivery,
hard-block state, and physical IO must therefore be qualified as compositions
on silicon. AGaMEMnon's aim is to turn every known silent-wrong surface into a
refusal until there is positive evidence. That policy is real; universal
correctness is not yet achieved.

This is IceStorm for an obscure RISC-V/FPGA hybrid, with a deliberately smaller
support claim than its recovered architecture database. The reverse-engineering
story is in [Reverse-engineering the vendor back-end](docs/AF_EXE_REVERSE_ENGINEERING.md).

Watch the original video demo:

[![AGaMEMnon video demo][video-thumbnail]][video-demo]

[video-thumbnail]: https://img.youtube.com/vi/udDq3NHxerc/maxresdefault.jpg
[video-demo]: https://www.youtube.com/watch?v=udDq3NHxerc

## Quick start

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
python3 -m pip install -e ".[programming]"
agamemnon doctor --no-hardware
```

All required data is stored as ordinary Git objects; Git LFS is not required.
The repository includes a routed counter fixture that can be verified without
a board or FPGA toolchain:

```sh
agamemnon verify tests/fixtures/counter_ahb_routed.json --cycles 8
```

Create the fabric-free starting project:

```sh
agamemnon new hello --board ag32vf303-l48
cd hello
agamemnon build
agamemnon run --transport dap
```

This default needs only a compatible RISC-V GCC and runs from volatile SRAM.
`agamemnon doctor` reports separate inspection, MCU-build, fabric-build, and
hardware-transport capabilities.

Two larger templates are exact replays, not generic promises:

- `--template mcu-fpga` replays the reviewed L48 public32 AHB map: ID32
  `0x4147414d` at +0, scratch16 at +4, counter3 at +8, and W1C1 at +c.
- `--template serv-blinky` replays one retained L48 SERV route. Fresh arbitrary
  SERV placement, a fresh full parity claim, and wider direct-D placement are
  outside this profile.

The current checkout intentionally has a review gate on the public32
composition. If the composer reports `candidate hash does not match reviewed
artifact`, stop and review the semantic drift; do not repin the hash to make the
test green. See [Landing a chip-database change](docs/LANDING_A_CHIPDB_CHANGE.md).

## Hardware safety

SWD/DAP is the beginner-safe transport: it works on a stock board and supports
volatile MCU/fabric loads. The USB CDC uploader is convenient only after its
loader is installed. The Pico-driven UART0 mask-ROM path is the
flash-independent recovery route. Read [Programming](docs/PROGRAMMING.md) before
any persistent write and compare the setup with
[Known-good hardware](docs/KNOWN_GOOD_HARDWARE.md).

## Documentation

| Read | For |
|---|---|
| [Status](docs/STATUS.md) | authoritative support, exclusions, open defects, and current test state |
| [Vendor parity](docs/VENDOR_PARITY.md) | the 105-design campaign and its evidence limits |
| [Installation](docs/INSTALLATION.md) | host tools, bundles, and drivers |
| [Usage](docs/USAGE.md) | command reference and strict-build behavior |
| [Projects](docs/PROJECTS.md) | manifests and exact replay templates |
| [Programming](docs/PROGRAMMING.md) | DAP, USB, UART, and persistent-write safety |
| [Examples](examples/README.md) | runnable RTL and firmware with per-example scope |
| [MCU SDK](sdk/README.md) | open HAL coverage and qualification tiers |
| [MCU HAL reference](docs/HAL_MCU_REFERENCE.md) | MCU registers, drivers, and provenance |
| [FPGA HAL reference](docs/HAL_FPGA_REFERENCE.md) | fabric resources and configuration fields |
| [Architecture](docs/ARCHITECTURE.md) | synthesis, routing, bitgen, and verification layers |
| [Routing admission](docs/ROUTING_ADMISSION.md) | selector policy and what admission does not prove |
| [MCU/fabric boundary](docs/MCU_AHB_REGISTER_BANK.md) | exact AHB compositions and remaining gaps |
| [Hardware validation](docs/HARDWARE_VALIDATION.md) | board-observed evidence, including negative results |
| [Roadmap](ROADMAP.md) | prioritized correctness, breadth, and release work |
| [Notices](NOTICE.md) | licensing and recovered-data provenance |

The detailed [documentation index](docs/AG32_OVERVIEW.md#documentation-map)
links the remaining bitstream, clock, pin-routing, peripheral, qualification,
and research records.

## Contributing and support

New hardware evidence is especially valuable. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting code or qualification
records. Use [SUPPORT.md](SUPPORT.md) for unexpected behavior and
[SECURITY.md](SECURITY.md) for security reports. User-visible changes are in
[CHANGELOG.md](CHANGELOG.md).

## The name

AGaMEMnon: “AG” plus something about memory. It was named before Nolan's
*Odyssey* came out.
