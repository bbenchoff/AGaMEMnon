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

AGaMEMnon now publishes its own compatible OpenOCD from official parent
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
- **macOS** — no qualified prebuilt artifact yet; a local compatible build can
  still be passed with its exact source tree.
