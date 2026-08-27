# R6 live-boundary rebuild: Phase 0

Phase 0 freezes and audits the inputs to a prospective Windows OpenOCD rebuild.
Its only green state is `PASS_PHASE0_SOURCE_INVENTORY_COMPILE_REFUSED`: the exact
source and policy inventory is reproducible, while compilation and every live
operation remain refused.

This directory does not authorize a build, an OpenOCD launch, debugger access,
USB or device enumeration, a board lock, a GO transition, evidence creation, or
hardware contact.  It contains no code path that performs any of those actions.

## Frozen source

The deterministic `tools/openocd/release.py prepare` workflow reconstructed:

- upstream base `a17c5f5a6dac6625cd5b01dfc3234f57cb58f1f3`;
- Gerrit change 9590 patch set 2, commit
  `9aa0f9765801e06ad79775ee0dde95de9a2a0a66`;
- tracked patch result `f96d840a24e0c6694815293b803e18b535663c00`;
- source tree `c8566e47651259bdca5897a9ffbd14172d38cd20`;
- JimTcl `f160866171457474f7c4d6ccda70f9b77524407e`; and
- libjaylink `0d23921a05d5d427332a142d154c213d0c306eb1`.

The source has 2,640 tracked files when submodules are traversed: 489 C files,
298 headers, and 27 `Makefile.am` files.  It contains 49 explicitly allowlisted,
tree-bound firmware and test fixtures with `.bin`, `.hex`, `.elf`, or `.map`
suffixes.  Some ELF fixtures are executable images; they are source inputs, not
products of this reconstruction.  Only those exact tracked paths are exempt.
Each exemption has an exact SHA-256 in the independently bound
`tracked_fixture_artifacts.json`; path additions, removals, and content changes
all fail closed.
The audit rejects every unlisted artifact suffix, ignored `.a`/`.lib` archive,
versioned shared library, and named build-output directory anywhere outside Git
metadata.  It does not infer an artifact merely from a tracked file's executable
permission bit.  It also checks that the fetched Gerrit commit exists with the
frozen base as its parent, then cross-checks generated provenance and both copied
patch hashes.

The extensionless and directory policy is derived from thirty-one exact, SHA-256-bound
`.gitignore`, configure, Make, and helper-script sources.  It explicitly catches
nine possible products, including `src/openocd`, `jimtcl/jimsh`,
`jimtcl/jimsh0`, and `jimtcl/build-jim-ext`, plus nine generated-directory
classes.  Independently, exact Git ignored-file enumeration must be empty in the
root and both submodules except for the two preparation-created
`AGAMEMNON-PATCHES` copies, whose paths and hashes are frozen.  Ignored generated
directories must always be empty.  There is no build-product exemption.

An inventory-independent active-build-rule pass scans Make, configure, and
Doxygen inputs for literal directory creation.  It derives `.dep` from exactly
eight `testing/examples` makefiles and also re-derives `build-aux`, `doxy`, and
`doxygen`; every discovered source must be hash-bound and represented in the
directory evidence.  Commented rules do not count.  This catches a non-ignored,
empty `.dep` directory that Git ignored-file enumeration cannot report, and a
self-consistent omission from the hand-maintained inventory is rejected.

The same independent pass separately freezes all 41 active directory-creation
occurrences, including unresolved or variable-mediated expressions: dynamic
`dirname` destinations, Automake `%D%`, Angie HDL build variables, Espressif
`$@` targets, release and cross-build shell scripts, JimTcl install-directory
aliases, autosetup and test Tcl `file mkdir`, and the eight literal `.dep`
rules.  Every occurrence has an exact source, line,
expression, kind, reviewed disposition, and any resolved forbidden ancestor or
basename.  Additions, removals, alias uses, and expression changes fail closed.

## Intended narrow build

The future configure plan explicitly disables every discovered adapter except
CMSIS-DAP v2 USB bulk.  The plan keeps only the CMSIS-DAP core, USB-bulk backend,
and libusb helper on the adapter path.  It also requires static non-system
dependencies so that the final PE may import only a frozen Windows system-DLL
allowlist and API-set DLLs.  Delay imports and adjacent runtime DLLs are refused.

These are plans, not build results.  Configure flags, compiled object membership,
archive membership, linker flags, direct imports, and delay imports must all be
re-derived and independently checked after the inputs below are reviewed.

The backend inventory distinguishes the one selected real implementation
(`cmsis_dap_usb_bulk.c`) from the excluded HID and TCP implementations.  OpenOCD
keeps inert HID and TCP descriptors in the CMSIS-DAP core even when their real
implementations are disabled; Phase 0 records and checks that distinction.  Its
object inventory is intentionally empty and separately freezes required and
excluded source stems for the future post-build object audit.

