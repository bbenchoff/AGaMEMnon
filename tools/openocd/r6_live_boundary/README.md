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
frozen base as its parent, then derives the complete expected generated
provenance from the hash-bound release manifest, actual patched HEAD and
submodules, and exact repository/copied-patch hashes.  Provenance is parsed with
duplicate-key rejection, has exact top-level and nested key sets, must retain the
full comparison-only oracle with `redistribute: false`, and must equal the
canonical indented UTF-8 JSON bytes.  Missing provenance, value drift, reordered
keys, whitespace changes, or authority additions such as `compile_authorized`
all fail closed.  The release CLI enforces the same prepared-source requirement;
only `prepare` invokes the internal pre-provenance identity mode before it
writes and revalidates the canonical file.

Source identity is not inferred from porcelain status.  The Phase-0 audit and
public release verifier independently parse the recursive `HEAD` tree and the
complete staged index and require exactly one stage-0 entry per path with the
same object ID and mode.  Separate `ls-files -v`, `ls-files -f`, and debug-flag
views must contain only ordinary zero-flag entries, rejecting skip-worktree,
assume-unchanged, fsmonitor-valid, intent-to-add, unmerged, and other extended
index states.  After those hiding mechanisms are excluded, each actual tracked
regular file or symlink is reopened and rehashed as its Git blob, file types and
representable executable modes are checked, gitlinks are required to be real
directories with separately frozen submodule identities, and Git's independent
worktree/index diff must also be empty.  Visible and ignored untracked files are
derived separately and their union must be exactly the provenance file and two
copied patches in the root, and empty in both submodules.  This whole-tree proof
runs in addition to the zero-extra-directory gate below.

The three generated inputs are not trusted merely because their paths and
bytes match that exact untracked inventory.  Both independent source verifiers
also require the provenance file and two copied patches to be ordinary files
with exactly one storage link, reached through real, contained, non-reparse
directory ancestry.  Symlinks, junctions, mount aliases, outside hardlinks,
and other redirected storage fail closed.  Source-archive staging freezes every
input through a no-follow file handle, copies only from a handle bound to that
identity and SHA-256, and independently reopens each staged member to require
contained ordinary single-link topology and exact bytes.  Temporary pathname
substitution therefore cannot redirect the copy, and an in-place byte change
during staging fails closed.  The complete staging operation is one transaction:
created files and directories are identity-bound, and rollback never unlinks a
substituted object.  On Windows, a normal failure at any natural-order member
removes all earlier transaction-owned objects through exact-handle disposition.
On other platforms, or after any custody/disposition failure, those objects are
preserved.  The caller must provide an empty private root; preserved output
intentionally leaves that root non-retryable rather than being overwritten.

Corrective v10 keeps directory custody through every staging creation and final
archive read.  POSIX child creation and opening is descriptor-relative; Windows
holds each real parent with a no-delete-sharing directory handle, making parent
redirection impossible before pathname-based child I/O.  Successful staging
returns an immutable identity, size, mode, change-state, ancestry, and SHA-256
binding for every copied member.  Packaging never rewrites the secured generated
provenance.  The tar writer opens each bound member no-follow under that directory
custody, hashes the exact handle bytes consumed by `TarFile.addfile()`, and then
rechecks handle, pathname, parent, size, link-count, and change state.  Append,
truncation, same-size rewrite, leaf replacement, and parent redirection therefore
fail through final source-archive consumption rather than only at staging time.
The staged tree must have exactly the copied input file/directory inventory, and
the final archive permits only those bound inputs plus the seven exact package
manifest, documentation, tool, and patch members; an injected extra object is
preserved for diagnosis but cannot enter the archive.

Corrective v11 narrows the rollback claim to what the live Windows platform can
prove.  Windows opens each transaction-created directory with DELETE access and
without delete sharing, retains that exact custody through rollback, and marks
the held object delete-pending with `SetFileInformationByHandle`.  A staged file
is reopened no-follow with DELETE access and no delete sharing, its expected
identity is checked on both sides of acquisition, and disposition is applied to
that exact handle.  A rename or replacement attempted at the final disposition
call is therefore blocked; if exact custody, identity, or disposition cannot be
proved, the object is preserved.  POSIX descriptors do not pin directory
entries against rename or unlink, so v11 deliberately performs no destructive
rollback there and preserves the partial private root rather than advertising a
portable pathname-race guarantee.  Normal Windows failures clean exactly and a
fresh unique root is retryable; preservation always takes precedence over
empty-root convenience.

Packaging no longer delegates its outer workspace to `TemporaryDirectory` or
generic recursive deletion.  Each invocation receives a fresh private
`mkdtemp` root, validates that root's identity again on exit, and deliberately
preserves it on success or failure until every package member has an equivalent
exact-object deletion binding.  This desk-only cleanup hardening grants no
compilation, OpenOCD, USB, HIL, board-lock, or later-phase authority.

The primary directory security boundary derives the only allowed filesystem
directories from the parent directories of every `git ls-files` entry in the
root, JimTcl, and libjaylink repositories, including the two root gitlinks.  It
adds only the exact parent of the two expected generated patch copies, excludes
only repository `.git` internals, and hands each submodule subtree to its own
identical audit.  Any other directory is rejected whether ignored or not, empty
or populated, and regardless of its name or creation mechanism.  A fresh Git
checkout has no legitimate empty tracked directories.

