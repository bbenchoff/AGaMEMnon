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


def hrdata_bit_for_bel(bel):
    """Translate the collision-free internal MCU_DOUT BEL id to hrdata[0:31]."""
    m = re.search(r"MCU_DOUT(\d+)", bel or "")
    if not m:
        return None
    lane = int(m.group(1))
    if 10 <= lane <= 19:
        return lane - 10
    if 23 <= lane <= 44:
        return lane - 13
    return None


def sim_routed(routed_json, cycles=96, document=None, stimulus=None, probe=None):
    """Simulate the routed netlist for `cycles` clocks. Returns (reads, bind):
       reads = per-cycle MCU-read value (bits ORed from each MCU_DOUT tap);
       bind  = {mcu-cell-name: (declared h<k>, bel AHB bit)} for the bind check.
       stimulus: optional callable(cycle, reads_so_far) -> {MCU_DIN/MCU cell name: 0|1}
       applied to that cell's DIN net for the cycle (an unlisted input holds its previous
       value; every MCU input starts at 0). Without it the sim is stimulus-free, as before.
       probe: optional callable(cycle, value_of_net) invoked after each cycle's combinational
       evaluation, where value_of_net(canonical net name) -> 0|1 (for tracing a design offline).
       ALTA_BRAM9K cells are modelled behaviourally (x18 only; any other width raises)."""
    d = json.load(open(routed_json)) if document is None else document
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
        # nextpnr's JSON writer emits a fresh dummy index (beyond every real net)
        # for a port bit that is connected to nothing; on silicon such an input
        # is undriven and reads HIGH (see the zero-cofactor root cause).
        if x not in nid:
            return "__unconnected__"
        return nid[x]

    # (qnet, fnet, coutnet, init, [in_nets], cinnet, ff_used)
    # A carry slice replaces physical LUT input C with Cin and drives Cout
    # from the low half of the same mask, matching alta_slice.
    cells = []
    dout_bits = {}                 # net -> set of AHB bits (constants may fan out)
    bind = {}                      # MCU_DOUT cell-name -> (declared bit k, bel bit)
    mcu_inputs = {}                # MCU_DIN / MCU cell-name -> DIN net (stimulus targets)
    brams = []                     # behavioural ALTA_BRAM9K instances
    for cn, c in top["cells"].items():
        t = c.get("type")
        if t in ("MCU_DIN", "MCU"):
            din = c["connections"].get("DIN", [])
            if din:
                mcu_inputs[cn] = netname(din[0])
            continue
        if t == "ALTA_BRAM9K":
            brams.append(_bram_model(cn, c, netname))
            continue
        if t == "GENERIC_SLICE" and "PACKER_GND" not in cn:
            I = [netname(n) for n in c["connections"].get("I", [])]
            q = c["connections"].get("Q", [])
            f = c["connections"].get("F", [])
            cin = c["connections"].get("CIN", [])
            cout = c["connections"].get("COUT", [])
            ffu = int(c["parameters"].get("FF_USED", "0"), 2)
            init = int(c["parameters"]["INIT"], 2)
            for k, net in enumerate(I):
                if net == "__unconnected__" and _init_depends_on(init, k, len(I)):
                    raise ValueError(
                        "verify: slice %s input I[%d] is unconnected but INIT %04x depends on it; "
                        "an undriven LUT input reads 1 on silicon, so this netlist is not "
                        "predictable (packer cofactoring missing)" % (cn, k, init))
            cells.append((netname(q[0]) if q else None, netname(f[0]) if f else None,
                          netname(cout[0]) if cout else None, init, I,
                          netname(cin[0]) if cin else None, ffu))
        elif t == "MCU_DOUT":
            bel = c["attributes"].get("NEXTPNR_BEL", "")
            dn = c["connections"].get("DOUT", [])
            bit = hrdata_bit_for_bel(bel)
            if dn and bit is not None:
                dout_bits.setdefault(netname(dn[0]), set()).add(bit)
            mk = re.search(r"h(\d+)", cn)
            if mk and bit is not None:
                bind[cn] = (int(mk.group(1)), bit)
        elif t == "GENERIC_IOB" and cn.endswith(".q"):
            # Physical-PCF probes often expose one diagnostic bit as top-level q instead of through
            # MCU_DOUT. Treat that output-pad input as read bit 0 so the same routed-netlist simulator
            # can validate the post-pack LUT/FF behavior before a hardware run.
            pin = c["connections"].get("I", [])
            if pin:
                dout_bits.setdefault(netname(pin[0]), set()).add(0)

    ff = {qn: 0 for (qn, fn, cout, init, I, cin, ffu) in cells if ffu and qn}
    for bram in brams:
        for net in bram["out_a"] + bram["out_b"]:
            if net:
                ff[net] = 0
    inputs = {net: 0 for net in mcu_inputs.values() if net}

    def val(net, comb):
        if net == "__one__" or net == "__unconnected__":
            return 1
        if net is None:
            return 0
        if net in comb:
            return comb[net]
        return ff.get(net, 0)

    reads = []
    for cycle in range(cycles):
        if stimulus is not None:
            for cell_name, value in stimulus(cycle, reads).items():
                if cell_name not in mcu_inputs:
                    raise KeyError("stimulus names no MCU_DIN/MCU cell %r" % cell_name)
                if mcu_inputs[cell_name]:
                    inputs[mcu_inputs[cell_name]] = int(value) & 1
        comb = dict(inputs)                              # evaluate comb cells (FF_USED=0) to fixpoint
        for _it in range(len(cells) + 3):
            ch = False
            for (qn, fn, cout, init, I, cin, ffu) in cells:
                carry_mode = cin is not None or cout is not None
                a = val(I[0], comb) if len(I) > 0 else 0
                b = val(I[1], comb) if len(I) > 1 else 0
                pin_c = val(cin, comb) if carry_mode else (val(I[2], comb) if len(I) > 2 else 0)
                d_in = val(I[3], comb) if len(I) > 3 else 0
                # A registered slice still exposes its combinational F output.
                # Vendor-topology TFFs use F for observation while Q feeds the
                # direct-D branch, so suppressing F when FF_USED is set makes a
                # valid routed design appear stuck in cycle simulation.
                if fn:
                    o = (init >> (a | (b << 1) | (pin_c << 2) | (d_in << 3))) & 1
                    if comb.get(fn) != o:
                        comb[fn] = o
                        ch = True
                if cout:
                    co = (init >> (a | (b << 1) | (val(cin, comb) << 2))) & 1
                    if comb.get(cout) != co:
                        comb[cout] = co
                        ch = True
            if not ch:
                break
        rv = 0
        for net, bits in dout_bits.items():
            value = val(net, comb)
            for bit in bits:
                rv |= (value << bit)
        reads.append(rv)
        if probe is not None:
            probe(cycle, lambda net: val(net, comb))
        nxt = dict(ff)                                   # clock the FFs
        for (qn, fn, cout, init, I, cin, ffu) in cells:
            if ffu and qn:
                carry_mode = cin is not None or cout is not None
                a = val(I[0], comb) if len(I) > 0 else 0
                b = val(I[1], comb) if len(I) > 1 else 0
                pin_c = val(cin, comb) if carry_mode else (val(I[2], comb) if len(I) > 2 else 0)
                d_in = val(I[3], comb) if len(I) > 3 else 0
                idx = a | (b << 1) | (pin_c << 2) | (d_in << 3)
                nxt[qn] = (init >> idx) & 1
        for bram in brams:
            _bram_clock(bram, lambda net: val(net, comb), nxt)
        ff = nxt
    return reads, bind


