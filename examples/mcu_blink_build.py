#!/usr/bin/env python3
"""Build the MCU-controlled PIN_18 blink fabric image through the fully-open flow, using ONLY the
packaged AGaMEMnon engine (no vendor binary).

The design (examples/designs/ahb_pad.v) is a tiny AHB-write slave: the RISC-V core stores to
0x60000000, the fabric captures write-data bit 0 into a register placed at the proven pad-route
source (14,9), and drives it onto PIN_18. The MCU firmware (examples/firmware/ahb_blink.c) writes
0/1 in a loop, so PIN_18 blinks at a rate the firmware sets (~1.25 Hz by default).

  yosys synth -> qin self-feedback fix -> nextpnr-generic (arch.py + pin_ahb_pad.py) -> bitgen, then
  the fixed pad-driver recipe (N-1 CFG_IOMUX source-select + the silicon-proven feeder-hop from
  chipdb/iomux_hop_vendor.csv) is applied to the .bin.

Prereq: yosys + nextpnr-generic on PATH or under $AGAMEMNON_OSS/bin (oss-cad-suite).
Usage:  python examples/mcu_blink_build.py [-o ahb_pad.bin]
Run it: agamemnon sram examples/firmware/ahb_blink.bin -b ahb_pad.bin   # SRAM-inject + run (volatile)
        (build the firmware first: see examples/firmware/, riscv64-unknown-elf-gcc + link.ld)
"""
import os, sys, subprocess, struct, csv, shutil, argparse, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "agamemnon", "engine")
CHIPDB = os.path.join(ROOT, "agamemnon", "chipdb")
SYNTH = os.path.join(ROOT, "agamemnon", "synth")
DESIGN = os.path.join(HERE, "designs", "ahb_pad.v")
from agamemnon.engine import io_emit as IOE

PADX, PADY, PADZ, FEEDER_R = 18, 13, 0, 28   # PIN_18; the route below forces feeder RMUX28
# Force the silicon-proven conducting chain FF@(14,9)->OMUX02->RMUX15->RMUX69@(18,9)->RMUX28->IOMUX00
# by blacklisting every competing in-edge of the two hop RMUXes (the router prefers short DEAD edges).
BLACKLIST = ("RMUX16@18,13->IOMUX00@18,13;OMUX26@18,9->RMUX69@18,9;OMUX29@18,9->RMUX69@18,9;"
    "OMUX30@17,9->RMUX69@18,9;OMUX33@17,9->RMUX69@18,9;RMUX15@15,9->RMUX69@18,9;RMUX15@16,9->RMUX69@18,9;"
    "RMUX15@17,9->RMUX69@18,9;RMUX15@18,9->RMUX69@18,9;RMUX39@18,5->RMUX69@18,9;RMUX39@18,6->RMUX69@18,9;"
    "RMUX39@18,7->RMUX69@18,9;RMUX39@18,8->RMUX69@18,9;RMUX63@19,9->RMUX69@18,9;RMUX63@20,9->RMUX69@18,9;"
    "RMUX87@18,10->RMUX69@18,9;OMUX05@14,9->RMUX15@14,9;RMUX03@14,9->RMUX15@14,9;RMUX03@15,9->RMUX15@14,9;"
    "RMUX27@14,10->RMUX15@14,9;RMUX27@14,11->RMUX15@14,9;RMUX27@14,12->RMUX15@14,9;RMUX27@14,8->RMUX15@14,9;"
    "RMUX51@14,9->RMUX15@14,9;IMUX29@14,12->RMUX15@14,9")

