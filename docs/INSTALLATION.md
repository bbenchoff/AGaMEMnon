# Installation and tool bundles

The supported end-user distribution is a version-pinned AGaMEMnon SDK bundle,
not a locally assembled C++ development environment. Each release bundle
contains AGaMEMnon, OSS CAD Suite/Yosys, the matching AGRV2K nextpnr and runtime
libraries, RISC-V GCC, and AGM-capable OpenOCD.

Release installers download the versioned archive and verify its published
SHA-256 before extraction:

```powershell
./tools/install.ps1 -Version 0.1.0
```

```sh
sh tools/install.sh 0.1.0
```

After extracting a bundle, activate it and run the diagnostic:

```powershell
./activate.ps1
python -m pip install packages/agamemnon_ag32-*.whl
agamemnon doctor
```

```sh
. ./activate.sh
python3 -m pip install packages/agamemnon_ag32-*.whl
agamemnon doctor
```

`doctor` checks Python, Git LFS payloads, Yosys, the exact nextpnr executable
and runtime, RISC-V GCC, OpenOCD, pyserial, serial ports, the `cafe:4001` AG32
USB uploader, the Pico UART bridge, and connected AG32 targets over DAP/USB.
Use `--no-hardware` in CI and `--json` for machine-readable output. When the
USB uploader already identifies the target, DAP is not opened unless
`--probe-dap` is supplied, avoiding an unnecessary target reset. UART target
probing resets into ROM and therefore occurs only with an explicit
`--uart-port`.

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