def _init_depends_on(init, k, n_inputs):
    """True if the LUT truth table `init` changes with input bit k for any other input value."""
    for idx in range(1 << n_inputs):
        if not idx & (1 << k) and ((init >> idx) & 1) != ((init >> (idx | (1 << k))) & 1):
            return True
    return False


# ---- behavioural ALTA_BRAM9K ------------------------------------------------
# x18 organisation only: 512 words of 18 bits, word = Address[12:4], the low
# four address bits are the default-high suffix.  Unconnected pins take the
# packer's hard default (control blob): We/AsyncReset/AddressStall low, Re/
# ClkEn/ByteEn high.  This is a MODEL for pre-silicon prediction; it is not
# evidence about the BRAM and it refuses widths it does not model.
_BRAM_LOW_DEFAULT = ("WeA", "WeB", "AsyncReset0", "AsyncReset1", "AddressStallA", "AddressStallB")


def _bram_model(name, cell, netname):
    params = cell.get("parameters", {})
    con = cell.get("connections", {})

    def code(key):
        v = params.get(key, "0")
        return int(v, 2) if isinstance(v, str) else int(v)

    for key in ("PORTA_WIDTH", "PORTB_WIDTH"):
        if code(key) != 0:
            raise ValueError("verify: ALTA_BRAM9K %s %s=%s is not modelled (x18 only)"
                             % (name, key, format(code(key), "05b")))
    init = params.get("INIT_VAL", "0")
    init = int(init, 2) if isinstance(init, str) else int(init)
    mem = [(init >> (18 * w)) & 0x3ffff for w in range(512)]

    def nets(port, width):
        # a constant-0 connection reads 0 (netname -> None); an UNCONNECTED
        # (hard-defaulted) bit reads the pin default, so keep them distinct
        bits = con.get(port, [])
        return [netname(b) for b in bits] + ["__unconnected__"] * (width - len(bits))


    def pin(port):
        bits = con.get(port, [])
        if not bits or netname(bits[0]) == "__unconnected__":
            return "__default__"
        return netname(bits[0])
    return {
        "name": name, "mem": mem,
        "outreg_a": code("PORTA_OUTREG"), "outreg_b": code("PORTB_OUTREG"),
        "addr_a": nets("AddressA", 13), "data_a": nets("DataInA", 18),
        "addr_b": nets("AddressB", 13), "data_b": nets("DataInB", 18),
        "out_a": nets("DataOutA", 18), "out_b": nets("DataOutB", 18),
        "ctl": {k: pin(k) for k in ("WeA", "ReA", "ClkEn0", "WeB", "ReB", "ClkEn1")},
        "be_a": nets("ByteEnA", 2), "be_b": nets("ByteEnB", 2),
        "q_a": 0, "q_b": 0, "q_a_reg": 0, "q_b_reg": 0,
    }


