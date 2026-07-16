# AGaMEMnon MCU SDK strategy

AGaMEMnon owns an explicitly open, freestanding MCU layer under
`agamemnon/sdk/`. It is the stable substrate used by generated projects:

- the AG32VF303 digital instance map;
- CLINT, System Control, FCB, GPIO4, and basic-timer accessors already proven
  by the repository examples;
- L48 board names and qualified LED mappings;
- startup and SRAM/native-flash/USB-application linker scripts;
- direct GCC project builds through `agamemnon build`;
- an optional CMake toolchain for editors and larger applications.

The existing `os-q/framework-agrv_sdk` is useful and substantially more
complete, but commit `3c729cb4745330e8cd1c9aac48c73bdf997fc9b0` does not ship
a top-level license file. AGaMEMnon therefore does **not** copy or redistribute
its drivers. Users may install it independently through the pinned PlatformIO
platform when they have reviewed its provenance and licensing.

The policy is incremental: promote a peripheral into the open AGaMEMnon HAL
only with a documented register source, a host test, and preferably silicon
qualification. Compatibility names may be supplied for migration, but the
unlicensed external framework is not a hidden runtime dependency of the open
SDK.

## CMake

```powershell
cmake -S . -B build `
  -DCMAKE_TOOLCHAIN_FILE=C:/path/to/AGaMEMnon/sdk/cmake/ag32-riscv.cmake
cmake --build build
```

Generated projects use the same compiler flags directly, so CMake is optional.
The compiler is resolved from `PATH`, `RISCV_PREFIX`, or PlatformIO's
`toolchain-agrv` installation.

## Full AGM PlatformIO framework

The external integration pins:

- `os-q/platform-agm32` at `71f4c316c849c3e6b117b4830330360bbd61359b`
- `os-q/framework-agrv_sdk` at `3c729cb4745330e8cd1c9aac48c73bdf997fc9b0`
- `os-q/framework-agrv_tinyusb` at `031adf292bdc967a6b5edd800f153b6480f5a4b0`

These pins are recorded in `tools/bundle/manifest.json`. The `usb-cdc`
project template shows the external PlatformIO boundary and points to the
qualified patches rather than silently downloading mutable upstream heads.
