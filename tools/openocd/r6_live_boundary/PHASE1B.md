# R6 live-boundary Phase1B deterministic minimal build

Status: **two-build reproducible static-audit candidate; independent review required; execution refused**.

Phase1B is an exact child of independently accepted Phase1A
`5b03850c0197a861be170a4c82aac9e8b1bfc5b4`. It authorizes compilation of the
frozen inputs and nothing live. The built OpenOCD PE was never invoked, including
with `--version`. USB enumeration, debugger access, board locks, evidence
sessions, and hardware contact remain forbidden.

## Deterministic source boundary

`phase1b.py prepare` first revalidates the accepted Phase1A toolchain, exact
OpenOCD/JimTcl commits and trees, official libusb 1.0.30 archive, extracted
archive projection, and all three frozen patches. It then copies only source
content, excluding Git administrative files and Phase-0 generated custody
members, and applies:

- the deny-only earliest-main and `--without-ext=load` OpenOCD patch;
- the JimTcl loader-shim guard; and
- the WinUSB-only libusb patch.

The resulting immutable projection contains 2,640 OpenOCD/JimTcl/libjaylink
files and 151 libusb files. Canonical prepared provenance binds the input
commits, tree, archive, patches, postpatch files, complete file counts, byte
counts, and inventory-record digests. The build script revalidates that
provenance, requires a fresh empty root, and copies the sources into that root
before Autotools can mutate them.

## Narrow build

The build uses the accepted MSYS2 UCRT64 snapshot and the official frozen
libusb source. libusb is regenerated, compiled static, and staged at the fixed
logical prefix `/opt/agamemnon-libusb`. No installed or system libusb archive is
an admitted link input. Its exact archive contains eleven members:

`core.o`, `descriptor.o`, `hotplug.o`, `io.o`, `strerror.o`, `sync.o`,
`events_windows.o`, `threads_windows.o`, `libusb-1.0.o`, `windows_common.o`,
and `windows_winusb.o`.

OpenOCD is configured at the fixed logical prefix `/opt/agamemnon-openocd` with
internal JimTcl, CMSIS-DAP v2 USB bulk enabled, and every other inventoried
adapter disabled. `PKG_CONFIG_LIBDIR`, include flags, and final link inputs point
only into the staged source-built libusb tree. `DESTDIR` preserves the fixed
compile-time prefixes while installing into an isolated disposable root.

The first exploratory builds were rejected as qualification evidence. One used
sources outside the mapped root; a later pair exposed two remaining variable
prefix strings in `jim.o` and `options.o`. The fixed logical-prefix/`DESTDIR`
construction removed that drift. Only fresh corrected runs 5 and 6 form the
candidate evidence, and they match exactly across the PE, three archives, all
348 object records, archive membership, normalized configure/link commands,
imports, adjacent files, private-string scan, and final disassembly.

## Frozen static result

- `openocd.exe`: 126,494 bytes, SHA-256
  `b1e88a703280f90ae444cd6f2c8921267f5db29e119e48b49b3befe794b85ea2`;
- source-built `libusb-1.0.a`: 234,454 bytes,
  `56bbd99dbc584ee3415f8991a8aaca3f9b3d878359e100f657c5570f1263b6fa`;
- `libopenocd.a`: 5,322,644 bytes,
  `c2fb0b271f34b2bf3ccdd1d371fb1d173ed7c92c6483f41af982d26b2bcd5e27`;
- `libjim.a`: 376,388 bytes,
  `086f80252236101c158634d47a42c39493aaf656bd3555269f573c7f6f086e71`;
- 348-object record digest:
  `3e9808a1fe7953d1b9bb7696d632e74dc1b67699ec358b75f776f67092e312e4`.

The final bin directory contains only `openocd.exe`. Direct imports are
`KERNEL32.dll` plus the eight frozen UCRT API-set DLLs; the delay-import
directory is empty. No private build path marker appears in the PE.
`jim-load.o` is absent, and `jim-win32compat.o` has no undefined
`LoadLibraryA`, `GetProcAddress`, `dlopen`, or `dlsym` symbol.

The compiler inlines the unconditional deny helper. Final `main` therefore
calls the compiler runtime `__main`, loads exit code 70, and returns. It has no
call to `setvbuf` or `openocd_main`. Configured CMSIS-DAP/libusb implementation
objects are present and hash-bound in the build archives, but the deny-only PE
cannot reach them. Replacing this gate is a later separately reviewed wave.

## Reproduction and audit

From the candidate repository root:

```powershell
python tools/openocd/r6_live_boundary/phase1b.py prepare `
  --source <accepted-pristine-openocd-source> `
  --libusb-archive <official-libusb-1.0.30.tar.bz2> `
  --libusb-source <pristine-libusb-1.0.30> `
  --output <fresh-prepared-root>
```

Then, inside the accepted MSYS2 UCRT64 shell:

```sh
bash tools/openocd/r6_live_boundary/phase1b_build.sh \
  <verified-prepared-root> <fresh-build-root>
```

The script terminates with
`PASS_PHASE1B_BUILD_COMPLETE_OPENOCD_NOT_EXECUTED`; it contains no launch or
version-probe step. After committing the exact candidate, run:

```powershell
python tools/openocd/r6_live_boundary/phase1b.py audit `
  --prepared-root <verified-prepared-root> `
  --build-root <build-root>
python -m pytest tools/openocd/r6_live_boundary/test_phase1b.py
python -m pytest tools/openocd/r6_live_boundary/test_phase1a.py
python -m pytest tools/openocd/r6_live_boundary/test_phase0.py
python -m pytest tests/test_openocd_bundle.py
```

Only an unchanged independent static audit may accept Phase1B. Even acceptance
does not authorize executing the PE. Two independent live-readiness audits, a
separately frozen one-shot authorization gate, and an explicit board-GO remain
mandatory before a single live session.
