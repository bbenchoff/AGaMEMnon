# Installation and tool bundles

AGaMEMnon's bounded L48 envelope fails closed on known unsupported typed
surfaces and ambiguous selectors. That is a safety policy, not a promise that
every accepted composition works: the reconciled campaign retains two
correctness escapes and fourteen no-image classifications. Install success and `doctor` capability tiers say
which tools are present; consult [STATUS.md](STATUS.md) separately for the
exact silicon-qualified design boundary.
Tagged releases publish hash-verified Windows and Linux SDK archives containing
the wheel, pinned RISC-V and FPGA tools, and offline smoke tests; source install
remains available on Windows, Linux, and macOS. The DAP tool has a separate
automatic, hash-verified Windows/Linux/macOS installer and release workflow.

## Current source installation

For the v0.4.0 release, select `--branch v0.4.0` in the clone command below.
Omitting it tracks development main. See [release scope](RELEASE_0_4_0.md),
and rebuild the matching native backend when upgrading an older checkout.

Python-only inspection, project creation, and offline verification work on
Windows, Linux, and macOS:

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
python3 -m pip install -e ".[programming]"
agamemnon --version
agamemnon doctor --no-hardware
```

On Windows, use `python` instead of `python3` if that is the installed launcher.
All required data is stored as normal Git objects; Git LFS is not required.

Setup is layered:

| Capability | Additional dependency |
|---|---|
| Decode, encode, inspect, scaffold, offline verify | None beyond Python and Git |
| Build MCU firmware | bundled `riscv-none-elf-gcc` or compatible `riscv64-unknown-elf-gcc` |
| Build FPGA fabric | Yosys plus AGaMEMnon's AGRV2K nextpnr backend |
| Program through USB CDC | pyserial and an already-installed target uploader |
| Program through SWD/DAP | CMSIS-DAP plus AGaMEMnon's qualified OpenOCD (`agamemnon install-openocd`) |
| Recover through UART mask ROM | Pico 2 bridge plus the documented board wiring |

The layers are capabilities, not evidence tiers. In particular, `FPGA-build`
means that synthesis, placement, routing, and bitgen can run on the host. It
does not mean a new design is vendor-equivalent or qualified on a board.

`doctor` checks Python, runtime database integrity, Yosys, the exact nextpnr executable
and runtime, RISC-V GCC, OpenOCD, pyserial, serial ports, the `cafe:4001` AG32
USB uploader, the Pico UART bridge, and connected AG32 targets over DAP/USB.
It reports independent inspection, MCU-build, FPGA-build, DAP, USB, and UART
capability tiers; a missing optional tool does not make the Python inspection
tier fail.
Use `--no-hardware` in CI and `--json` for machine-readable output. When the
USB uploader already identifies the target, DAP is not opened unless
`--probe-dap` is supplied, avoiding an unnecessary target reset. UART target
probing resets into ROM and therefore occurs only with an explicit
`--uart-port`.

## FPGA and MCU toolchains

Yosys is normally obtained from
[OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases).
Point `AGAMEMNON_OSS` at its root. Build the pinned AGRV2K nextpnr backend:

```sh
export AGAMEMNON_OSS=/opt/oss-cad-suite
./agamemnon/engine/uarch/agrv2k/build.sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"
```

On Windows PowerShell:

```powershell
$env:AGAMEMNON_OSS = "C:\tools\oss-cad-suite"
$env:AGAMEMNON_UARCH_NEXTPNR = "$PWD\third_party\nextpnr\build\nextpnr-generic.exe"
$env:AGAMEMNON_UARCH_NEXTPNR_RUNTIME = "C:\path\to\matching\runtime"
```

The nextpnr source build requires a native C++ toolchain, CMake, Boost, and
Eigen. `AGAMEMNON_UARCH_NEXTPNR_RUNTIME` is useful when a Windows executable
needs runtime DLLs that must not be mixed with OSS CAD Suite's environment.

Release bundles pin xPack's cross-platform `riscv-none-elf-gcc`. The MCU
compiler discovery also accepts `riscv64-unknown-elf-gcc`, `RISCV_PREFIX`, or
PlatformIO's pinned external `toolchain-agrv` package.

## OpenOCD status

Hardware SWD/DAP commands require an OpenOCD executable implementing AGM's
`target create riscv -dap` extension. Stock upstream and OSS CAD Suite OpenOCD
builds do not provide it. Install the qualified build:

```sh
agamemnon install-openocd
agamemnon doctor --probe-dap
```

The installer verifies the release sidecar hash, extracts to
`~/.agamemnon/tools/openocd/VERSION`, and records the executable and script
directory in `current.json`; `probe`, `backup`, `flash`, and `doctor` discover
it without environment variables. `--base-url` supports a mirror or local
release directory. Public GitHub releases need no token. Set `GH_TOKEN` or
`GITHUB_TOKEN` only for an authenticated mirror, private fork, or pre-release
test asset.

The exact inputs and build environments are pinned in
[`tools/openocd/manifest.json`](../tools/openocd/manifest.json). Each release
contains the platform binary, required Windows DLLs, complete patched source
and submodules, both patches, GPL text, build recipe, provenance, hashes, and
an SPDX 2.3 SBOM.

The release workflow produces binaries for Windows x64, Linux x64, and macOS
on both Apple Silicon (`macos-arm64`) and Intel (`macos-x64`);
`install-openocd` selects the correct one for the host. macOS archives include
their `libusb` and HIDAPI dylibs, license files, and exact upstream source
archives, so end users do not need Homebrew. The macOS arm64 build is
silicon-qualified on the L48 bench — firmware execution plus a
restore-verified destructive flash cycle:
[`docs/evidence/openocd-macos-ag32.json`](evidence/openocd-macos-ag32.json).
The Intel archive is independently built and parser-tested in CI but does not
claim a separate Intel-Mac hardware qualification.

The OS-Q executable is a known-working comparison oracle only. No packaging or
installer path copies it into an AGaMEMnon release. See [NOTICE.md](../NOTICE.md).

## Driver notes

- CMSIS-DAP uses the operating system HID driver. Do not replace it with a
  libusb driver on Windows; AGM-capable OpenOCD must be able to open the HID
  interface.
- The AG32 USB uploader and Pico bridge use USB CDC ACM. Windows 10/11 include
  the class driver. Linux normally creates `/dev/ttyACM*`; add the user to the
  distribution's serial-port group (commonly `dialout`) if access is denied.
- USB VID:PID `cafe:4001` is the qualified flash-resident uploader. It is not
  present on untouched factory firmware.
- The mask-ROM UART path requires the board harness change documented in
  [UART_BOOTLOADER.md](UART_BOOTLOADER.md).

## Development install

Toolchain contributors can still clone and build the pinned backend:

```sh
python -m pip install -e ".[programming]"
./agamemnon/engine/uarch/agrv2k/build.sh
agamemnon doctor
```

All dependency/source pins are centralized in
[`tools/bundle/manifest.json`](../tools/bundle/manifest.json). Bundle assembly
is described in [`tools/bundle/README.md`](../tools/bundle/README.md).

## Full SDK release bundles

Local Windows and Linux release candidates have completed the full offline
archive smoke, including CLI diagnostics, routed-fixture verification, MCU
compilation, strict FPGA+MCU compilation, and bit generation. The Windows
candidate also passed from a path containing spaces and non-ASCII characters;
the Linux candidate was assembled and verified from native ext4 staging. They
remain pre-release until hosted artifacts and SHA-256 sidecars are published
and independently downloaded/reproduced.

A published Windows or Linux SDK bundle will contain AGaMEMnon, OSS CAD
Suite/Yosys, the matching AGRV2K nextpnr and runtime libraries, and RISC-V GCC.
It can consume AGaMEMnon's paired OpenOCD binary/source output; the bundle
preflight still refuses any unpaired executable.

Once a release actually exists, the intended install commands are:

```powershell
./tools/install.ps1 -Version VERSION
```

```sh
sh tools/install.sh VERSION
```

The installers download the named archive and verify its published SHA-256,
extract into a versioned directory, create an isolated Python environment,
install only from the archive's wheel directory, activate the bundled tools,
and run `doctor --no-hardware`. They do not contact a Python package index.
Python 3.8-3.10 bundles therefore include the pinned `tomli` wheel; Python
3.11+ uses the standard-library TOML parser. Release notes must state whether
the archive is build-only or also DAP-programming capable.

Windows bundle paths may contain spaces and non-ASCII characters. AGaMEMnon
works around native nextpnr/Yosys path limitations by staging only the pinned
nextpnr executable and synthesis support files into a content-addressed ASCII
cache. The bundled runtime and user project stay in place. If the default
temporary directory is not writable or is also non-ASCII, set
`AGAMEMNON_ASCII_TOOL_CACHE` to a writable ASCII-only directory.
