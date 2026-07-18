# Release bundles

`manifest.json` is the single pin list for Windows and Linux SDK bundles.
`build_bundle.py` consumes already built/verified tool trees and produces a
relocatable archive containing the AGaMEMnon wheel, OSS CAD Suite, the AGRV2K
nextpnr binary and its exact runtime, and a RISC-V GCC toolchain. Compatible
OpenOCD is optional: when it is supplied, its exact corresponding GPL source
is mandatory and is copied into the archive.

Release automation must build nextpnr from the pinned commit plus
`agamemnon/engine/uarch/agrv2k/agrv2k.cc`, run the repository test suite, run
the archive smoke test below, and publish both the archive and SHA-256
checksum. The external AGM SDK is intentionally not redistributed because its
pinned tree lacks a top-level license.

The assembler validates the wheel version and required runtime files, checks
the disclosed `fabric_default.bin` hash, copies the project license and notice,
and emits `COMPONENTS.json`. That inventory records each top-level input's
pin, license expression, bundled path, byte/file count, and deterministic tree
hash. The nested OSS CAD Suite and GNU toolchain components retain their
upstream notices; the top-level inventory does not replace those.

`fetch_tools.py` downloads the exact host assets named in `manifest.json`,
checks their SHA-256 before extraction, and returns the OSS CAD Suite and
RISC-V toolchain roots:

```text
python tools/bundle/fetch_tools.py \
  --platform linux-x64 \
  --output .tmp/release-tools \
  --json-output .tmp/release-tools.json
```

The release compiler is xPack `riscv-none-elf-gcc` 15.2.0-1 on both Windows
and Linux. The older OS-Q Windows compiler remains pinned only as part of the
external PlatformIO ecosystem; it is not the cross-platform bundle input.
The Windows workflow stages only the DLL closure reported for its nextpnr
executable, together with the MSYS2 license tree; the assembler rejects a
runtime directory that lacks either DLLs or license texts.

Example Windows build-only assembly:

```powershell
python tools/bundle/build_bundle.py `
  --oss C:/tools/oss-cad-suite `
  --nextpnr third_party/nextpnr/build/nextpnr-generic.exe `
  --nextpnr-license third_party/nextpnr/COPYING `
  --nextpnr-runtime C:/build/nextpnr-runtime `
  --toolchain C:/tools/xpack-riscv-none-elf-gcc-15.2.0-1 `
  --wheel dist/agamemnon_ag32-0.1.0-py3-none-any.whl `
  --dependency-wheel dist/tomli-2.0.1-py3-none-any.whl `
  --output dist/agamemnon-sdk-windows-x64
```

Example Linux build-only assembly:

```sh
python tools/bundle/build_bundle.py \
  --oss /opt/oss-cad-suite \
  --nextpnr third_party/nextpnr/build/nextpnr-generic \
  --nextpnr-license third_party/nextpnr/COPYING \
  --toolchain /opt/xpack-riscv-none-elf-gcc-15.2.0-1 \
  --wheel dist/agamemnon_ag32-0.1.0-py3-none-any.whl \
  --dependency-wheel dist/tomli-2.0.1-py3-none-any.whl \
  --output dist/agamemnon-sdk-linux-x64
```

The pinned universal `tomli` wheel is mandatory so the same archive installs
offline on Python 3.8-3.10; Python 3.11+ simply ignores it. Download it with
the hash-locked `python-requirements.txt`. Dependency wheels are copied into
`packages/` and the smoke test installs only from that directory.

## Clean archive smoke test

Run this against the archive, not the assembly directory:

```text
python tools/bundle/smoke_archive.py dist/agamemnon-sdk-windows-x64.zip
python tools/bundle/smoke_archive.py dist/agamemnon-sdk-linux-x64.tar.gz
```

The runner verifies the adjacent `.sha256`, safely extracts into a clean
temporary directory, creates a virtual environment, disables package-index
access, and installs the bundled wheel. It then requires:

- exact agreement between wheel and bundle versions;
- `doctor --no-hardware` readiness for inspect, MCU-build, and FPGA-build;
- offline verification of the bundled routed counter fixture;
- compilation of the maintained `mcu-blink` project;
- synthesis, place/route, bit generation, and MCU compilation of the
  maintained `fpga-blink` project.

Any missing runtime DLL, package-data file, compiler, or tool pin therefore
fails the release artifact rather than only the editable source checkout.

`.github/workflows/sdk-bundle.yml` performs this complete process for Windows
and Linux x64 on demand and for version tags: clean LFS checkout, verified tool
download, pinned nextpnr build, wheel/bundle assembly, archive-level smoke
test, and release-candidate artifact upload.

Add both of these arguments to produce a DAP-capable bundle:

```text
--openocd /path/to/compatible/openocd
--openocd-source /path/to/its/exact/corresponding/source
```

## AGaMEMnon OpenOCD

Hardware SWD/DAP commands need an OpenOCD that carries AGM's `riscv -dap` target
extension; stock upstream and OSS CAD Suite builds do not have it. Every bundle
that includes OpenOCD ships it under `tools/openocd`, and `activate.{ps1,sh}`
points `AGAMEMNON_OPENOCD` at it. A build-only bundle omits those paths and
`agamemnon doctor` reports DAP/SWD programming as unavailable. When present,
`doctor` reports `OpenOCD AGM DAP: PASS` only when the `-dap` target is found.

Provenance is pinned per platform in `manifest.json` under `pins.openocd`.
`build_bundle.py` requires the executable tree and source tree as a pair. It
parser-probes `target create riscv -dap`, checks for the RISC-V source and GPL
text, then includes the source under `sources/openocd`. Supplying only one of
`--openocd` and `--openocd-source` is an error.

AGaMEMnon now builds its own qualified OpenOCD release from official parent
`a17c5f5a`, Gerrit 9590 patchset 2, and the separate nested-config repair.
`tools/openocd/release.py` produces the executable tree and the complete
patched source tree required by this bundle preflight.

The pinned OS-Q Windows package remains a comparison oracle only. It is not a
release or bundle input.

Platform notes:

- **Windows** — use `agamemnon-openocd-windows-x64.zip` and the paired source
  archive from the same release.
- **Linux** — use `agamemnon-openocd-linux-x64.tar.gz` and the same paired
  source archive.
- **macOS Apple Silicon** — use `agamemnon-openocd-macos-arm64.tar.gz`; this
  host path passed the complete AG32 silicon gate.
- **macOS Intel** — use `agamemnon-openocd-macos-x64.tar.gz`; this host path is
  build- and parser-qualified but has no independent Intel-Mac silicon record.

The macOS archives carry their `libusb` and HIDAPI dylibs, license files, and
exact upstream source archives; installation does not require Homebrew. Both
remain paired with the same platform-independent patched OpenOCD source
archive.
