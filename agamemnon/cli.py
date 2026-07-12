#!/usr/bin/env python3
"""Project AGaMEMnon — the open AG32 / AGRV2K toolchain, one command for both halves of the chip.

No vendor binary in any path here: yosys+nextpnr build the fabric bitstream, the LZW `.bin` codec /
LUT editor / bitgen are open and byte-exact vs af.exe, and the programmer drives the flash controller
directly (no vendor `agrv` OpenOCD driver, no "Supra" install).

  FPGA fabric:
    agamemnon build foo.v -o foo.bin         # Verilog -> synth -> place&route -> .bin (open flow)
    agamemnon build foo.v -o foo.bin --uarch --verify   # agrv2k uarch flow + offline behavioural check
    agamemnon verify foo_routed.json         # cycle-sim a routed design: the AHB read-values it produces
    agamemnon pack foo_routed.json foo.bin   # routed nextpnr JSON -> .bin  (icepack)
    agamemnon unpack foo.bin -o raw.img      # .bin -> 99936-byte raw image (iceunpack)
    agamemnon decode fabric.bin -o raw.img   # .bin -> 99936-byte raw config image
    agamemnon encode raw.img   -o fabric.bin # raw image -> .bin (byte-exact LZW)
    agamemnon edit-lut in.bin --le 17,4,1 --init 0x96e9 -o out.bin
  chip (SWD via a CMSIS-DAP probe + an OpenOCD built with `riscv -dap`):
    agamemnon probe                          # read DEVICE_ID over SWD (expect 0x40200001)
    agamemnon sram fw.bin -b fabric.bin      # SRAM-inject a bitstream + firmware and run it (volatile)
    agamemnon backup full.bin                # dump the whole 256 KB flash
    agamemnon flash foo.bin --addr 0x80008100 --backup full.bin   # open flasher: erase+program+verify
    agamemnon image -b fabric.bin -m fw.bin --flash --backup f.bin  # assemble+flash a boot image
"""
import os, sys, argparse, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine")        # the self-contained engine (single source of truth)
CHIPDB = os.path.join(HERE, "chipdb")        # the shipped device database
SYNTH = os.path.join(HERE, "synth")          # yosys synth scripts (prims/cells_map + tcl)
sys.path.insert(0, ENGINE)                    # engine modules import each other by bare name
import lzw_codec as L                          # noqa: E402
import physmap                                 # noqa: E402
from . import program as P                     # noqa: E402  (the SWD programmer / open flasher)

