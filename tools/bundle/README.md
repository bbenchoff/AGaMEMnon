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