## Earliest process boundary

The proposed `r6_live_boundary_gate` belongs at the first statement of
`src/main.c:main`, before either `setvbuf` call and before `openocd_main`.
That ordering is earlier than command registration, command-line parsing,
configuration parsing, `server_preinit`, `server_init`, and the OpenOCD `init`
command.  Phase 0 records and tests this insertion window; it does not implement
the gate.

The later gate must be side-effect minimal and fail closed before any potentially
contacting code.  Its contract and implementation require a separate review.

## Static risk inventory

The comment/string-aware call scan freezes 26 executable-looking direct and
indirect loader/resolver calls across seven JimTcl paths.  It distinguishes
declarations and definitions from calls and covers `dlsym`, `GetProcAddressA`,
SQLite's `sqlite3OsDlOpen`/`sqlite3OsDlSym` and `xDlOpen`/`xDlSym`, the
`osLoadLibraryA/W` and packaged-loader paths, and the existing APIs from the
first review.  Exact per-path call counts are recorded in `phase0_manifest.json`;
a new path or an additional call in an existing path is rejected.

A second case-insensitive family scan inventories declarations, definitions,
function-pointer tables, capability guards, and calls for any identifier
containing `dlopen`/`dlsym` and any `LoadLibrary`/`GetProcAddress` family wrapper.
It freezes 92 code references, 28 identifiers, and ten paths.  Comments,
character literals, and strings are excluded.  This catches prefixed wrappers
such as `lt_dlsym` or `Jim_dlopen` even though they are absent from this exact
tree.  `GetProcAddressW` and any packaged resolver wrapper are proactively in the
call scanner but absent from the exact reference inventory; `GetProcAddressA`
is present.  The active JimTcl extension-loader path in `jim-load.c`, its
indirect caller in `jim-package.c`, and `jim-win32compat.c` must be patched out
or proved absent from the final object/link inventory.

The planned CMSIS-DAP v2 source files contain no loader calls or forbidden DLL
literals.  The external libusb source is not yet frozen locally, however, so a
WinUSB-only patch and proof excluding UsbDk and MSYS runtime loading remain
mandatory before compilation.

## Current blockers

The read-only package audit found two exact-version mismatches:

- GCC expected `16.2.0-3`, observed `16.1.0-5`;
- pkgconf expected `1~3.0.5-1`, observed `1~2.5.1-2`.

No package was installed or changed.  Compilation remains blocked until the
environment and every other blocker in `phase0_manifest.json` are reviewed and
resolved.  The system-DLL allowlist is also intentionally unfrozen.

`tool_observation.json` is an exact SHA-256-bound input.  Its 11 required package
records are re-derived against `tools/openocd/manifest.json`; the two-package
mismatch set must match exactly.  All nine absolute tool/library identities are
then reopened read-only and checked for exact path, byte size, and SHA-256.

## Read-only audit

From the valve repository root, against a source tree produced by the existing
deterministic prepare workflow:

```powershell
python tools/openocd/r6_live_boundary/audit.py `
  --source build/r6-live-boundary-phase0/openocd-source
python -m pytest tools/openocd/r6_live_boundary/test_phase0.py
```

The audit reads source, Git metadata, manifests, and hashes.  It writes nothing.
It fails closed on source drift, submodule drift, input-hash drift, an ignored
archive or build directory, adapter-plan gaps, required-symbol loss, any loader
call/path/count change, forbidden DLL text, entry ordering drift, package or tool
identity mutation, mismatch removal, or accidental authority expansion.  The
adversarial tests exercise each of the artifact, observation, and loader bypasses.

## Planned progression

1. Independently review Phase 0 and freeze the exact build environment.
2. Freeze libusb source and a minimal WinUSB-only patch; prove JimTcl loader
   removal at source and object level.
3. Implement and unit-test the earliest-main gate without running OpenOCD.
4. Compile only after explicit review, then inventory every object, archive,
   direct import, delay import, adjacent DLL, and required symbol.
5. Obtain two independent live-readiness audits.  A later explicit board-GO is
   still required before any single live session; build success is never GO.

`pe_import_policy.schema.json` defines the normalized final import document.
DLL names are lowercase, unique, sorted, and checked against exact direct and
delay-import policy; unknown imports are rejected.  The bound
`tool_observation.schema.json` separately documents the exact read-only host
observation shape; the audit performs the semantic and on-disk identity checks.