def crc32_bzip2(dd):
    c = 0xFFFFFFFF
    for by in dd:
        c ^= by << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (c & 0x80000000) else (c << 1) & 0xFFFFFFFF
    return c ^ 0xFFFFFFFF

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "ahb_pad.bin"))
    a = ap.parse_args()
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join([os.path.join(oss, "bin"), os.path.join(oss, "lib"), env.get("PATH", "")])
    env["AGAMEMNON_DATA"] = CHIPDB
    env["PYTHONPATH"] = os.pathsep.join([ENGINE, env.get("PYTHONPATH", "")])
    env["AGAMEMNON_EDGE_BLACKLIST"] = BLACKLIST
    env["AGAMEMNON_LEDPADS"] = "1"        # expose the ring-pad OUTPUT bels (OPAD) + the CLKIN bel
    env["AGAMEMNON_PADFEED_TOP"] = "1"; env["AGAMEMNON_PADFEED_ONLY"] = "18,13,0"
    env["AGAMEMNON_MCU_ENTRY"] = "1"
    env["AGAMEMNON_PIN"] = "X14Y9_SLICE0"; env["AGAMEMNON_OPAD"] = "X18Y13_OPAD0"

    def run(step, cmd, need=None):
        exe = shutil.which(cmd[0], path=env.get("PATH")) or cmd[0]
        r = subprocess.run([exe] + cmd[1:], env=env, capture_output=True, text=True)
        log = r.stdout + r.stderr
        if r.returncode != 0 or (need and need not in log):
            print(log[-1800:]); sys.exit("error: %s failed" % step)
        return log

    tmp = tempfile.mkdtemp(prefix="mcu_blink_")
    sj = os.path.join(tmp, "ahb_pad.json"); rj = os.path.join(tmp, "ahb_pad_routed.json")
    run("synth", ["yosys", "-q", "-p", "tcl %s 4 %s" % (os.path.join(SYNTH, "synth_pads.tcl"), sj), DESIGN])
    run("qin", [sys.executable, os.path.join(ENGINE, "qin_pack.py"), sj])
    run("place&route", ["nextpnr-generic", "--pre-pack", os.path.join(ENGINE, "arch.py"),
        "--pre-place", os.path.join(ENGINE, "pin_ahb_pad.py"), "--json", sj, "--write", rj],
        need="Routing complete")
    run("bitgen", [sys.executable, os.path.join(ENGINE, "to_bin.py"), rj, a.output])

    # apply the fixed pad-driver recipe to the .bin: at the N-1 config tile (17,13), clear stale
    # CFG_IOMUX then re-emit the source-select for the routed feeder R, and add the silicon-proven
    # feeder-hop (set) + stray-clear (clear) from chipdb/iomux_hop_vendor.csv.
    d = bytearray(open(a.output, "rb").read()); hdr, raw = d[:8], bytearray(d[8:])
    for (x, y, mux), sels in IOE.CELLS.items():
        if (x, y) == (17, 13) and mux.startswith("CFG_IOMUX"):
            for sel, (b, m) in sels.items():
                if b < len(raw) and (raw[b] & m): raw[b] &= (~m) & 0xFF
    for (b, m) in IOE.emit_bits(17, 13, [(PADZ, FEEDER_R)]): raw[b] |= m
    hop = os.path.join(CHIPDB, "iomux_hop_vendor.csv")
    for row in csv.DictReader([l for l in open(hop) if not l.startswith("#")]):
        if (int(row["pad_x"]), int(row["pad_y"]), int(row["z"]), int(row["feeder_R"])) == (PADX, PADY, PADZ, FEEDER_R):
            for c in row["set_cells"].split(";"):
                b, m = c.split(":"); raw[int(b)] |= int(m)
            for c in row.get("clear_cells", "").split(";"):
                if ":" in c:
                    b, m = c.split(":"); raw[int(b)] &= (~int(m)) & 0xFF
            break
    raw[99932:99936] = struct.pack(">I", crc32_bzip2(bytes(hdr) + bytes(raw[:99932])))
    open(a.output, "wb").write(bytes(hdr) + bytes(raw))
    print("built %s -> %s" % (os.path.relpath(DESIGN, ROOT), a.output))
    print("run: agamemnon sram examples/firmware/ahb_blink.bin -b %s   (PIN_18 blinks ~1.25 Hz)"
          % os.path.relpath(a.output, ROOT))

if __name__ == "__main__":
    main()
