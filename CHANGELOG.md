# Changelog

All notable user-visible changes will be recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) in spirit. Version
numbers are not promises that an archive has been published; the Releases page
is authoritative for downloadable artifacts.

## [Unreleased]

### Added

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

## [0.1.0]

### Added

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

### Changed

- Installation documentation now identifies the project as a source-installable
  preview until release archives and checksums actually exist.
- Release bundles may omit OpenOCD and remain useful for MCU/fabric builds.
  Bundles that include it consume AGaMEMnon's paired binary and complete GPL
  source release.
- Qualified board naming is consistently `AG32VF303CCT6` with `AGRV2KL48`
  fabric.

### Known limitations

- No tagged SDK bundle has been published.
- Linux and macOS Intel OpenOCD are build- and parser-qualified but still need
  physical host-specific USB/DAP bench runs.
- Physical routing and current silicon claims are L48-specific.
- The open MCU HAL and hard-peripheral qualification are incomplete.