def _bram_clock(bram, value, nxt):
    def pinval(port):
        net = bram["ctl"][port]
        if net == "__default__":
            return 0 if port in _BRAM_LOW_DEFAULT else 1
        return value(net)

    def bus(nets, default=1):
        out = 0
        for i, net in enumerate(nets):
            bit = default if net == "__unconnected__" else value(net)
            out |= (bit & 1) << i
        return out

    def port(addr, data, be, we, re, en, q_key, reg_key, outreg, outs):
        # Non-blocking semantics of the vendor-shaped model: a read in the same
        # clock as a write returns the OLD word; the output register takes the
        # previous read value.
        if pinval(en):
            word = (bus(addr) >> 4) & 0x1ff
            previous_q = bram[q_key]
            if pinval(re):
                bram[q_key] = bram["mem"][word]
            if pinval(we):
                d = bus(data, default=0)
                be_v = bus(be)
                cur = bram["mem"][word]
                if be_v & 1:
                    cur = (cur & ~0x1ff) | (d & 0x1ff)
                if be_v & 2:
                    cur = (cur & 0x1ff) | (d & ~0x1ff & 0x3ffff)
                bram["mem"][word] = cur
            bram[reg_key] = previous_q
        shown = bram[reg_key] if outreg else bram[q_key]
        for i, net in enumerate(outs):
            if net and net != "__unconnected__":
                nxt[net] = (shown >> i) & 1

    port(bram["addr_a"], bram["data_a"], bram["be_a"], "WeA", "ReA", "ClkEn0",
         "q_a", "q_a_reg", bram["outreg_a"], bram["out_a"])
    port(bram["addr_b"], bram["data_b"], bram["be_b"], "WeB", "ReB", "ClkEn1",
         "q_b", "q_b_reg", bram["outreg_b"], bram["out_b"])


def summary(routed_json, cycles=96, document=None):
    """Print the read-values a routed design will produce on silicon + the bind check. Returns True if the
    MCU_DOUT bind is sound (h<k> -> AHB bit k). Hardware-free."""
    reads, bind = sim_routed(routed_json, cycles, document=document)
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
