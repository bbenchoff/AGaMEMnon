# R6 live-boundary Phase1C namespace-custody child

Status: **desk-only child candidate of accepted Phase1C; independent live-readiness audits pending; OpenOCD execution and hardware contact refused**.

This child is based exactly on independently accepted Phase1C commit
`a8f7598c59ec1a9c3e01c81b382e83f0f99b4b8e`, tree
`74ddbd324ce9c1eaf7c1179f1cf4bf8e87fc664c`, whose accepted parent is Phase1B
`70c24a5b575bacd0c11af7c1edb26fc1c602194d`. It leaves the accepted deterministic
static CMSIS-DAPv2/WinUSB-only PE and build artifacts unchanged. The child narrows the
launch grammar to two exact self-contained Tcl leaves and adds Windows volume-GUID
namespace custody for the executable, config, command, working directory, and exact
new log. The OpenOCD PE must not be invoked during construction, including with
`--version`.

The only retained `GetProcAddress` site is the MinGW `getntptimeofday` compatibility
routine. It resolves the fixed `GetSystemTimePreciseAsFileTime` name from the already
loaded `kernel32.dll` and falls back to the directly imported
`GetSystemTimeAsFileTime`. Phase1C binds the complete function disassembly, its sole
caller classification, target string, and the full DLL/import-symbol inventory. It is
not a general or libusb-controlled loader surface.

## Earliest-main protocol

Default launch, malformed private arguments, a missing/broken pipe, wrong nonce report,
partial I/O, EOF, or a token other than the exact four bytes `R6GO` returns exit 70 before
either `setvbuf()` or `openocd_main()`. There is no environment override, desk bypass,
probe mode, or generic continuation switch.

The direct launcher creates two anonymous pipes and supplies exactly three private
arguments containing the child read handle, child write handle, and a 64-character
lowercase hexadecimal nonce. The gate:

1. validates all three arguments and distinct nonzero handles;
2. emits exactly `R6GATE1\n` followed by the 64 nonce bytes;
3. waits for exactly `R6GO`;
4. closes and clears its private state;
5. strips all three private arguments so OpenOCD receives only the authorized request;
6. permits the normal entry path.

The report precedes continuation. Possession of an arbitrary command line without both
inherited pipe handles cannot pass the gate.

## Exact authorization boundary

The launcher has no command-line `-c` surface. It accepts one strict launch-request JSON
whose only admitted OpenOCD grammar is:

```text
-f <exact self-contained config file> -f <exact non-programming halt/read command file>
```

The request binds the package/epoch/session/nonce, exact PE size and SHA-256, complete
config and command identities, canonical volume-GUID log path, and canonical argv digest.
No external scripts directory, `-s`, `-c`, extra argument, default `openocd.cfg`, or Tcl
file-loading command is admitted. Exact prepared-source attestation proves that explicit
`-f` inputs suppress the default config, each `-f` sources only its named leaf, and the
startup Tcl is embedded in the accepted PE. Later Phase1C patches are mechanically proved
disjoint from the four attested configuration-source files.
A separate short-lived GO must bind the exact request bytes, carry `maximum_uses: 1`, and
name two distinct exact desk-only live-readiness ACCEPT reports. Missing, duplicate, or
foreign JSON keys fail closed.

Before any process backend call, the launcher verifies the complete request/GO/audit
closure, acquires the single-consumer lock, reconciles every prior receipt with the
high-water record, creates and flushes a terminal `CONSUMED` receipt exclusively, advances
the high water with write-through replacement, and rereads both. It then repeats the
request, manifest, and controller-source checks at the final pre-create edge. Spawn,
assignment, parent-death, report, continuation, timeout, and child failures all leave the
authorization consumed and nonreplayable.

Before authorization consumption, the launcher acquires noninheritable custody handles
from each canonical local volume-GUID root through every launch leaf and holds them until
the backend returns or faults. Ancestors allow reads and writes but deny delete sharing;
the executable/config/command leaves allow reads only, require one hard-link, reject
reparse points and writable mappings, and are checked by volume/file identity, final path,
size, and SHA-256 through their handles. The exact absent log is bound in the request; the
backend creates it once with `CREATE_NEW`, verifies its final volume path and identity,
and gives the child that same handle. No custody handle other than the exact combined log
is inherited.

The Windows backend calls `CreateProcessW` directly with
`CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW |
EXTENDED_STARTUPINFO_PRESENT`. Its exact inherited-handle list is the gate read/write
ends, `NUL` stdin, and one exclusive combined log. It assigns the returned process to a
kill-on-close Job before resuming the returned initial-thread handle. It does not use
`Popen`, Toolhelp thread reacquisition, a shell, inherited PATH authority, or an arbitrary
environment.

