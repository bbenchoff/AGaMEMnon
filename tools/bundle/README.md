# Release bundles

`manifest.json` is the single pin list for Windows and Linux SDK bundles.
`build_bundle.py` consumes already built/verified tool trees and produces a
relocatable archive containing the AGaMEMnon wheel, OSS CAD Suite, the AGRV2K
nextpnr binary and its exact runtime, and a RISC-V GCC toolchain. Compatible
OpenOCD is optional: when it is supplied, its exact corresponding GPL source
is mandatory and is copied into the archive.

Release automation must build nextpnr from the pinned commit plus
`agamemnon/engine/uarch/agrv2k/agrv2k.cc`, run the repository test suite, run
`agamemnon doctor --no-hardware` from the assembled archive, and publish both
the archive and SHA-256 checksum. The external AGM SDK is intentionally not
redistributed because its pinned tree lacks a top-level license.

Example Windows build-only assembly:

```powershell
python tools/bundle/build_bundle.py `
  --oss C:/tools/oss-cad-suite `
  --nextpnr third_party/nextpnr/build/nextpnr-generic.exe `
  --nextpnr-runtime C:/msys64/mingw64/bin `
  --toolchain $HOME/.platformio/packages/toolchain-agrv `
  --wheel dist/agamemnon_ag32-0.1.0-py3-none-any.whl `
  --output dist/agamemnon-sdk-windows-x64
```

Example Linux build-only assembly:

```sh
python tools/bundle/build_bundle.py \
  --oss /opt/oss-cad-suite \
  --nextpnr third_party/nextpnr/build/nextpnr-generic \
  --toolchain "$HOME/.platformio/packages/toolchain-agrv" \
  --wheel dist/agamemnon_ag32-0.1.0-py3-none-any.whl \
  --output dist/agamemnon-sdk-linux-x64
```

Add both of these arguments to produce a DAP-capable bundle:

```text
--openocd /path/to/compatible/openocd
--openocd-source /path/to/its/exact/corresponding/source
```

## Compatible OpenOCD

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

The pinned os-q Windows package by itself is **not publishable**. Its repository
contains the executable and runtime DLLs but no corresponding patched source
or license text, even though the executable identifies itself as GPLv2. The
bundle preflight rejects that binary-only input instead of creating an
accidental GPL violation.

Platform notes:

- **Windows** — the prebuilt AGM package `os-q/tool-agrv_openocd`; pass its root
  to `--openocd` only when the exact source tree is also supplied through
  `--openocd-source`.
- **Linux / macOS** — AGM publishes the extension prebuilt for Windows only.
  Build the pinned `pins.openocd.base` commit with AGM's `riscv -dap` target
  applied, or extract the `openocd` binary from an installed vendor toolchain,
  and pass that root to `--openocd`. If the AGM target source is unavailable for
  a platform, that is the remaining blocker to a fully self-contained non-Windows
  bundle; until then a user can point `AGAMEMNON_OPENOCD` at any locally built
  compatible OpenOCD.