RAW_LEN = 99936
HDR = bytes.fromhex("40200001") + bytes.fromhex("0000ffff")   # DEVICE_ID | max_index


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
    r = subprocess.run([sys.executable, to_bin, a.input, a.output], env=env,
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
    engine = os.environ.get("AGAMEMNON_ENGINE", ENGINE)
    data = os.environ.get("AGAMEMNON_DATA", CHIPDB)
    base = os.path.splitext(os.path.basename(a.input))[0]
    out = a.output or (base + ".bin")
    tmp = tempfile.mkdtemp(prefix="agamemnon_build_")
    synth_json = os.path.join(tmp, base + ".json")
    routed_json = os.path.join(tmp, base + "_routed.json")

    env = dict(os.environ)
    env["AGAMEMNON_DATA"] = data
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join([os.path.join(oss, "bin"), os.path.join(oss, "lib"), env.get("PATH", "")])
    env["PYTHONPATH"] = os.pathsep.join([engine, env.get("PYTHONPATH", "")])
    for flag, var in [(a.leds, "AGAMEMNON_LEDPADS"), (a.mcu, "AGAMEMNON_MCU_ENTRY"),
                      (a.true_topo, "AGAMEMNON_TRUE_TOPO"), (a.no_intra_rmux, "AGAMEMNON_NO_INTRA_RMUX")]:
        if flag: env[var] = "1"
    if a.pin: env["AGAMEMNON_PIN"] = a.pin
    if a.baseline: env["AGAMEMNON_BASELINE"] = a.baseline

    import shutil
    def run(step, cmd, check=True):
        exe = shutil.which(cmd[0], path=env.get("PATH")) or cmd[0]   # Windows: find via child PATH
        cmd = [exe] + cmd[1:]
        print("[build] %s: %s" % (step, " ".join(os.path.basename(c) if os.sep in c else c for c in cmd)))
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if r.returncode != 0 and check:
            print(r.stdout[-1500:]); print(r.stderr[-1500:]); print("error: %s failed" % step); sys.exit(1)
        return r.stdout + r.stderr

    # always wrap top-level ports as GENERIC_IOB (iopadmap) so nextpnr can bind them to IO bels
    synth_tcl = os.path.join(SYNTH, "synth_pads.tcl")
    run("synth", ["yosys", "-q", "-p", "tcl %s 4 %s" % (synth_tcl, synth_json), a.input])
    # Qin self-feedback fix: permute each registered FF's self-feedback LUT input to pinC (I[2]) so it
    # uses the slice's INTERNAL feedback path (never routed) + cell-to-cell reads to input D. WITHOUT this
    # every counter/FSM freezes (self-feedback can't route). Idempotent; safe for combinational designs.
    run("qin", [sys.executable, os.path.join(engine, "qin_pack.py"), synth_json])
    if getattr(a, "uarch", False):
        # ---- agrv2k uarch flow (silicon-proven for multi-bit sequential; see examples/uarch_sequential.md).
        # The device is CONDUCTION-GATED (router can't pick electrically-dead pips) and placement is
        # conduction-aware (pack_condplace). Needs the uarch-built nextpnr-generic: $AGAMEMNON_UARCH_NEXTPNR
        # (a path/command), else `nextpnr-generic` on PATH must itself be the uarch build (built via
        # engine/uarch/agrv2k/build.sh). The gated devdb is auto-emitted+cached on first use.
        udir = os.path.join(engine, "uarch", "agrv2k")
        devdb = os.environ.get("AGAMEMNON_DEVDB", os.path.join(udir, "devdb_gate"))
        if not os.path.exists(os.path.join(devdb, "dev_pips.csv")):
            run("emit-devdb", [sys.executable, os.path.join(engine, "emit_uarch_db.py"),
                               "--arch", os.path.join(engine, "arch.py"), "--data", data, "--out", devdb,
                               "--env", "AGAMEMNON_CONDUCTION_GATE=1", "--env", "AGAMEMNON_HW_CARRY=1",
                               "--env", "AGAMEMNON_LEDPADS=1"])
            mc = os.path.join(data, "master_conduction.csv")
            if os.path.exists(mc):
                shutil.copy(mc, devdb)
        env["AGRV2K_CONDPLACE"] = "1"
        env["AGAMEMNON_MESH_TEMPLATE"] = "1"
        env["AGAMEMNON_LEDPADS"] = "1"
        unpr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR", "nextpnr-generic")
        npr = unpr.split() + ["--uarch", "agrv2k", "-o", "chipdb=" + devdb,
                              "--json", synth_json, "--write", routed_json]
        # ROUTE-DRIVEN escalation over BOTH cells/tile (cap) and fanout. Neither knob dominates: a counter
        # routes SPREAD (low cap) while a shift register routes PACKED (high cap co-locates cells on one
        # tile's conducting crossbar, cutting inter-tile hops). And the conducting fanout limit is >2, so
        # splitting nets a design DOESN'T need corrupts it (fanout_split cascades on feedback loops and
        # explodes the netlist). So: PHASE A sweeps cap ascending, UNSPLIT, stopping at the first that
        # routes; PHASE B (only if A fails) adds fanout_split at the largest cap, escalating tighter
        # (16->8->4->--maxfo). fanout_split rewrites synth_json in place, so snapshot & restore each attempt.
        pristine = synth_json + ".prefo"
        shutil.copy(synth_json, pristine)
        caps = sorted({2, 4, 8, a.cap})                       # --cap is a hint folded into the sweep
        attempts = [(c, 0) for c in caps]                     # phase A: unsplit, ascending cap
        fos, seenfo = [], set()
        for fo in [16, 8, 4, a.maxfo]:                        # phase B fanout ladder (looser -> tighter)
            if fo > 0 and fo not in seenfo:
                seenfo.add(fo); fos.append(fo)
        attempts += [(caps[-1], fo) for fo in fos]            # phase B: split at the largest cap
        log = None
        for attempt, (cap, fo) in enumerate(attempts):
            shutil.copy(pristine, synth_json)                 # always start from the un-split netlist
            if fo > 0:
                folog = run("fanout-split(maxfo=%d)" % fo,
                            [sys.executable, os.path.join(engine, "fanout_split.py"), synth_json, str(fo)])
                # a split that replicated nothing leaves the netlist == an attempt already tried -> skip.
                if "replicated 0 driver copies" in folog:
                    continue
            env["AGRV2K_CONDPLACE_CAP"] = str(cap)
            rlog = run("place&route (cap=%d, fanout %s)" % (cap, "off" if fo == 0 else "maxfo=%d" % fo),
                       npr, check=False)
            if "Routing complete" in rlog:
                log = rlog; break
            if attempt + 1 < len(attempts):
                print("[build]   did not route; escalating")
        os.remove(pristine)
        if log is None:
            print("error: routing did not complete after cap/fanout escalation (the design exceeds the "
                  "conducting graph — see examples/uarch_sequential.md limits)"); sys.exit(1)
    else:
        npr = ["nextpnr-generic", "--pre-pack", os.path.join(engine, "arch.py")]
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
        log = run("place&route", npr)
        if "Routing complete" not in log:
            print(log[-1500:]); print("error: routing did not complete"); sys.exit(1)
    # bitgen via the engine's to_bin (writes the 99944-byte uncompressed .bin + <out>.comp)
    log = run("bitgen", [sys.executable, os.path.join(engine, "to_bin.py"), routed_json, out])
    for line in log.splitlines():
        if "unmapped" in line or "registered slices" in line or "IO LED" in line or "wrote" in line:
            print("        " + line.strip())
    print("built %s -> %s" % (a.input, out))
    if getattr(a, "verify", False):
        # hardware-free behavioural check: cycle-sim the ACTUAL routed netlist and report the read-values
        # the design will produce on silicon over AHB 0x60000000, plus the MCU_DOUT bind soundness.
        import verify_netlist as V
        print("[build] verify:")
        if not V.summary(routed_json, cycles=a.verify_cycles):
            print("error: MCU_DOUT readout bind is SCRAMBLED (h<k> not mapped to AHB bit k)"); sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agamemnon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- FPGA fabric ----
    b = sub.add_parser("build", help="Verilog -> synth -> place&route -> .bin (open flow)")
    b.add_argument("input", help="Verilog source (.v)")
    b.add_argument("-o", "--output", help="output .bin (default <name>.bin)")
    b.add_argument("--leds", action="store_true", help="expose the (1,4) LED output pads + pin them")
    b.add_argument("--mcu", action="store_true", help="enable the MCU-edge (din/dout) interface")
    b.add_argument("--true-topo", action="store_true", help="route on harvested real edges only")
    b.add_argument("--no-intra-rmux", action="store_true", help="drop intra-tile RMUX hops (avoid un-encodable edges)")
    b.add_argument("--pin", help="pin the single GENERIC_SLICE to this bel, e.g. X10Y4_SLICE0")
    b.add_argument("--pin-hook", help="custom --pre-place hook filename in the engine dir")
    b.add_argument("--baseline", help="baseline .bin for clock/preamble reuse")
    b.add_argument("--uarch", action="store_true",
                   help="use the agrv2k nextpnr uarch flow (conduction-gated device + conduction-aware "
                        "placer; silicon-proven for sequential). Needs the uarch build ($AGAMEMNON_UARCH_NEXTPNR).")
    b.add_argument("--cap", type=int, default=2,
                   help="[--uarch] cells/tile hint folded into the placer's cap sweep {2,4,8,--cap}")
    b.add_argument("--maxfo", type=int, default=2,
                   help="[--uarch] tightest fanout floor for the route-driven escalation (tries unsplit "
                        "first across the cap sweep, then splits progressively down to this if routing fails)")
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
    el = sub.add_parser("edit-lut"); el.add_argument("input"); el.add_argument("--le", required=True, help="x,y,z"); el.add_argument("--init", required=True, help="16-bit truth table, e.g. 0x96e9"); el.add_argument("-o", "--output", required=True); el.set_defaults(fn=cmd_edit_lut)
    vf = sub.add_parser("verify", help="cycle-sim a routed nextpnr JSON offline: report the AHB read-values "
                                       "it produces (+ optionally check a silicon-observed value set)")
    vf.add_argument("input", help="routed nextpnr 'generic' --write JSON")
    vf.add_argument("--observed", help="comma-separated silicon-observed read values to check (SOUND/COVER)")
    vf.add_argument("--cycles", type=int, default=96, help="cycles to simulate")
    vf.set_defaults(fn=cmd_verify)

    # ---- chip (SWD; the open programmer, agamemnon/program.py) ----
    pr = sub.add_parser("probe", help="read DEVICE_ID over SWD"); pr.set_defaults(fn=P.cmd_probe)
    sr = sub.add_parser("sram", help="SRAM-inject a fabric image + firmware and run it (volatile)")
    sr.add_argument("firmware", help="RISC-V .bin loaded at 0x20000000 and run")
    sr.add_argument("-b", "--fabric", help="uncompressed fabric .bin loaded at 0x20002000")
    sr.add_argument("-w", "--words", type=int, default=10, help="result words to read from 0x20001000")
    sr.add_argument("--sleep", type=int, default=500, help="ms to run before halting")
    sr.set_defaults(fn=P.cmd_sram)
    bk = sub.add_parser("backup", help="dump the whole 256 KB flash"); bk.add_argument("output"); bk.set_defaults(fn=P.cmd_backup)
    fl = sub.add_parser("flash", help="erase+program a binary to flash at --addr (open flasher, no agrv)")
    fl.add_argument("image", help="binary to write")
    fl.add_argument("--addr", required=True, help="flash address, e.g. 0x80008100")
    fl.add_argument("--backup", help="dump full flash here before writing (recommended)")
    fl.set_defaults(fn=P.cmd_flash)
    im = sub.add_parser("image", help="assemble (+ optionally flash) a combined flash-boot image")
    im.add_argument("-b", "--fabric", required=True, help="uncompressed fabric .bin")
    im.add_argument("-m", "--mcu", help="MCU firmware .bin (-> 0x80000000)")
    im.add_argument("--logic-addr", help="fabric flash address, 4KB-aligned (default 0x80010000)")
    im.add_argument("--flash", action="store_true", help="actually write it (default: print plan only)")
    im.add_argument("--backup", help="dump full flash here before writing")
    im.add_argument("--write-options", action="store_true",
                    help="also write the option config-pointer (UNVERIFIED; requires --backup)")
    im.set_defaults(fn=P.cmd_image)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
