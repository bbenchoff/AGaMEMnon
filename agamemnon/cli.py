#!/usr/bin/env python3
"""AGaMEMnon: open synthesis, place-and-route, bitstream, and programming for AG32 / AGRV2K.

The release fabric path uses Yosys, nextpnr with the `agrv2k` backend, and strict AGaMEMnon bitgen.
Bitstream conversion, named `.agasc` editing, and main-flash controller operations are also open.
Hardware access requires a CMSIS-DAP probe and an OpenOCD binary with AGM's `riscv -dap` target
extension; see docs/PROGRAMMING.md.

  SDK workflow:
    agamemnon doctor
    agamemnon new hello --board ag32vf303-l48 --template mcu-fpga
    agamemnon build                         # inside the generated project
    agamemnon run --transport dap           # volatile SRAM run

  FPGA fabric:
    agamemnon build foo.v -o foo.bin         # Verilog -> synth -> place&route -> .bin (open flow)
    agamemnon build foo.v -o foo.bin --uarch --verify   # agrv2k uarch flow + offline behavioural check
    agamemnon verify foo_routed.json         # cycle-sim a routed design: the AHB read-values it produces
    agamemnon pack foo_routed.json foo.bin   # routed nextpnr JSON -> .bin  (icepack)
    agamemnon unpack foo.bin -o raw.img      # .bin -> 99936-byte raw image (iceunpack)
    agamemnon decode fabric.bin -o raw.img   # .bin -> 99936-byte raw config image
    agamemnon encode raw.img   -o fabric.bin # raw image -> compressed .bin
    agamemnon to-agasc fabric.bin -o fabric.agasc    # .bin -> named per-tile ASCII
    agamemnon from-agasc fabric.agasc -o fabric.bin  # edited ASCII -> CRC-correct .bin
    agamemnon edit-lut in.bin --le 17,4,1 --init 0x96e9 -o out.bin
  chip (SWD via a CMSIS-DAP probe + an OpenOCD built with `riscv -dap`):
    agamemnon probe                          # read DEVICE_ID over SWD (expect 0x40200001)
    agamemnon sram fw.bin -b fabric.bin      # SRAM-inject a bitstream + firmware and run it (volatile)
    agamemnon backup full.bin                # dump the whole 256 KB flash
    agamemnon flash foo.bin --addr 0x80008100 --backup full.bin   # open flasher: erase+program+verify
    agamemnon image -b fabric.bin -m fw.bin --flash --backup f.bin  # assemble+flash a boot image
  chip (UART0 mask ROM via the Raspberry Pi Pico 2 bridge):
    agamemnon uart-probe --port COM6
    agamemnon uart-backup full.bin --port COM6
    agamemnon uart-flash fw.bin --addr 0x80000000 --backup full.bin --port COM6
  chip (flash-resident USB CDC uploader):
    agamemnon probe --transport usb
    agamemnon backup full.bin --transport usb
    agamemnon flash app.bin --addr 0x80010000 --backup full.bin --transport usb
    agamemnon go 0x80010000 --transport usb
"""
import os, sys, argparse, subprocess, tempfile, json, hashlib, shutil, time, re

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine")        # the self-contained engine (single source of truth)
CHIPDB = os.path.join(HERE, "chipdb")        # the shipped device database
SYNTH = os.path.join(HERE, "synth")          # yosys synth scripts (prims/cells_map + tcl)
sys.path.insert(0, ENGINE)                    # engine modules import each other by bare name
import lzw_codec as L                          # noqa: E402
import physmap                                 # noqa: E402
import pll_emit as PLL                         # noqa: E402
from . import __version__                      # noqa: E402
from . import program as P                     # noqa: E402  (the SWD programmer / open flasher)
from . import uart_program as U                # noqa: E402  (Pico + mask-ROM UART programmer)
from . import usb_program as USB               # noqa: E402  (flash-resident USB CDC uploader)
from . import diagnostics as D                 # noqa: E402
from . import project as PJ                    # noqa: E402
from . import tool_install as TI               # noqa: E402
from . import qualification_report as Q         # noqa: E402
from .engine.registry import OPTIONS as ENGINE_OPTIONS  # noqa: E402

RAW_LEN = 99936
HDR = bytes.fromhex("40200001") + bytes.fromhex("0000ffff")   # DEVICE_ID | max_index
DEFAULT_FABRIC_FREQUENCY_MHZ = int(ENGINE_OPTIONS["AGAMEMNON_SYSCLK"].default)


