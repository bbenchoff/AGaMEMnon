# Installation and tool bundles

AGaMEMnon is currently a source-installable development preview. There is no
published SDK archive yet. The repository contains bundle construction and
installer machinery, but `tools/install.*` will not work until a matching tag,
archive, and SHA-256 file appear on the GitHub Releases page.

## Current source installation

Python-only inspection, project creation, and offline verification work on
Windows, Linux, and macOS:

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
git lfs install
git lfs pull
python3 -m pip install -e ".[programming]"
agamemnon --version
agamemnon doctor --no-hardware
```

On Windows, use `python` instead of `python3` if that is the installed launcher.
Git LFS is required: a checkout containing pointer text instead of the chip
database will fail `doctor`.

Setup is layered:

| Capability | Additional dependency |
|---|---|
| Decode, encode, inspect, scaffold, offline verify | None beyond Python and Git LFS |
| Build MCU firmware | `riscv64-unknown-elf-gcc` |
| Build FPGA fabric | Yosys plus AGaMEMnon's AGRV2K nextpnr backend |
| Program through USB CDC | pyserial and an already-installed target uploader |
| Program through SWD/DAP | CMSIS-DAP plus AGM-compatible OpenOCD |
| Recover through UART mask ROM | Pico 2 bridge plus the documented board wiring |

`doctor` checks Python, Git LFS payloads, Yosys, the exact nextpnr executable
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

The MCU compiler is discovered as `riscv64-unknown-elf-gcc`, through
`RISCV_PREFIX`, or in PlatformIO's pinned `toolchain-agrv` package.

## OpenOCD status

Hardware SWD/DAP commands require an OpenOCD executable implementing AGM's
`target create riscv -dap` extension. Stock upstream and OSS CAD Suite OpenOCD
builds do not provide it. Set:

```sh
export AGAMEMNON_OPENOCD=/path/to/compatible/openocd
export AGAMEMNON_OOCD_SCRIPTS=/path/to/openocd/scripts
```

The known os-q Windows binary is a useful local development fallback, but it
is not a redistributable release input because its exact patched GPL source is
not available in the pinned repository. See [NOTICE.md](../NOTICE.md).

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
git lfs install
git lfs pull
python -m pip install -e ".[programming]"
./agamemnon/engine/uarch/agrv2k/build.sh
agamemnon doctor
```

All dependency/source pins are centralized in
[`tools/bundle/manifest.json`](../tools/bundle/manifest.json). Bundle assembly
is described in [`tools/bundle/README.md`](../tools/bundle/README.md).

## Future release bundles

A published Windows or Linux build bundle will contain AGaMEMnon, OSS CAD
Suite/Yosys, the matching AGRV2K nextpnr and runtime libraries, and RISC-V GCC.
It may omit OpenOCD and remain a complete build SDK. If compatible OpenOCD is
included, the bundle builder requires and ships its exact corresponding GPL
source.

Once a release actually exists, the intended install commands are:

```powershell
./tools/install.ps1 -Version VERSION
```

```sh
sh tools/install.sh VERSION
```

The installers download the named archive and verify its published SHA-256
before extraction. Release notes must state whether the archive is build-only
or also DAP-programming capable.
