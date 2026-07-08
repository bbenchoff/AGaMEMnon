#!/usr/bin/env python3
"""Project AGaMEMnon — the open AG32 / AGRV2K toolchain, one command for both halves of the chip.

No vendor binary in any path here: yosys+nextpnr build the fabric bitstream, the LZW `.bin` codec /
LUT editor / bitgen are open and byte-exact vs af.exe, and the programmer drives the flash controller
directly (no vendor `agrv` OpenOCD driver, no "Supra" install).

  FPGA fabric:
    agamemnon build foo.v -o foo.bin         # Verilog -> synth -> place&route -> .bin (open flow)
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
    def run(step, cmd):
        exe = shutil.which(cmd[0], path=env.get("PATH")) or cmd[0]   # Windows: find via child PATH
        cmd = [exe] + cmd[1:]
        print("[build] %s: %s" % (step, " ".join(os.path.basename(c) if os.sep in c else c for c in cmd)))
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout[-1500:]); print(r.stderr[-1500:]); print("error: %s failed" % step); sys.exit(1)
        return r.stdout + r.stderr

    # always wrap top-level ports as GENERIC_IOB (iopadmap) so nextpnr can bind them to IO bels
    synth_tcl = os.path.join(SYNTH, "synth_pads.tcl")
    run("synth", ["yosys", "-q", "-p", "tcl %s 4 %s" % (synth_tcl, synth_json), a.input])
    # Qin self-feedback fix: permute each registered FF's self-feedback LUT input to pinC (I[2]) so it
    # uses the slice's INTERNAL feedback path (never routed) + cell-to-cell reads to input D. WITHOUT this
    # every counter/FSM freezes (self-feedback can't route). Idempotent; safe for combinational designs.
    run("qin", [sys.executable, os.path.join(engine, "qin_pack.py"), synth_json])
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