def _synchronize_build_frequency(env, freq):
    """Use one qualified frequency for timing analysis and emitted hardware.

    ``nextpnr --freq`` without a matching ``AGAMEMNON_SYSCLK`` can produce an
    image that closes timing at one frequency but configures the PLL for
    another.  Resolve CLI/manifest input first, then the environment override,
    then the qualified registry default, and pass that value to both tools.
    """
    requested = env.get("AGAMEMNON_SYSCLK", DEFAULT_FABRIC_FREQUENCY_MHZ) if freq is None else freq
    try:
        numeric = float(requested)
    except (TypeError, ValueError) as exc:
        name = "AGAMEMNON_SYSCLK" if freq is None else "--freq"
        raise ValueError("%s must be an integer MHz value" % name) from exc
    if numeric <= 0:
        name = "AGAMEMNON_SYSCLK" if freq is None else "--freq"
        raise ValueError("%s must be greater than zero" % name)
    if not numeric.is_integer():
        name = "AGAMEMNON_SYSCLK" if freq is None else "--freq"
        raise ValueError(
            "%s must be an integer MHz value supported by the emitted PLL" % name
        )
    sysclk = int(numeric)
    try:
        hse = int(env.get("AGAMEMNON_HSE", "8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("AGAMEMNON_HSE must be an integer MHz value") from exc
    try:
        PLL.require_supported_ratio(sysclk, hse)
    except PLL.UnsupportedPLLConfiguration as exc:
        raise ValueError(str(exc)) from exc
    env["AGAMEMNON_SYSCLK"] = str(sysclk)
    return sysclk


def _run_child(command, **kwargs):
    """Run one tool and tie its lifetime to this CLI process on Windows.

    Windows does not normally terminate a child when its console parent is
    killed.  A cancelled build could therefore leave nextpnr consuming CPU and
    competing with the next invocation.  A kill-on-close Job Object gives the
    process tree Unix-like parent lifetime semantics; if jobs are unavailable,
    retain normal subprocess behaviour rather than making tools unstartable.
    """
    if os.name != "nt":
        return subprocess.run(command, **kwargs)

    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if job:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            job = None

    popen_kwargs = dict(kwargs)
    capture = popen_kwargs.pop("capture_output", False)
    if capture:
        if popen_kwargs.get("stdout") is not None or popen_kwargs.get("stderr") is not None:
            raise ValueError("stdout/stderr may not be used with capture_output")
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(command, **popen_kwargs)
    if job and not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
        kernel32.CloseHandle(job)
        job = None
    try:
        stdout, stderr = proc.communicate()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        if job:
            kernel32.CloseHandle(job)
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _read_pcf(path):
    """Read the useful subset of IceStorm-style PCF: `set_io <port> PIN_<n>`."""
    pins = {}
    for lineno, raw in enumerate(open(path), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        tok = line.split()
        if len(tok) != 3 or tok[0] != "set_io":
            raise ValueError("%s:%d: expected `set_io <port> PIN_<n>`" % (path, lineno))
        port, pin = tok[1], tok[2].upper()
        if pin.isdigit():
            pin = "PIN_" + pin
        if not pin.startswith("PIN_"):
            raise ValueError("%s:%d: invalid package pin %r" % (path, lineno, tok[2]))
        if port in pins:
            raise ValueError("%s:%d: port %s is assigned twice" % (path, lineno, port))
        pins[port] = pin
    return pins


def _devdb_fingerprint(arch, emitter, data, emit_env):
    """Content fingerprint for generated uarch databases.

    Device databases are ignored build artifacts.  Reusing one after arch.py or
    a chipdb evidence file changes silently resurrects old routing mistakes, so
    the default cache is valid only for an exact generator/data/environment
    fingerprint.
    """
    digest = hashlib.sha256()
    inputs = [arch, emitter]
    for root, dirs, files in os.walk(data):
        dirs.sort()
        for name in sorted(files):
            inputs.append(os.path.join(root, name))
    for path in inputs:
        rel = os.path.relpath(path, os.path.dirname(arch)).replace("\\", "/")
        digest.update(rel.encode("utf-8") + b"\0")
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    digest.update(json.dumps(sorted(emit_env), separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def _json_has_live_bram_portb(path):
    """Return true when a synthesized BRAM DataOutB bit has a real consumer."""
    design = json.load(open(path, encoding="utf-8"))
    for module in design.get("modules", {}).values():
        refs = {}
        for cell in module.get("cells", {}).values():
            for bits in cell.get("connections", {}).values():
                for bit in bits:
                    if isinstance(bit, int):
                        refs[bit] = refs.get(bit, 0) + 1
        for cell in module.get("cells", {}).values():
            if str(cell.get("type", "")).upper() != "ALTA_BRAM9K":
                continue
            if any(refs.get(bit, 0) > 1 for bit in cell.get("connections", {}).get("DataOutB", [])
                   if isinstance(bit, int)):
                return True
    return False


def _wsl_path(path):
    """Translate an absolute Windows path for a nextpnr process launched by WSL.

    WSL is only launched from Windows, where ``os.path`` is ``ntpath``.  Using
    ``ntpath`` explicitly keeps the drive-letter split correct (``C:\\...`` ->
    ``/mnt/c/...``) even when this runs from a POSIX host -- on POSIX,
    ``os.path.splitdrive`` never sees a drive letter and ``os.path.abspath``
    would prepend the POSIX cwd, so the plain-``os.path`` version silently
    failed to translate anything off Windows.
    """
    import ntpath
    if not ntpath.isabs(path):
        path = ntpath.abspath(path)
    drive, tail = ntpath.splitdrive(path)
    if drive and len(drive) >= 2 and drive[1] == ":":
        return "/mnt/%s%s" % (drive[0].lower(), tail.replace("\\", "/"))
    return path.replace("\\", "/")


def _translate_wsl_nextpnr_args(command):
    """Translate only nextpnr's path-bearing arguments, preserving all options."""
    result = list(command)
    for pos, value in enumerate(result):
        if value in ("--json", "--write") and pos + 1 < len(result):
            result[pos + 1] = _wsl_path(result[pos + 1])
        elif value == "-o" and pos + 1 < len(result) and result[pos + 1].startswith("chipdb="):
            result[pos + 1] = "chipdb=" + _wsl_path(result[pos + 1][len("chipdb="):])
    return result


def _forward_wsl_uarch_environment(env):
    """Tell WSL to import the AGRV2K controls set for the Windows process."""
    wanted = sorted(key for key in env if key.startswith("AGRV2K_"))
    existing = [item for item in env.get("WSLENV", "").split(":") if item]
    env["WSLENV"] = ":".join(dict.fromkeys(existing + wanted))


def _route_and_timing_succeeded(log, returncode, require_fmax=False):
    """Require both a routed design and a clean nextpnr timing exit.

    nextpnr prints ``Routing complete`` before checking the requested Fmax.  A
    timing failure must therefore not be mistaken for a successful routing
    attempt merely because that earlier marker is present in the captured log.
    """
    return (returncode == 0 and "Routing complete" in log
            and (not require_fmax or "No Fmax available" not in log))


def _nonretryable_uarch_failure(log):
    """Recognize pack errors that placement seeds and fanout cannot change."""
    return any(marker in log for marker in (
        "dedicated carry requires",
        "malformed or branched carry graph",
        "dedicated carry contains no chain head",
    ))


def _without_path_entries(path, entries):
    """Remove exact path entries without disturbing the user's remaining PATH."""
    unwanted = {os.path.normcase(os.path.normpath(item)) for item in entries if item}
    return os.pathsep.join(
        item for item in (path or "").split(os.pathsep)
        if item and os.path.normcase(os.path.normpath(item)) not in unwanted
    )


def _build_tool_env(base, oss=None, use_oss=False, runtime=None):
    """Construct a child environment for one external tool family.

    oss-cad-suite ships a self-consistent MinGW runtime for its own programs,
    but those DLLs are not ABI-compatible with an independently built native
    nextpnr.  Never expose the OSS ``bin``/``lib`` directories to a custom
    uarch process; optionally prepend its matching runtime instead.
    """
    child = dict(base)
    oss_entries = [os.path.join(oss, "bin"), os.path.join(oss, "lib")] if oss else []
    path = _without_path_entries(child.get("PATH", ""), oss_entries)
    prepend = oss_entries if use_oss else ([runtime] if runtime else [])
    child["PATH"] = os.pathsep.join([*prepend, path]) if prepend else path
    return child


def _loader_failure_hint(returncode):
    """Translate common Windows/launcher failures into actionable diagnostics."""
    status = returncode & 0xffffffff
    windows = {
        0xC0000135: "a required DLL was not found",
        0xC0000139: "a loaded DLL is ABI-incompatible (entry point not found)",
        0xC000007B: "a DLL has the wrong architecture or image format",
    }
    if status in windows:
        return "%s (Windows status 0x%08X)" % (windows[status], status)
    if returncode == 127:
        return "the launcher or nextpnr executable was not found (exit 127)"
    return "startup exited with status %d" % returncode


def _preflight_nextpnr(command, env):
    """Prove nextpnr can enter ``main`` before classifying any route result."""
    if not command:
        raise RuntimeError("nextpnr command is empty")
    exe = shutil.which(command[0], path=env.get("PATH")) or command[0]
    probe = [exe, *command[1:], "--version"]
    try:
        result = _run_child(probe, env=env, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError("cannot start nextpnr: %s" % exc) from exc
    log = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        detail = _loader_failure_hint(result.returncode)
        tail = log.strip()[-1000:]
        runtime = os.environ.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
        advice = (" Set AGAMEMNON_UARCH_NEXTPNR_RUNTIME to the directory containing the "
                  "matching compiler/runtime DLLs.") if os.name == "nt" and not runtime else ""
        if tail:
            detail += ": " + tail
        raise RuntimeError("nextpnr startup preflight failed: %s.%s" % (detail, advice))
    return log


def _suppress_windows_crash_dialogs():
    """Make child assertion failures return to the CLI instead of opening WER UI."""
    if os.name != "nt":
        return
    import ctypes
    # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def _nextpnr_aborted(log, returncode):
    text = (log or "").lower()
    return ("terminate called after throwing" in text or "assertion failure:" in text
            or (returncode & 0xffffffff) in {0xC0000409, 0x40000015})


def _validate_uarch_devdb(path):
    """Fail before nextpnr when a custom/generated database lacks required resources."""
    required = ["dev_meta.csv", "dev_wires.csv", "dev_bels.csv", "dev_belpins.csv", "dev_pips.csv"]
    missing = [name for name in required if not os.path.isfile(os.path.join(path, name))]
    if missing:
        raise RuntimeError("uarch device database is incomplete: missing %s" % ", ".join(missing))
    bels = open(os.path.join(path, "dev_bels.csv"), encoding="utf-8").read().splitlines()
    if not any(line.startswith("CLKIN,") for line in bels[1:]):
        raise RuntimeError("uarch device database has no CLKIN bel (emit with AGAMEMNON_LEDPADS=1)")


def _uarch_attempts(requested_cap, maxfo, split_first=False):
    """Return the deterministic placement/fanout escalation order.

    The requested density must remain a real candidate after fanout splitting;
    large designs such as SERV cannot route unsplit, and historically jumped
    straight to cap 8 despite an explicit ``--cap`` value.
    """
    caps = sorted({2, 4, 8, requested_cap})
    attempts = [(cap, 0) for cap in caps]
    fos = list(dict.fromkeys(fo for fo in (16, 8, 4, maxfo) if fo > 0))
    split_caps = sorted({requested_cap, caps[-1]})
    attempts.extend((cap, fo) for fo in fos for cap in split_caps)
    if split_first:
        # Every qualified true-dual-port SERV route needs the cap-5/maxfo-16
        # netlist. Try the caller's requested cap at maxfo 16 first, while
        # retaining the complete unsplit/split fallback matrix afterward.
        preferred = (requested_cap, 16)
        attempts = [preferred] + [attempt for attempt in attempts if attempt != preferred]
    return attempts


def _decode_to_raw(bin_bytes):
    """Return the fixed 99936-byte raw image from either form `pack` produces: an already-
    uncompressed image (99944 B = 8-byte header + 99936 raw) is returned as-is; a compressed .bin
    (header + LZW) is LZW-decoded, stopping at the target so trailing flash padding is ignored."""
    if len(bin_bytes) - 8 == RAW_LEN:
        return bytes(bin_bytes[8:])
    payload = bin_bytes[8:]
    gen = L.bits_msb(payload)

    def rd(n):
        v = 0
        for _ in range(n):
            try:
                v = (v << 1) | next(gen)
            except StopIteration:
                return None
        return v
    dic = {i: bytes([i]) for i in range(L.CLEAR)}
    w, nxt, out, prev = 9, L.FIRST, bytearray(), None
    while len(out) < RAW_LEN:
        c = rd(w)
        if c is None or c == L.EOI:
            break
        if c == L.CLEAR:
            dic = {i: bytes([i]) for i in range(L.CLEAR)}; w, nxt, prev = 9, L.FIRST, None; continue
        e = dic[c] if c in dic else prev + prev[:1]
        out += e
        if prev is not None:
            dic[nxt] = prev + e[:1]; nxt += 1
            if nxt == (1 << w) and w < L.MAXW:
                w += 1
        prev = e
    return bytes(out)


def patch_lut(raw, x, y, z, new_mask):
    """Open LUT editor: set the LE at (x,y,z) to truth table `new_mask` (16 bits). SRAM stores
    the complement (validated byte-exact vs af.exe in lut_edit.py)."""
    raw = bytearray(raw)
    for b in range(16):
        byte, mask = physmap.init_bit_pos(x, y, z, b)
        if not ((new_mask >> b) & 1):
            raw[byte] |= mask
        else:
            raw[byte] &= ~mask & 0xFF
    return bytes(raw)


def cmd_decode(a):
    raw = _decode_to_raw(open(a.input, "rb").read())
    open(a.output, "wb").write(raw)
    print(f"decoded {a.input} -> {a.output} ({len(raw)} bytes raw)")


def cmd_encode(a):
    raw = open(a.input, "rb").read()
    out = HDR + L.encode(raw)
    open(a.output, "wb").write(out)
    print(f"encoded {a.input} -> {a.output} ({len(out)} byte .bin)")


def cmd_to_agasc(a):
    """Convert either compressed or raw-form .bin into lossless per-tile ASCII."""
    import agasc
    data = open(a.input, "rb").read()
    if len(data) < 8:
        raise agasc.AgascError("fabric image is shorter than its 8-byte header")
    raw = _decode_to_raw(data)
    text = agasc.dumps(raw, CHIPDB, header=data[:8])
    with open(a.output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    ntiles = sum(1 for line in text.splitlines() if line.startswith(".tile "))
    nfeatures = sum(1 for line in text.splitlines() if line.startswith("+"))
    print(f"to-agasc {a.input} -> {a.output}: {ntiles} tile(s), {nfeatures} asserted named feature(s)")


def cmd_from_agasc(a):
    """Assemble .agasc, regenerate its CRC, and LZW-compress a flashable .bin."""
    import agasc
    with open(a.input, encoding="utf-8") as handle:
        header, raw = agasc.loads(handle.read(), CHIPDB)
    out = header + (raw if a.uncompressed else L.encode(raw))
    with open(a.output, "wb") as handle:
        handle.write(out)
    form = "uncompressed" if a.uncompressed else "LZW-compressed"
    print(f"from-agasc {a.input} -> {a.output} ({len(out)} byte {form} .bin)")


def cmd_edit_lut(a):
    data = open(a.input, "rb").read()
    raw = _decode_to_raw(data)
    x, y, z = (int(v) for v in a.le.split(","))
    raw2 = patch_lut(raw, x, y, z, int(a.init, 0))
    out = HDR + L.encode(raw2)
    open(a.output, "wb").write(out)
    nchg = sum(1 for i in range(len(raw)) if raw[i] != raw2[i])
    print(f"edit-lut LE({x},{y},{z}) INIT={a.init}: {nchg} raw byte(s) changed -> {a.output}")


def cmd_pack(a):
    """icepack-equivalent: routed nextpnr JSON -> flashable .bin, via the self-contained package
    engine (no vendor binary). Writes <out> (99944-byte uncompressed, for SRAM inject) + <out>.comp
    (LZW-compressed, for flash)."""
    to_bin = os.path.join(ENGINE, "to_bin.py")
    env = dict(os.environ)
    if a.baseline:
        env["AGAMEMNON_BASELINE"] = a.baseline
    r = _run_child([sys.executable, to_bin, a.input, a.output], env=env,
                   capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        print("error: pack failed"); sys.exit(r.returncode)


def cmd_unpack(a):
    """iceunpack-equivalent: .bin -> the 99936-byte raw fabric config image."""
    cmd_decode(a)


def cmd_verify(a):
    """Offline, hardware-free behavioural check of a routed design: cycle-sim the routed netlist and report
    the AHB read-values it will produce. With --observed, compare a silicon-observed value set (SOUND/COVER
    + MCU_DOUT bind). See engine/verify_netlist.py."""
    import verify_netlist as V
    if a.observed is not None:
        obs = [int(x, 0) for x in a.observed.split(",") if x.strip() != ""]
        ok = V.verify(a.input, obs, a.cycles)
        sys.exit(0 if ok else 1)
    ok = V.summary(a.input, a.cycles)
    sys.exit(0 if ok else 1)


def cmd_build(a):
    """Single-command open build: Verilog -> yosys synth -> nextpnr place&route -> our bitgen -> .bin,
    entirely from the self-contained package (engine/ + chipdb/ + synth/). No vendor binary. yosys and
    nextpnr-generic come from $AGAMEMNON_OSS/bin (or PATH). $AGAMEMNON_DATA overrides the shipped chip
    DB and $AGAMEMNON_ENGINE overrides the engine dir, but both default to the packaged copies."""
    _suppress_windows_crash_dialogs()
    freq = getattr(a, "freq", None)
    if freq is not None and freq <= 0:
        print("error: --freq must be greater than zero")
        sys.exit(2)
    project = None
    if not getattr(a, "input", None):
        try:
            project = PJ.Project.load(getattr(a, "project", None))
        except (OSError, ValueError) as exc:
            print("error: %s" % exc)
            sys.exit(2)
        if project.external:
            PJ.build_external(project)
            return
        if not PJ.apply_fabric_config(a, project):
            mcu_output = PJ.build_mcu(project)
            PJ.write_flash_plan(project, mcu_output=mcu_output)
            return
        freq = getattr(a, "freq", None)
        if freq is not None and freq <= 0:
            print("error: --freq must be greater than zero")
            sys.exit(2)
    sources = [a.input] + list(getattr(a, "sources", None) or [])
    top = getattr(a, "top", None)
    if top and not re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", top):
        print("error: --top must be a Verilog module identifier")
        sys.exit(2)
    engine = os.environ.get("AGAMEMNON_ENGINE", ENGINE)
    data = os.environ.get("AGAMEMNON_DATA", CHIPDB)
    if getattr(a, "hard_carry", False) and not a.uarch:
        print("error: --hard-carry requires --uarch")
        sys.exit(2)
    if a.qualified_checkpoint and not a.uarch:
        print("error: --qualified-checkpoint requires --uarch")
        sys.exit(2)
    base = os.path.splitext(os.path.basename(a.input))[0]
    out = a.output or (base + ".bin")
    tmp = tempfile.mkdtemp(prefix="agamemnon_build_")
    synth_json = os.path.join(tmp, base + ".json")
    routed_json = os.path.join(tmp, base + "_routed.json")

    env = dict(os.environ)
    env["AGAMEMNON_DATA"] = data
    require_timing_path = freq is not None or "AGAMEMNON_SYSCLK" in env
    try:
        freq = _synchronize_build_frequency(env, freq)
    except ValueError as exc:
        print("error: %s" % exc)
        sys.exit(2)
    print("[build] clock: timing target and emitted PLL = %d MHz" % freq)
    oss = os.environ.get("AGAMEMNON_OSS")
    env["PYTHONPATH"] = os.pathsep.join([engine, env.get("PYTHONPATH", "")])
    for flag, var in [(a.leds, "AGAMEMNON_LEDPADS"), (a.mcu, "AGAMEMNON_MCU_ENTRY"),
                      (a.true_topo, "AGAMEMNON_TRUE_TOPO"), (a.no_intra_rmux, "AGAMEMNON_NO_INTRA_RMUX")]:
        if flag: env[var] = "1"
    # Dedicated CIN/COUT is silicon-qualified through eight stages, but remains
    # explicit while the constructive packer is limited to nine same-tile slots
    # total (arithmetic stages plus one seed per chain). Ordinary builds retain
    # the more general LUT/routed arithmetic.
    if getattr(a, "hard_carry", False):
        env["AGAMEMNON_HW_CARRY"] = "1"
    else:
        env.pop("AGAMEMNON_HW_CARRY", None)
    if a.pin: env["AGAMEMNON_PIN"] = a.pin
    if a.baseline: env["AGAMEMNON_BASELINE"] = a.baseline
    if a.pcf:
        try:
            _pcf = _read_pcf(a.pcf)
        except ValueError as e:
            print("error: %s" % e); sys.exit(2)
        env["AGAMEMNON_PCF_JSON"] = json.dumps(_pcf, sort_keys=True)
        env["AGAMEMNON_PHYSICAL_IO"] = "1"
        env["AGAMEMNON_LEDPADS"] = "1"       # exposes the physical OPAD bels for constrained outputs
        env["AGAMEMNON_PADFEED_TOP"] = "1"    # real top-row feeder + terminal pips
        env["AGAMEMNON_HARDEN_PADFEED"] = "1"
        # Keep the strict graph's feedback bridges.  Qin packing makes registered
        # self-feedback use the intended INTERNAL path, while large sequential
        # designs still need the remaining proven bridge resources; removing the
        # entire family makes a routed SERV image fail its reset/run behaviour.
        if not a.uarch:
            # The legacy Python architecture's physical-PCF placer relies on
            # this narrower graph; the C++ large-design uarch does not.
            env["AGAMEMNON_NO_FFBRIDGE"] = "1"

    def run(step, cmd, check=True, child_env=None):
        child_env = child_env or env
        exe = shutil.which(cmd[0], path=child_env.get("PATH")) or cmd[0]   # Windows: find via child PATH
        cmd = [exe] + cmd[1:]
        print("[build] %s: %s" % (step, " ".join(os.path.basename(c) if os.sep in c else c for c in cmd)))
        try:
            r = _run_child(cmd, env=child_env, capture_output=True, text=True)
        except OSError as exc:
            # Fail closed with an actionable message instead of a raw
            # FileNotFoundError traceback (the nextpnr path has its own preflight;
            # this covers yosys and any other external build tool that is absent).
            print("error: %s: cannot start '%s' (%s). Install it -- yosys and "
                  "nextpnr-generic ship with oss-cad-suite -- or point AGAMEMNON_OSS "
                  "at your oss-cad-suite/bin directory." % (step, cmd[0], exc))
            sys.exit(1)
        run.returncode = r.returncode
        if r.returncode != 0 and check:
            print(r.stdout[-1500:]); print(r.stderr[-1500:]); print("error: %s failed" % step); sys.exit(1)
        return r.stdout + r.stderr

    # always wrap top-level ports as GENERIC_IOB (iopadmap) so nextpnr can bind them to IO bels
    synth_tcl = os.path.join(SYNTH, "synth_pads.tcl")
    oss_env = _build_tool_env(env, oss=oss, use_oss=bool(oss))
    synth_command = "tcl %s 4 %s%s" % (synth_tcl, synth_json, " " + top if top else "")
    run("synth", ["yosys", "-q", "-p", synth_command, *sources],
        child_env=oss_env)
    # Physical BEL names are exposed by the C++ uarch database.  Generic
    # nextpnr consumes the PCF through arch.py and does not have those BELs.
    if a.pcf and a.uarch:
        run("pcf-bind", [sys.executable, os.path.join(engine, "pcf_bind_json.py"), synth_json,
                         json.dumps(_pcf, sort_keys=True), data])
    # Qin self-feedback fix: permute each registered FF's self-feedback LUT input to pinC (I[2]) so it
    # uses the slice's INTERNAL feedback path (never routed) + cell-to-cell reads to input D. WITHOUT this
    # every counter/FSM freezes (self-feedback can't route). Idempotent; safe for combinational designs.
    run("qin", [sys.executable, os.path.join(engine, "qin_pack.py"), synth_json])
    if getattr(a, "uarch", False):
        live_portb = _json_has_live_bram_portb(synth_json)
        # ---- agrv2k uarch flow (silicon-proven for multi-bit sequential; see examples/uarch_sequential.md).
        # The device is CONDUCTION-GATED (router can't pick electrically-dead pips) and placement is
        # conduction-aware (pack_condplace). Needs the uarch-built nextpnr-generic: $AGAMEMNON_UARCH_NEXTPNR
        # (a path/command), else `nextpnr-generic` on PATH must itself be the uarch build (built via
        # engine/uarch/agrv2k/build.sh). The gated devdb is auto-emitted+cached on first use.
        udir = os.path.join(engine, "uarch", "agrv2k")
        unpr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR", "nextpnr-generic")
        unpr_parts = unpr.split()
        npr_runtime = os.environ.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
        npr_env = _build_tool_env(env, oss=oss, runtime=npr_runtime)
        try:
            version = _preflight_nextpnr(unpr_parts, npr_env)
        except RuntimeError as exc:
            print("error: %s" % exc)
            sys.exit(1)
        for line in version.splitlines():
            if "nextpnr" in line.lower():
                print("[build] nextpnr preflight: %s" % line.strip())
                break
        # Strict DBs contain only per-position silicon/vendor-proven edges.  Keep a distinct cache
        # name so an older permissive "conduction" database can never be reused accidentally.
        default_devdb = "devdb_strict_pcf" if a.pcf else "devdb_strict"
        if live_portb:
            default_devdb += "_portb"
        custom_devdb = os.environ.get("AGAMEMNON_DEVDB")
        devdb = custom_devdb or os.path.join(udir, default_devdb)
        emitter = os.path.join(engine, "emit_uarch_db.py")
        arch_source = os.path.join(engine, "arch.py")
        emit_env = ["AGAMEMNON_CONDUCTION_GATE=1", "AGAMEMNON_HW_CARRY=1",
                    "AGAMEMNON_LEDPADS=1", "AGAMEMNON_STRICT_GATE=1",
                    "AGAMEMNON_XBAR_CONDUCT=1", "AGAMEMNON_CLEAN_SEL_GATE=1"]
        if live_portb:
            emit_env.append("AGAMEMNON_BRAM_PORTB_EXIT=1")
        if a.pcf:
            emit_env += ["AGAMEMNON_PHYSICAL_IO=1", "AGAMEMNON_PADFEED_TOP=1",
                         "AGAMEMNON_HARDEN_PADFEED=1", "AGAMEMNON_LEFT_PAD_OUT=1"]
            env["AGAMEMNON_LEFT_PAD_OUT"] = "1"
        ignored_cache_env = {"AGAMEMNON_DEVDB", "AGAMEMNON_OSS", "AGAMEMNON_UARCH_NEXTPNR",
                             "AGAMEMNON_UARCH_NEXTPNR_RUNTIME", "AGAMEMNON_BASELINE",
                             "AGAMEMNON_PCF_JSON", "AGAMEMNON_PIN", "AGAMEMNON_SYSCLK",
                             "AGAMEMNON_HSE", "AGAMEMNON_SRAM_STUB"}
        emit_context = emit_env + ["%s=%s" % item for item in env.items()
                                   if item[0].startswith("AGAMEMNON_")
                                   and item[0] not in ignored_cache_env]
        fingerprint = _devdb_fingerprint(arch_source, emitter, data, emit_context)
        manifest = os.path.join(devdb, ".source_sha256")

        def cache_matches():
            if not os.path.exists(os.path.join(devdb, "dev_pips.csv")):
                return False
            if custom_devdb:
                return True
            try:
                return open(manifest, encoding="ascii").read().strip() == fingerprint
            except OSError:
                return False

        cache_ok = cache_matches()
        lock_dir = devdb + ".emit-lock"
        have_lock = False
        if not cache_ok and not custom_devdb:
            deadline = time.monotonic() + 120.0
            while True:
                try:
                    os.mkdir(lock_dir)
                    have_lock = True
                    break
                except FileExistsError:
                    try:
                        if time.time() - os.path.getmtime(lock_dir) > 300:
                            os.rmdir(lock_dir)
                            continue
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for device-database cache lock: %s" % lock_dir)
                    time.sleep(0.1)
            # Another build may have completed the same cache while this one waited.
            cache_ok = cache_matches()
        try:
            if not cache_ok:
                if not custom_devdb and os.path.isdir(devdb):
                    shutil.rmtree(devdb)
                emit_cmd = [sys.executable, emitter, "--arch", arch_source, "--data", data,
                            "--out", devdb]
                for item in emit_env:
                    emit_cmd += ["--env", item]
                run("emit-devdb", emit_cmd)
                # Runtime-only placement/route evidence consumed directly by
                # the C++ packer (not represented by dev_*.csv rows).
                for runtime_asset in ("master_conduction.csv", "mcu_ahb32_corridors.csv",
                                      "mcu_ahb32_addr_corridors.csv"):
                    src_asset = os.path.join(data, runtime_asset)
                    if os.path.exists(src_asset):
                        shutil.copy(src_asset, devdb)
                if not custom_devdb:
                    with open(manifest, "w", encoding="ascii") as f:
                        f.write(fingerprint + "\n")
        finally:
            if have_lock:
                try:
                    os.rmdir(lock_dir)
                except OSError:
                    pass
        try:
            _validate_uarch_devdb(devdb)
        except RuntimeError as exc:
            print("error: %s" % exc)
            sys.exit(1)
        if a.qualified_checkpoint:
            # Turn a hardware-qualified routed checkpoint into a narrow routing
            # oracle: replay its packed placement and expose only PIPs that the
            # known-running image used.  nextpnr still performs routing; this
            # makes that result reproducible while the global map is incomplete.
            qualified_db = os.path.join(tmp, "qualified_devdb")
            shutil.copytree(devdb, qualified_db)
            run("qualify-route", [sys.executable, os.path.join(engine, "qualify_route_db.py"),
                                  a.qualified_checkpoint, os.path.join(devdb, "dev_pips.csv"),
                                  os.path.join(qualified_db, "dev_pips.csv"), "--filter"])
            run("placement-map", [sys.executable, os.path.join(engine, "placement_replay.py"), "--map",
                                  a.qualified_checkpoint, os.path.join(qualified_db, "placement.csv")])
            devdb = qualified_db
            env["AGRV2K_REPLAY_BELS_IN_DB"] = "1"
        env["AGRV2K_CONDPLACE"] = "1"
        env["AGRV2K_BRAM_HARDCONST"] = "1"
        env["AGRV2K_BRAM_PINPACK"] = "1"
        env["AGRV2K_IO_PINPACK"] = "1"
        # Small handshake clusters are no-ops when these nets are absent. They keep common bus/RF
        # return cones on a silicon-proven local crossbar in large sequential designs such as SERV.
        env["AGRV2K_CLUSTER_MEM_ACK"] = "1"
        env["AGRV2K_CLUSTER_RF_READY"] = "1"
        # Seed 4 remains the first regional tie-break ordering because it is
        # qualified across independent large RTL structures.  Routing is not
        # monotonic in that ordering, however: the three-UART example closes
        # with seeds 2 and 7 while seed 4 reaches a resource conflict.  Unless
        # the caller locks one seed explicitly, try those two bounded fallback
        # orderings before changing the netlist with fanout splitting.
        seed_locked = "AGRV2K_CONDPLACE_SEED" in env
        env.setdefault("AGRV2K_CONDPLACE_SEED", "4")
        route_seeds = [env["AGRV2K_CONDPLACE_SEED"]] if seed_locked else ["4", "2", "7"]
        env["AGAMEMNON_MESH_TEMPLATE"] = "1"
        env["AGAMEMNON_LEDPADS"] = "1"
        # Route and pack only selector encodings recovered without conflicting
        # evidence.  This is deliberately fail-closed: an electrically
        # plausible edge is not usable until its independent RMUX/IMUX node
        # block has a clean physical or unanimous tile-relative encoding.
        env["AGAMEMNON_CLEAN_SEL_GATE"] = "1"
        npr = unpr_parts + ["--uarch", "agrv2k", "-o", "chipdb=" + devdb,
                            "--json", synth_json, "--write", routed_json, "--router", "router2"]
        if freq is not None:
            npr += ["--freq", str(freq)]
        if os.path.basename(unpr_parts[0]).lower() in ("wsl", "wsl.exe"):
            npr = _translate_wsl_nextpnr_args(npr)
            _forward_wsl_uarch_environment(env)
        # ROUTE-DRIVEN escalation over BOTH cells/tile (cap) and fanout. Neither knob dominates: a counter
        # routes SPREAD (low cap) while a shift register routes PACKED (high cap co-locates cells on one
        # tile's conducting crossbar, cutting inter-tile hops). And the conducting fanout limit is >2, so
        # splitting nets a design DOESN'T need corrupts it (fanout_split cascades on feedback loops and
        # explodes the netlist). So: PHASE A sweeps cap ascending, UNSPLIT, stopping at the first that
        # routes; PHASE B (only if A fails) adds fanout_split at the largest cap, escalating tighter
        # (16->8->4->--maxfo). fanout_split rewrites synth_json in place, so snapshot & restore each attempt.
        pristine = synth_json + ".prefo"
        shutil.copy(synth_json, pristine)
        attempts = _uarch_attempts(a.cap, a.maxfo, split_first=live_portb)
        log = None
        routed_but_timing_failed = False
        no_fmax_available = False
        for attempt, (cap, fo) in enumerate(attempts):
            shutil.copy(pristine, synth_json)                 # always start from the un-split netlist
            if fo > 0:
                folog = run("fanout-split(maxfo=%d)" % fo,
                            [sys.executable, os.path.join(engine, "fanout_split.py"), synth_json, str(fo)])
                # a split that replicated nothing leaves the netlist == an attempt already tried -> skip.
                if "replicated 0 driver copies" in folog:
                    continue
            env["AGRV2K_CONDPLACE_CAP"] = str(cap)
            for seed_index, seed in enumerate(route_seeds):
                env["AGRV2K_CONDPLACE_SEED"] = seed
                # Cap and seed are chosen inside the attempt loop, after the base
                # WSLENV forwarding list was assembled. Refresh it so WSL imports
                # the controls that the Windows-side log advertises.
                if os.path.basename(unpr_parts[0]).lower() in ("wsl", "wsl.exe"):
                    _forward_wsl_uarch_environment(env)
                rlog = run("place&route (cap=%d, seed=%s, fanout %s)" %
                           (cap, seed, "off" if fo == 0 else "maxfo=%d" % fo),
                           npr, check=False, child_env=_build_tool_env(env, oss=oss, runtime=npr_runtime))
                if _nextpnr_aborted(rlog, run.returncode):
                    print(rlog[-4000:])
                    print("error: nextpnr aborted; placement/routing retries are unsafe for this failure")
                    sys.exit(1)
                if _nonretryable_uarch_failure(rlog):
                    print(rlog[-4000:])
                    print("error: nextpnr rejected a deterministic hardware constraint; "
                          "placement/routing retries cannot make this image safe")
                    sys.exit(1)
                if _route_and_timing_succeeded(rlog, run.returncode, require_fmax=require_timing_path):
                    log = rlog
                    break
                if "Routing complete" in rlog:
                    routed_but_timing_failed = True
                    no_fmax_available = no_fmax_available or "No Fmax available" in rlog
                    # Placement/fanout retries cannot create a sequential timing
                    # endpoint in a design that has none.
                    if no_fmax_available and require_timing_path:
                        break
                if seed_index + 1 < len(route_seeds):
                    print("[build]   did not route; retrying deterministic seed")
            if log is not None or (no_fmax_available and require_timing_path):
                break
            if attempt + 1 < len(attempts):
                print("[build]   did not route; escalating")
        os.remove(pristine)
        if log is None:
            if rlog:
                print(rlog[-4000:])
            if no_fmax_available and require_timing_path:
                print("error: frequency target requested, but nextpnr found no interior clocked timing path")
                sys.exit(1)
            if routed_but_timing_failed and freq is not None:
                print("error: routing completed, but the %.3f MHz timing target was not met" % freq)
                sys.exit(1)
            print("error: routing did not complete after cap/fanout escalation (the design exceeds the "
                  "conducting graph — see examples/uarch_sequential.md limits)"); sys.exit(1)
    else:
        # Router1's path search fails on otherwise legal physical-I/O and MCU-exit routes once the
        # characterized multi-nanosecond wire delays are present. Router2 finds those routes and then
        # invokes router1's legality checker before accepting them, preserving the same final-route
        # invariant while allowing the real timing model to remain enabled.
        npr = ["nextpnr-generic", "--pre-pack", os.path.join(engine, "arch.py"),
               "--router", "router2"]
        # DEFAULT placement = conduction-aware auto-placer (place_auto): detects the design's I/O
        # (MCU_DOUT/MCU_DIN/MCU) + places logic on silicon-conducting tiles/links automatically -- no
        # per-design hook or env tuning. --leds keeps the LED-pad placer; --pin-hook overrides both.
        hook = a.pin_hook or ("pin_leds.py" if a.leds else "place_auto.py")
        if hook == "place_auto.py":
            # conduction-aware routing preference the auto-placer relies on (prefer proven-conducting pips).
            env.setdefault("AGAMEMNON_SOFT_PREFER", "1")
            env.setdefault("AGAMEMNON_SOFT_PENALTY", "1.5")
            env.setdefault("AGAMEMNON_EXIT_TILE", "14,12")
        npr += ["--pre-place", os.path.join(engine, hook)]
        npr += ["--json", synth_json, "--write", routed_json]
        if freq is not None:
            npr += ["--freq", str(freq)]
        try:
            version = _preflight_nextpnr(npr[:1], oss_env)
        except RuntimeError as exc:
            print("error: %s" % exc)
            sys.exit(1)
        for line in version.splitlines():
            if "nextpnr" in line.lower():
                print("[build] nextpnr preflight: %s" % line.strip())
                break
        log = run("place&route", npr,
                  child_env=_build_tool_env(env, oss=oss, use_oss=bool(oss)))
        if "Routing complete" not in log:
            print(log[-1500:]); print("error: routing did not complete"); sys.exit(1)
        if require_timing_path and "No Fmax available" in log:
            print("error: frequency target requested, but nextpnr found no interior clocked timing path")
            sys.exit(1)
    if freq is not None:
        for line in log.splitlines():
            if ("Max frequency" in line or "MHz (PASS" in line or "MHz (FAIL" in line
                    or "No Fmax available" in line):
                print("[timing] " + line.strip())
    # bitgen via the engine's to_bin (writes the 99944-byte uncompressed .bin + <out>.comp)
    log = run("bitgen", [sys.executable, os.path.join(engine, "to_bin.py"), routed_json, out])
    for line in log.splitlines():
        if "unmapped" in line or "registered slices" in line or "IO LED" in line or "wrote" in line:
            print("        " + line.strip())
    print("built %s -> %s" % (", ".join(sources), out))
    if getattr(a, "write_routed", None):
        shutil.copy(routed_json, a.write_routed)
        print("routed netlist -> %s" % a.write_routed)
    if getattr(a, "verify", False):
        # hardware-free behavioural check: cycle-sim the ACTUAL routed netlist and report the read-values
        # the design will produce on silicon over AHB 0x60000000, plus the MCU_DOUT bind soundness.
        import verify_netlist as V
        print("[build] verify:")
        if not V.summary(routed_json, cycles=a.verify_cycles):
            print("error: MCU_DOUT readout bind is SCRAMBLED (h<k> not mapped to AHB bit k)"); sys.exit(1)
    if project is not None:
        mcu_output = PJ.build_mcu(project)
        PJ.write_flash_plan(project, mcu_output=mcu_output, fabric_output=out)


def cmd_transport_probe(a):
    if a.transport == "dap":
        return P.cmd_probe(a)
    if a.transport == "uart":
        return U.cmd_uart_probe(a)
    return USB.cmd_usb_probe(a)


def cmd_transport_backup(a):
    if a.transport == "dap":
        return P.cmd_backup(a)
    if a.transport == "uart":
        return U.cmd_uart_backup(a)
    return USB.cmd_usb_backup(a)


def cmd_transport_flash(a):
    # Every transport erases 4-KiB sectors before writing, so a full-flash backup
    # is the only recovery path -- require it uniformly (DAP included), not just
    # for UART/USB.
    if not a.backup:
        print("refusing: flash writes require a complete --backup path (erases are destructive)")
        raise SystemExit(2)
    if a.transport == "dap":
        return P.cmd_flash(a)
    if a.transport == "uart":
        return U.cmd_uart_flash(a)
    return USB.cmd_usb_flash(a)


def cmd_transport_go(a):
    if a.transport != "usb":
        print("error: GO is currently qualified only for the flash-resident USB uploader")
        raise SystemExit(2)
    return USB.cmd_usb_go(a)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agamemnon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="diagnose toolchain, transports, ports, probes, and connected AG32")
    doctor.add_argument("--json", action="store_true", help="machine-readable report")
    doctor.add_argument("--no-hardware", action="store_true", help="check host tools and enumeration without probing targets")
    doctor.add_argument("--probe-dap", action="store_true", help="probe DAP even when USB already identified the target (may reset/halt it briefly)")
    doctor.add_argument("--uart-port", help="also reset/probe the mask-ROM target through this Pico bridge")
    doctor.set_defaults(fn=D.cmd_doctor)

    qualify = sub.add_parser(
        "qualify",
        help="create a read-only host/support/artifact report for qualification review",
    )
    qualify.add_argument(
        "--artifact", action="append", default=[],
        help="file to hash into the report (repeatable; file is never modified)",
    )
    qualify.add_argument("--notes", help="operator, fixture, wiring, or observation notes")
    qualify.add_argument("-o", "--output", help="write JSON here instead of stdout")
    qualify.set_defaults(fn=Q.cmd_qualify)

    install_openocd = sub.add_parser(
        "install-openocd", help="download, verify, and activate the qualified AG32 OpenOCD"
    )
    install_openocd.add_argument("--version", default=TI.DEFAULT_VERSION)
    install_openocd.add_argument("--prefix", help="installation directory (default ~/.agamemnon)")
    install_openocd.add_argument("--base-url", help="release directory override for mirrors/testing")
    install_openocd.set_defaults(fn=TI.cmd_install_openocd)

    new = sub.add_parser("new", help="create an AG32 project from a maintained template")
    new.add_argument("name", help="new project directory")
    new.add_argument("--board", default="ag32vf303-l48", choices=["ag32vf303-l48"])
    # Default to the fabric-free MCU-only starter: it builds with just RISC-V GCC
    # and needs no Yosys/nextpnr. mcu-fpga (the MCU<->fabric bridge demo) is opt-in.
    new.add_argument("--template", default="mcu-blink", choices=PJ.TEMPLATE_NAMES)
    new.set_defaults(fn=PJ.cmd_new)

    # ---- FPGA fabric ----
    b = sub.add_parser("build", help="Verilog -> synth -> place&route -> .bin (open flow)")
    b.add_argument("input", nargs="?", help="Verilog source (.v); omit inside a directory with agamemnon.toml")
    b.add_argument("--source", dest="sources", action="append", default=[], help="additional Verilog source (repeatable)")
    b.add_argument("--top", help="top-level Verilog module for a multi-source build")
    b.add_argument("--project", help="project manifest or directory (default ./agamemnon.toml)")
    b.add_argument("-o", "--output", help="output .bin (default <name>.bin)")
    b.add_argument("--leds", action="store_true", help="expose the (1,4) LED output pads + pin them")
    b.add_argument("--mcu", action="store_true", help="enable the MCU-edge (din/dout) interface")
    b.add_argument("--true-topo", action="store_true", help="route on harvested real edges only")
    b.add_argument("--no-intra-rmux", action="store_true", help="drop intra-tile RMUX hops (avoid un-encodable edges)")
    b.add_argument("--pin", help="pin the single GENERIC_SLICE to this bel, e.g. X10Y4_SLICE0")
    b.add_argument("--pin-hook", help="custom --pre-place hook filename in the engine dir")
    b.add_argument("--baseline", help="baseline .bin for clock/preamble reuse")
    b.add_argument("--pcf", help="package-pin constraints: `set_io <port> PIN_<n>` (L48 physical map)")
    b.add_argument("--uarch", action="store_true",
                   help="use the supported agrv2k nextpnr release flow with the filtered device graph "
                        "and regional placer; requires $AGAMEMNON_UARCH_NEXTPNR")
    b.add_argument("--cap", type=int, default=5,
                   help="[--uarch] cells/tile hint used by the placer and split-net retry sweep "
                        "(default 5)")
    b.add_argument("--maxfo", type=int, default=2,
                   help="[--uarch] tightest fanout floor for the route-driven escalation (tries unsplit "
                        "first across the cap sweep, then splits progressively down to this if routing fails)")
    b.add_argument("--hard-carry", action="store_true",
                   help="[--uarch] lower arithmetic into the dedicated AG32_FA Cin/Cout chain "
                        "(qualified same-tile footprints or one 33-site corridor for up to 32 stages)")
    b.add_argument("--qualified-checkpoint",
                   help="[--uarch] replay placement and route only through PIPs from a routed, "
                        "silicon-qualified nextpnr JSON checkpoint")
    b.add_argument("--write-routed", help="retain the final placed+routed nextpnr JSON at this path")
    b.add_argument(
        "--freq", type=float,
        help="qualified fabric frequency in MHz; set the emitted PLL and fail if timing does not close "
             "(default 10; AGAMEMNON_SYSCLK overrides the default)",
    )
    b.add_argument("--verify", action="store_true",
                   help="after building, cycle-sim the routed netlist and print the AHB read-values it will "
                        "produce + the MCU_DOUT bind check (hardware-free)")
    b.add_argument("--verify-cycles", type=int, default=96, help="cycles to simulate for --verify")
    b.set_defaults(fn=cmd_build)

    pk = sub.add_parser("pack", help="routed nextpnr JSON -> flashable .bin (uncompressed + .comp)")
    pk.add_argument("input", help="routed nextpnr 'generic' --write JSON")
    pk.add_argument("output", help="output .bin (99944-byte uncompressed; .comp written alongside)")
    pk.add_argument("--baseline", help="baseline .bin for clock/preamble reuse")
    pk.set_defaults(fn=cmd_pack)
    up = sub.add_parser("unpack", help=".bin -> 99936-byte raw fabric config image")
    up.add_argument("input"); up.add_argument("-o", "--output", required=True); up.set_defaults(fn=cmd_unpack)
    d = sub.add_parser("decode"); d.add_argument("input"); d.add_argument("-o", "--output", required=True); d.set_defaults(fn=cmd_decode)
    e = sub.add_parser("encode"); e.add_argument("input"); e.add_argument("-o", "--output", required=True); e.set_defaults(fn=cmd_encode)
    ta = sub.add_parser("to-agasc", help=".bin -> lossless named per-tile .agasc ASCII")
    ta.add_argument("input"); ta.add_argument("-o", "--output", required=True); ta.set_defaults(fn=cmd_to_agasc)
    fa = sub.add_parser("from-agasc", help=".agasc ASCII -> CRC-correct flashable .bin")
    fa.add_argument("input"); fa.add_argument("-o", "--output", required=True)
    fa.add_argument("--uncompressed", action="store_true", help="write header + 99936 raw bytes instead of LZW")
    fa.set_defaults(fn=cmd_from_agasc)
    el = sub.add_parser("edit-lut"); el.add_argument("input"); el.add_argument("--le", required=True, help="x,y,z"); el.add_argument("--init", required=True, help="16-bit truth table, e.g. 0x96e9"); el.add_argument("-o", "--output", required=True); el.set_defaults(fn=cmd_edit_lut)
    vf = sub.add_parser("verify", help="cycle-sim a routed nextpnr JSON offline: report the AHB read-values "
                                       "it produces (+ optionally check a silicon-observed value set)")
    vf.add_argument("input", help="routed nextpnr 'generic' --write JSON")
    vf.add_argument("--observed", help="comma-separated silicon-observed read values to check (SOUND/COVER)")
    vf.add_argument("--cycles", type=int, default=96, help="cycles to simulate")
    vf.set_defaults(fn=cmd_verify)

    # ---- chip (SWD; the open programmer, agamemnon/program.py) ----
    def transport(parser, default="dap"):
        parser.add_argument("--transport", choices=["dap", "uart", "usb"], default=default)
        parser.add_argument("--port", help="serial port for UART Pico bridge or USB CDC uploader")

    pr = sub.add_parser("probe", help="identify AG32 over DAP, mask-ROM UART, or USB CDC")
    transport(pr)
    pr.set_defaults(fn=cmd_transport_probe)
    sr = sub.add_parser("sram", help="SRAM-inject a fabric image + firmware and run it (volatile)")
    sr.add_argument("firmware", help="RISC-V .bin loaded at 0x20000000 and run")
    sr.add_argument("-b", "--fabric", help="uncompressed fabric .bin loaded at 0x20002000")
    sr.add_argument("-w", "--words", type=int, default=10, help="result words to read from 0x20001000")
    sr.add_argument("--sleep", type=int, default=500, help="ms to run before halting")
    sr.set_defaults(fn=P.cmd_sram)
    bk = sub.add_parser("backup", help="dump the whole 256 KB flash over DAP, UART, or USB")
    bk.add_argument("output")
    transport(bk)
    bk.set_defaults(fn=cmd_transport_backup)
    fl = sub.add_parser("flash", help="erase+program a binary to flash at --addr (open flasher, no agrv)")
    fl.add_argument("image", help="binary to write")
    fl.add_argument("--addr", required=True, help="flash address, e.g. 0x80008100")
    fl.add_argument("--backup", help="dump full flash here before writing (required; erases are destructive)")
    transport(fl)
    fl.set_defaults(fn=cmd_transport_flash)
    go = sub.add_parser("go", help="launch an address through the flash-resident USB uploader")
    go.add_argument("addr", help="application entry address, e.g. 0x80010000")
    transport(go, default="usb")
    go.set_defaults(fn=cmd_transport_go)
    im = sub.add_parser("image", help="assemble (+ optionally flash) a combined flash-boot image")
    im.add_argument("-b", "--fabric", required=True, help="uncompressed fabric .bin")
    im.add_argument("-m", "--mcu", help="MCU firmware .bin (-> 0x80000000)")
    im.add_argument("--logic-addr", help="fabric flash address, 4KB-aligned (default 0x80010000)")
    im.add_argument("--flash", action="store_true", help="actually write it (default: print plan only)")
    im.add_argument("--backup", help="dump full flash here before writing")
    im.add_argument("--write-options", action="store_true",
                    help="also write the option config-pointer (UNVERIFIED; requires --backup)")
    im.set_defaults(fn=P.cmd_image)

    # ---- chip (mask-ROM UART0 through pico/ag32_uart_programmer) ----
    def uart_port(parser):
        parser.add_argument("--port", help="Pico USB serial port (auto-detected if unique)")

    upr = sub.add_parser("uart-probe", help="identify AG32 through the Pico-controlled UART boot ROM")
    uart_port(upr)
    upr.set_defaults(fn=U.cmd_uart_probe)
    ubk = sub.add_parser("uart-backup", help="dump all 256 KiB of main flash through UART0")
    ubk.add_argument("output")
    uart_port(ubk)
    ubk.set_defaults(fn=U.cmd_uart_backup)
    ufl = sub.add_parser("uart-flash", help="backup, sector-preserve, program, verify, and reset via UART0")
    ufl.add_argument("image", help="binary to write")
    ufl.add_argument("--addr", required=True, help="main-flash address, e.g. 0x80000000")
    ufl.add_argument("--backup", required=True, help="mandatory full 256-KiB pre-write backup path")
    uart_port(ufl)
    ufl.set_defaults(fn=U.cmd_uart_flash)
    urs = sub.add_parser("uart-reset", help="drive BOOT0 low and reset AG32 into main flash")
    uart_port(urs)
    urs.set_defaults(fn=U.cmd_uart_reset)

    run = sub.add_parser("run", help="run the current project without manually naming artifacts")
    run.add_argument("--project", help="project manifest or directory")
    run.add_argument("--transport", choices=["dap", "usb", "uart"], default="dap")
    run.add_argument("--port")
    run.add_argument("--flash", action="store_true", help="program the MCU image before USB GO")
    run.add_argument("--backup", help="mandatory full-flash backup for --flash")
    run.add_argument("--words", type=int, default=4)
    run.add_argument("--sleep", type=int, default=500)
    run.set_defaults(fn=PJ.cmd_run)

    monitor = sub.add_parser("monitor", help="open a serial terminal")
    monitor.add_argument("--port")
    monitor.add_argument("--baud", type=int, default=115200)
    monitor.set_defaults(fn=PJ.cmd_monitor)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (U.UartProgrammingError, FileNotFoundError, ValueError,
            subprocess.CalledProcessError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
