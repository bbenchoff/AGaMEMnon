# R6 live-boundary Phase1A desk contract

Status: **builder-green desk-input and deny-gate candidate; compilation and execution refused**.

This exact child starts from independently accepted Phase-0 v11
`2fee9bce38980f42bfb08ab479f89199cdf0ede3`. It resolves the two observed
tool-version mismatches, freezes patches for the libusb and JimTcl runtime
loader surfaces, and defines an earliest-main gate that denies every
invocation before stdio setup or `openocd_main()`. It does not build or run
OpenOCD, authorize USB enumeration, contact hardware, or claim live readiness.

## Exact toolchain decision

Phase1A accepts the already observed MSYS2 UCRT64 snapshot rather than claiming
that a rolling CI installation is reproducible:

- GCC package `16.1.0-5`, `gcc.exe` SHA-256
  `f96a3bdb1d3a3967b309d75c7413399391e857b5be4cb17162572ed66f6772a0`;
- pkgconf package `1~2.5.1-2`, `pkgconf.exe` SHA-256
  `f605c5fe827ad466b492d36ef87ee4a1a0e5f9435eb3140288a8e37f8510b974`;
- the matching cached package archives and signatures are size/hash bound in
  `phase1a_manifest.json`.

`tools/openocd/manifest.json` and the read-only observation now agree exactly.
The build script already calls `verify-environment` before bootstrap, so a
newer rolling package remains a hard failure. A later build must provision the
frozen snapshot explicitly; the current GitHub Actions `update: true` path is
not Phase1A-authorized.

## Frozen source inputs

The official libusb 1.0.30 release archive is frozen at 656,112 bytes and
SHA-256 `fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf`.
The patch applies exactly to its three named prepatch files and:

- removes the UsbDk object from the Automake source list;
- removes UsbDk initialization, selection, and teardown;
- removes the libusbK DLL-loading path;
- admits only the Microsoft WinUSB sub-API;
- retains libusb's absolute `GetSystemDirectoryA` resolution of `WinUSB.dll`.

The existing installed `libusb-1.0.a` is not an admitted future link input.
Phase1A freezes the source/patch policy; building that source and proving final
archive membership remain later gates.

The OpenOCD patch adds `--without-ext=load` to both internal JimTcl configure
paths. The JimTcl patch additionally compiles its MinGW
`LoadLibraryA`/`GetProcAddress` shim only when `jim_ext_load` exists. A later
object audit must prove `jim-load.o` absent and `jim-win32compat.o` free of those
imports. Bootstrap-only `jimsh0`, unselected `jim-win32`, and unselected SQLite
sources must not appear in final membership.

## Earliest-main boundary

The source patch places `r6_live_boundary_gate(argc, argv)` as the first action
inside `src/main.c:main`. Phase1A deliberately gives that function no calls, no
authorization input, and no desk override; it unconditionally returns exit code
70. Therefore the patched source cannot reach either `setvbuf` call or
`openocd_main()`.

This is a safe construction boundary, not the final one-shot authorization
implementation. Replacing deny-only behavior requires a separately frozen
child, exact authorization-envelope contract, and independent review.

## Reproduction

Using exact OpenOCD source `f96d840a...`, JimTcl `f1608661...`, the official
libusb archive, its pristine extracted top-level directory, and the frozen MSYS2
package cache:

```powershell
python tools/openocd/r6_live_boundary/phase1a.py `
  --source <exact-openocd-source> `
  --libusb-archive <libusb-1.0.30.tar.bz2> `
  --libusb-source <pristine-libusb-1.0.30>
python -m pytest tools/openocd/r6_live_boundary/test_phase1a.py
python -m pytest tools/openocd/r6_live_boundary/test_phase0.py
python -m pytest tests/test_openocd_bundle.py
```

The first command is read-only and reports
`PASS_PHASE1A_DESK_CONTRACT_COMPILE_REFUSED`. Patch application is checked with
no fuzz and whitespace errors rejected. The tests reject authority expansion,
unknown schema fields, duplicate JSON keys, tool/input mutation, loader-policy
weakening, alternate libusb backends, a desk override, and premature final
object/disassembly claims.

The validator also binds the complete semantic identity of the Phase1A
manifest, requires a clean single-parent candidate directly above accepted v11,
and freezes the complete 14-path candidate inventory. A placeholder future-gate
list, removed forbidden object/library, weakened system-library resolution,
deleted entry-gate order, merge commit, accepted-parent checkout, path drift, or
dirty candidate worktree rejects before the PASS marker.

## Remaining gates

Before any compilation, a separate child must integrate the three patches into
deterministic prepared-source provenance and wire the build exclusively to the
frozen libusb source rather than the installed library. After compilation is
separately authorized, an exact audit must cover every object/archive member,
linker flag,
direct and delay PE import, adjacent DLL, JimTcl loader symbol, libusb backend,
and the deny gate's final disassembly order. Two independent live-readiness
audits and a later one-shot board authorization remain mandatory.