The secondary artifact review binds thirty-five exact, SHA-256-bound
`.gitignore`, documentation, workflow, configure, Make, Tcl, shell, and helper
sources.  Its named policy explicitly catches
nine possible products, including `src/openocd`, `jimtcl/jimsh`,
`jimtcl/jimsh0`, and `jimtcl/build-jim-ext`, plus nine generated-directory
classes.  Independently, exact Git ignored-file enumeration must be empty in the
root and both submodules except for the two preparation-created
`AGAMEMNON-PATCHES` copies, whose paths and hashes are frozen.  Ignored generated
directories must always be empty.  There is no build-product exemption.

The active-build-rule inventory is explicitly secondary review evidence and
does not claim completeness or act as the security boundary.  It scans Make, configure, and
Doxygen inputs for literal directory creation.  It derives `.dep` from exactly
eight `testing/examples` makefiles and also re-derives `build-aux`, `doxy`, and
`doxygen`; every discovered source must be hash-bound and represented in the
directory evidence.  Commented rules do not count.  This catches a non-ignored,
empty `.dep` directory that Git ignored-file enumeration cannot report, and a
self-consistent omission from the hand-maintained inventory is rejected.

The same secondary pass separately freezes 41 active directory-creation
occurrences, including unresolved or variable-mediated expressions: dynamic
`dirname` destinations, Automake `%D%`, Angie HDL build variables, Espressif
`$@` targets, release and cross-build shell scripts, JimTcl install-directory
aliases, autosetup and test Tcl `file mkdir`, and the eight literal `.dep`
rules.  Every occurrence has an exact source, line,
expression, kind, reviewed disposition, and any resolved forbidden ancestor or
basename.  Additions, removals, alias uses, and expression changes fail closed.
Ten additional hash-bound records cover mechanisms outside that scanner's
claimed surface: HACKING's `build-*` and Git-clone recipes, snapshot-workflow
download/build directories, autosetup output, cpio distribution copying,
release-test Git cloning, archive staging, `.test` input patterns, and Tcl test
helper directories.  All created directories are still governed by the primary
zero-extra-directory invariant.

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
literals. Phase1A now freezes the official libusb 1.0.30 archive and a
WinUSB-only source patch. Deterministic source-build integration and final
object/import proof excluding UsbDk, libusbK, and MSYS runtime loading remain
mandatory before compilation.

## Current blockers

Phase1A resolves the two Phase-0 version mismatches by accepting and hash-binding
the exact observed offline MSYS2 snapshot: GCC `16.1.0-5` and pkgconf
`1~2.5.1-2`. No package was installed or changed. Rolling CI resolution remains
refused, and compilation is still blocked on deterministic patched-source and
libusb-source integration plus every final object/link/import gate. The
system-DLL allowlist is also intentionally unfrozen. See `PHASE1A.md`.

`tool_observation.json` is an exact SHA-256-bound input. Its 11 required package
records are re-derived against `tools/openocd/manifest.json`; the Phase1A
mismatch set must remain empty. All ten absolute tool/library identities are
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
identity mutation, mismatch-set change, or accidental authority expansion.  The
adversarial tests exercise each of the artifact, observation, loader, tracked
source, generated-input topology, and archive-staging bypasses.
They also schedule staging failures at all three generated-input order positions,
prove clean retry after ordinary rollback, preserve substituted leaves and
parents, exercise parent swaps at creation and tar consumption, and inject
append, truncation, same-size rewrite, and leaf replacement after the tar reader
has consumed each generated member.

## Planned progression

Phase1C is independently accepted at
`a8f7598c59ec1a9c3e01c81b382e83f0f99b4b8e`. It retains the deterministic static
WinUSB-only build, adds the earliest-main inherited-handle handshake, converts reachable
libusb system-DLL resolution to direct imports, and provides the exact one-shot
request/GO/receipt boundary and direct suspended Job launcher described in `PHASE1C.md`.
The current desk-only child retains that exact PE while eliminating the external scripts
tree, proving explicit-config source closure, and holding the executable/config/command/
working-directory/log namespace by canonical volume-GUID handles through backend return.
Its public CLI still refuses before any authorization or process side effect while
execution or hardware authority is false. Authorization-input/state namespace custody,
module/API-set/mitigation attestation, external GO provenance, two independent
live-readiness audits, a fresh board-GO, and both false authority bits remain hard
blockers.

1. Retain the independently accepted Phase 0 and the exact Phase1A offline
   build-environment decision.
2. Integrate the frozen Phase1A libusb/JimTcl patches into deterministic source
   preparation, then prove loader removal at final object level.
3. Preserve the Phase1A deny-only earliest-main gate through final disassembly;
   a real authorization gate is a later separately frozen child.
4. Compile only after explicit review, then inventory every object, archive,
   direct import, delay import, adjacent DLL, and required symbol.
5. Obtain two independent live-readiness audits.  A later explicit board-GO is
   still required before any single live session; build success is never GO.

`pe_import_policy.schema.json` defines the normalized final import document.
DLL names are lowercase, unique, sorted, and checked against exact direct and
delay-import policy; unknown imports are rejected.  The bound
`tool_observation.schema.json` separately documents the exact read-only host
observation shape; the audit performs the semantic and on-disk identity checks.
