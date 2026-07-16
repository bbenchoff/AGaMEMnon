# Release bundles

`manifest.json` is the single pin list for Windows and Linux SDK bundles.
`build_bundle.py` consumes already built/verified tool trees and produces a
relocatable archive containing the AGaMEMnon wheel, OSS CAD Suite, the AGRV2K
nextpnr binary and its exact runtime, a RISC-V GCC toolchain, and compatible
OpenOCD.

Release automation must build nextpnr from the pinned commit plus
`agamemnon/engine/uarch/agrv2k/agrv2k.cc`, run the repository test suite, run
`agamemnon doctor --no-hardware` from the assembled archive, and publish both
the archive and SHA-256 checksum. The external AGM SDK is intentionally not
redistributed because its pinned tree lacks a top-level license.

Example Windows assembly:

```powershell
python tools/bundle/build_bundle.py `
  --oss C:/tools/oss-cad-suite `
  --nextpnr third_party/nextpnr/build/nextpnr-generic.exe `
  --nextpnr-runtime C:/msys64/mingw64/bin `
  --toolchain $HOME/.platformio/packages/toolchain-agrv `
  --openocd $HOME/.platformio/packages/tool-agrv_openocd `
  --wheel dist/agamemnon_ag32-0.1.0-py3-none-any.whl `
  --output dist/agamemnon-sdk-windows-x64
```

Example Linux assembly:

```sh
python tools/bundle/build_bundle.py \
  --oss /opt/oss-cad-suite \
  --nextpnr third_party/nextpnr/build/nextpnr-generic \
  --toolchain "$HOME/.platformio/packages/toolchain-agrv" \
  --openocd /opt/agrv-openocd \
  --wheel dist/agamemnon_ag32-0.1.0-py3-none-any.whl \
  --output dist/agamemnon-sdk-linux-x64
```

## Compatible OpenOCD

Hardware SWD/DAP commands need an OpenOCD that carries AGM's `riscv -dap` target
extension; stock upstream and OSS CAD Suite builds do not have it. Every bundle
ships one under `tools/openocd`, and `activate.{ps1,sh}` points
`AGAMEMNON_OPENOCD` at it. `agamemnon doctor` reads the binary and reports
`OpenOCD AGM DAP: PASS` only when the `-dap` target is present, so a bundle can
be verified before it is published.

Provenance is pinned per platform in `manifest.json` under `pins.openocd`:

- **Windows** — the prebuilt AGM package `os-q/tool-agrv_openocd`; pass its root
  to `--openocd`.
- **Linux / macOS** — AGM publishes the extension prebuilt for Windows only.
  Build the pinned `pins.openocd.base` commit with AGM's `riscv -dap` target
  applied, or extract the `openocd` binary from an installed vendor toolchain,
  and pass that root to `--openocd`. If the AGM target source is unavailable for
  a platform, that is the remaining blocker to a fully self-contained non-Windows
  bundle; until then a user can point `AGAMEMNON_OPENOCD` at any locally built
  compatible OpenOCD.