The public Phase1C CLI rereads and validates the manifest, then refuses before opening
the GO, request, state, log, pipes, handles, or process backend while either the
OpenOCD-execution or hardware-contact bit is false. Both are frozen false in this
desk-only candidate. A private test-only seam exercises fault scheduling against fake
backends; it is not the public launch edge.

## What Phase1C does not prove

This candidate is intentionally not live-ready. In particular:

- the complete System32 module/API-set closure and creation/late-image mitigation set are
  not yet attested;
- request, GO, and audit documents are content-checked, and the authorization-state
  directory has receipt/high-water reconciliation, but neither input documents nor
  state have proved private namespace custody against ancestor, file, or directory
  replacement;
- no externally authenticated GO provenance mechanism is claimed beyond the exact
  one-shot document and its frozen desk reports;
- two independent unchanged live-readiness audits have not occurred;
- no fresh board-GO exists;
- OpenOCD execution and hardware contact remain frozen false.

Therefore a green Phase1C build or unit suite grants no OpenOCD execution, USB/device
enumeration, board lock, HIL evidence session, or hardware contact. These blockers must
be closed or explicitly resolved in a separately frozen child before any execution.

## Desk gates

- prepare the exact Phase1B source projection and apply the gate and direct-system-import
  patches with no fuzz;
- perform two fresh builds and require byte-identical PE, archives, objects, imports,
  configure/link records, and disassembly;
- retain exactly one adjacent `openocd.exe`, no delay imports, the prior direct-import
  allowlist, direct WinUSB/CfgMgr32/AdvAPI32/SetupAPI/HID imports, no libusb generic
  loader string or unresolved symbol, exactly one bound fixed MinGW system resolver,
  no Jim loader object/symbol, and exactly `BUILD_CMSIS_DAP_USB`;
- prove the gate call precedes both `setvbuf` calls and `openocd_main` in final
  disassembly;
- adversarially reject malformed/expired/replayed/wrong-package/wrong-config/
  wrong-command authority, duplicate auditors, late mutation, concurrent consumption,
  spawn failure, assignment failure, parent death, and timeout;
- prove exact explicit-config source closure, strict volume-GUID grammar, ancestor and
  leaf custody, writable-handle/mapping refusal, one-link leaves, log `CREATE_NEW`, exact
  request grammar, handle noninheritance, and cleanup on every injected fault;
- rerun every Phase1B, Phase1A, Phase0, and retained OpenOCD-bundle test.

The build script terminates with
`PASS_PHASE1C_BUILD_COMPLETE_OPENOCD_NOT_EXECUTED` and contains no executable invocation.

## Inherited frozen builder result

The accepted Phase1C parent was built twice from exact prepared source without invoking
the PE, and the results were byte-identical. This child freezes and rechecks those same
artifacts without rebuilding or executing them:

- `openocd.exe`: 4,818,443 bytes, SHA-256
  `81b5c1cba4f4f028c4a2ec56a0319d7d78d31ad1abbb5887f8f4ee08f009d674`;
- `libusb-1.0.a`: 238,830 bytes, SHA-256
  `6ac8a798bdadcd1d195d22192b65e9c1e8e975439e31a50d49e08e30cedf8107`;
- `libopenocd.a`: 5,322,644 bytes, SHA-256
  `d1477c52373a26bd349e6f2820192d7585f43198fb70b4e141995a735b6d1603`;
- `libjim.a`: 376,388 bytes, SHA-256
  `086f80252236101c158634d47a42c39493aaf656bd3555269f573c7f6f086e71`;
- 348 object records with digest
  `88056a868b896cfecc7888320650544d349829a2626a891e2cce1316173c6a62`;
- the complete 20-DLL import and imported-symbol inventory, no delay imports,
  exact `main`, gate, and fixed-resolver disassembly, and no libusb generic-loader
  undefined symbols or forbidden loader/backend strings.

Both exact build roots passed
`PASS_PHASE1C_DESK_ONE_SHOT_BOUNDARY_OPENOCD_NOT_EXECUTED`. The accepted parent retained
matrix passed 252 tests with one unchanged skip. This namespace-custody child passed the
expanded complete Phase0/1A/1B/1C, namespace, and OpenOCD-bundle matrix with 271 tests and
the same one skip. These are desk results only. The false manifest authority bits and
every blocker listed above remain controlling.
