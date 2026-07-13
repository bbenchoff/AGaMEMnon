#!/usr/bin/env python3
"""Offline, hardware-free verification of a routed design.

Cycle-accurate simulator of the ACTUAL ROUTED netlist (the `GENERIC_SLICE` INITs + the real I[0..3]/Q
connectivity + FF_USED + the real MCU_DOUT->AHB-bit binding, all read straight from the nextpnr `--write`
JSON). It answers "what values will the MCU read back over AHB `0x60000000` when this bitstream runs?"
WITHOUT touching the board -- the sim IS the ground truth of what was actually built.

Two uses:
  * `summary(routed_json)` -> the set of read-values the design produces + the MCU_DOUT bind check
    (h<k> must map to AHB bit k; a mismatch is a read-bit-scramble class bug). This is what
    `agamemnon build --verify` prints after routing.
  * `verify(routed_json, observed)` -> compare a silicon-observed value SET to the sim's reachable set:
      SOUND: every observed value is reachable in the sim (a spurious value = the silicon is NOT faithfully
             executing the routed netlist -> a real routing/config error).
      COVER: fraction of sim states observed (misses = deterministic-sampling aliasing, not an error).

No vendor binaries, no board, no absolute paths. Usage:
  python -m agamemnon.engine.verify_netlist <routed.json> [observed e.g. 0,1,2,3] [cycles]
"""
import json, re, sys


def sim_routed(routed_json, cycles=96):
    """Simulate the routed netlist for `cycles` clocks. Returns (reads, bind):
       reads = per-cycle MCU-read value (bits ORed from each MCU_DOUT tap);
       bind  = {mcu-cell-name: (declared h<k>, bel AHB bit)} for the bind check."""
    d = json.load(open(routed_json))
    top = d["modules"]["top"]
    nid = {}
    for nm, ni in top["netnames"].items():
        for b in ni.get("bits", []):
            nid[b] = nm

    def netname(x):
        if x == "1":
            return "__one__"
        if x == "0":
            return None
        return nid.get(x)

    cells = []                     # (qnet, fnet, init, [in_nets], ff_used)
    dout_bit = {}                  # net -> AHB bit
    bind = {}                      # MCU_DOUT cell-name -> (declared bit k, bel bit)
    for cn, c in top["cells"].items():
        t = c.get("type")
        if t == "GENERIC_SLICE" and "PACKER_GND" not in cn:
            I = [netname(n) for n in c["connections"].get("I", [])]
            q = c["connections"].get("Q", [])
            f = c["connections"].get("F", [])
            ffu = int(c["parameters"].get("FF_USED", "0"), 2)
            init = int(c["parameters"]["INIT"], 2)
            cells.append((netname(q[0]) if q else None, netname(f[0]) if f else None, init, I, ffu))
        elif t == "MCU_DOUT":
            bel = c["attributes"].get("NEXTPNR_BEL", "")
            dn = c["connections"].get("DOUT", [])
            mb = re.search(r"MCU_DOUT(\d+)", bel)
            bit = int(mb.group(1)) - 10 if mb else None
            if dn and bit is not None:
                dout_bit[netname(dn[0])] = bit
            mk = re.search(r"h(\d)", cn)
            if mk and bit is not None:
                bind[cn] = (int(mk.group(1)), bit)
        elif t == "GENERIC_IOB" and cn.endswith(".q"):
            # Physical-PCF probes often expose one diagnostic bit as top-level q instead of through
            # MCU_DOUT. Treat that output-pad input as read bit 0 so the same routed-netlist simulator
            # can validate the post-pack LUT/FF behavior before a hardware run.
            pin = c["connections"].get("I", [])
            if pin:
                dout_bit[netname(pin[0])] = 0

    ff = {qn: 0 for (qn, fn, init, I, ffu) in cells if ffu and qn}

    def val(net, comb):
        if net == "__one__":
            return 1
        if net is None:
            return 0
        if net in comb:
            return comb[net]
        return ff.get(net, 0)

    reads = []
    for _ in range(cycles):
        comb = {}                                        # evaluate comb cells (FF_USED=0) to fixpoint
        for _it in range(len(cells) + 3):
            ch = False
            for (qn, fn, init, I, ffu) in cells:
                if ffu or not fn:
                    continue
                idx = sum((val(I[i], comb) if i < len(I) else 0) << i for i in range(4))
                o = (init >> idx) & 1
                if comb.get(fn) != o:
                    comb[fn] = o
                    ch = True
            if not ch:
                break
        rv = 0
        for net, bit in dout_bit.items():
            rv |= (val(net, comb) << bit)
        reads.append(rv)
        nxt = dict(ff)                                   # clock the FFs
        for (qn, fn, init, I, ffu) in cells:
            if ffu and qn:
                idx = sum((val(I[i], comb) if i < len(I) else 0) << i for i in range(4))
                nxt[qn] = (init >> idx) & 1
        ff = nxt
    return reads, bind


def summary(routed_json, cycles=96):
    """Print the read-values a routed design will produce on silicon + the bind check. Returns True if the
    MCU_DOUT bind is sound (h<k> -> AHB bit k). Hardware-free."""
    reads, bind = sim_routed(routed_json, cycles)
    simset = sorted(set(reads))
    bind_ok = all(k == bit for (k, bit) in bind.values())
    nff = "?"
    print("verify: routed-netlist sim over %d cycles" % cycles)
    print("  MCU read-values the design will produce (AHB 0x60000000): %s" % (simset,))
    if bind:
        print("  MCU_DOUT bind (h<k> -> AHB bit k): %s %s"
              % ("OK" if bind_ok else "SCRAMBLED", {c: b for c, (k, b) in bind.items()}))
        if len(simset) > 2:
            print("  => multi-bit sequential: %d distinct read-values (a stuck/toggle output could reach <=2)"
                  % len(simset))
    else:
        print("  (no MCU_DOUT readout taps in this design -- nothing to read over AHB)")
    return bind_ok


def verify(routed_json, observed, cycles=96):
    """Compare a silicon-observed value set to the sim's reachable set (SOUND + COVER + BIND)."""
    reads, bind = sim_routed(routed_json, cycles)
    simset = set(reads)
    obs = set(observed)
    bind_ok = all(k == bit for (k, bit) in bind.values())
    spurious = obs - simset
    cover = len(obs & simset) / max(1, len(simset))
    print("routed-netlist sim reachable values:", sorted(simset))
    print("silicon observed values:            ", sorted(obs))
    print("BIND  (MCU_DOUT h<k>->AHB bit k): %s %s"
          % ("OK" if bind_ok else "SCRAMBLED", {c: b for c, (k, b) in bind.items()}))
    print("SOUND (observed subset of sim):   %s%s"
          % ("PASS" if not spurious else "FAIL", "" if not spurious else "  spurious=%s" % sorted(spurious)))
    print("COVER (sim states seen on silicon): %.0f%% (%d/%d)  missing=%s (aliasing if nonempty)"
          % (100 * cover, len(obs & simset), len(simset), sorted(simset - obs)))
    ok = bind_ok and not spurious
    print("VERDICT:", "CORRECT (silicon faithfully executes the routed netlist)" if ok else "MISMATCH")
    return ok


if __name__ == "__main__":
    rj = sys.argv[1]
    cyc = int(sys.argv[3]) if len(sys.argv) > 3 else 96
    if len(sys.argv) > 2 and sys.argv[2]:
        verify(rj, [int(x) for x in sys.argv[2].split(",")], cyc)
    else:
        summary(rj, cyc)
