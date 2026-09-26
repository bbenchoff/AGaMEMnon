#!/usr/bin/env python3
"""Offline simulation of the logical model in a routed design.

The model reads `GENERIC_SLICE` INITs, I[0..3]/Q connectivity, FF_USED and
MCU_DOUT-to-AHB binding from nextpnr `--write` JSON. It predicts read values for
the selected stimulus and cycle window. It does not decode the final image or
establish physical routing, clock/reset behavior, electrical timing or silicon
correctness. A model and its encoder can share an incorrect device assumption.

Two uses:
  * `summary(routed_json)` -> the set of read-values the design produces + the MCU_DOUT bind check
    (h<k> must map to AHB bit k; a mismatch is a read-bit-scramble class bug). This is what
    `agamemnon build --verify` prints after routing.
  * `verify(routed_json, observed)` -> compare a nonempty observed value SET to
    the finite model window. SOUND checks set inclusion; COVER reports the
    fraction of modeled values observed. Neither checks sequence, frequency,
    transaction completion or internal state. Missing values do not establish
    sampling aliasing; a mismatch can also reflect model or stimulus differences.

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


def sim_routed(routed_json, cycles=96, document=None, stimulus=None, probe=None,
               bram_probe=None, bram_unconnected_data=0, dead_nets=(), qf_alias=()):
    """Simulate the routed netlist for `cycles` clocks. Returns (reads, bind):
       reads = per-cycle MCU-read value (bits ORed from each MCU_DOUT tap);
       bind  = {mcu-cell-name: (declared h<k>, bel AHB bit)} for the bind check.
       stimulus: optional callable(cycle, reads_so_far) -> {MCU_DIN/MCU cell name: 0|1}
       applied to that cell's DIN net for the cycle (an unlisted input holds its previous
       value; every MCU input starts at 0). Without it the sim is stimulus-free, as before.
       probe: optional callable(cycle, value_of_net) invoked after each cycle's combinational
       evaluation, where value_of_net(canonical net name) -> 0|1 (for tracing a design offline).
       bram_probe: optional callable(cycle, brams) invoked after the clock edge with the
       behavioural ALTA_BRAM9K instances (each carries a `last` dict describing the port
       operations of that edge) for tracing a memory offline.
       bram_unconnected_data: the value an UNCONNECTED DataIn lane presents to a write
       (0 keeps the historical model; 1 models "an undriven fabric input reads 1").
       dead_nets: canonical net names whose every consumer reads 1 (an undriven fabric input
       reads high), for asking which single conduction failure reproduces a board symptom.
       qf_alias: canonical names of REGISTERED nets whose consumers read the driving slice's
       combinational LUT output (F) instead of its register (Q): the value a mesh pip delivers
       when it really reads the slice's OMUX[3z+1] wire although the graph labels it
       OMUX[3z+0]/[3z+2] (a wire the register presents on).
       ALTA_BRAM9K cells are modelled behaviourally in the vendor x18/x9/x4/x2/x1 port
       organisations (x36 raises)."""
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
            carry_mode = bool(cin) or bool(cout)
            for k, net in enumerate(I):
                # A carry slice replaces physical input C (I[2]) with Cin and
                # its D (I[3]) selects the COUT (D=0) / F (D=1) halves of the
                # mask, so unconnected I[2]/I[3] there are by construction.
                if carry_mode and k in (2, 3):
                    continue
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

    dead = set(dead_nets)
    aliased = set(qf_alias)

    def val(net, comb):
        if net == "__one__" or net == "__unconnected__":
            return 1
        if net in dead:
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
                if qn in aliased:
                    o = (init >> (a | (b << 1) | (pin_c << 2) | (d_in << 3))) & 1
                    if comb.get(qn) != o:
                        comb[qn] = o
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
            bram["cycle"] = cycle
            _bram_clock(bram, lambda net: val(net, comb), nxt, bram_unconnected_data)
        ff = nxt
        if bram_probe is not None:
            bram_probe(cycle, brams)
    return reads, bind


def _init_depends_on(init, k, n_inputs):
    """True if the LUT truth table `init` changes with input bit k for any other input value."""
    for idx in range(1 << n_inputs):
        if not idx & (1 << k) and ((init >> idx) & 1) != ((init >> (idx | (1 << k))) & 1):
            return True
    return False


# ---- behavioural ALTA_BRAM9K ------------------------------------------------
# Behavioral port organization, checked against vendor-model mode fixtures.
# Historical activity-only board checks did not independently establish completed
# read transactions for every mode. This model is not silicon qualification.
# The represented memory contains 512 rows of
# 18 bits, row = Address[12:4]; the low four address bits (`blk`) select the
# sub-word window of a narrow port.  A narrow WRITE lands the address-selected
# window (x9 halves 0/9; x4 windows 0,4,9,13; x2 windows 0,2,4,6,9,11,13,15; x1 the
# 16 non-parity lanes) from data the fabric must present on that window; a narrow
# READ extracts the window and presents it on the low DataOut lanes with the rest
# high (x9 {1, w[7:0], 1, w[8], 7'h7f}; x4 {11'h7ff, w, 3'b111}; x2 {15'h7fff, w, 1};
# x1 {17'h1ffff, w}).  Unconnected pins take the packer's hard default (control
# blob): We/AsyncReset/AddressStall low, Re/ClkEn/ByteEn high; an unconnected
# address bit reads high.  This is a MODEL for pre-silicon prediction; it is not
# evidence about the BRAM and it refuses widths it does not model (x36).
_BRAM_LOW_DEFAULT = ("WeA", "WeB", "AsyncReset0", "AsyncReset1", "AddressStallA", "AddressStallB")
_BRAM_WIDTH_BITS = {0b00000: 18, 0b01000: 9, 0b01100: 4, 0b01110: 2, 0b01111: 1}


def _bram_model(name, cell, netname):
    params = cell.get("parameters", {})
    con = cell.get("connections", {})

    def code(key):
        v = params.get(key, "0")
        return int(v, 2) if isinstance(v, str) else int(v)

    widths = {}
    for key in ("PORTA_WIDTH", "PORTB_WIDTH"):
        w = code(key)
        if w not in _BRAM_WIDTH_BITS:
            raise ValueError("verify: ALTA_BRAM9K %s %s=%s is not modelled (x18/x9/x4/x2/x1 only)"
                             % (name, key, format(w, "05b")))
        widths[key] = w
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
        "width_a": widths["PORTA_WIDTH"], "width_b": widths["PORTB_WIDTH"],
        "outreg_a": code("PORTA_OUTREG"), "outreg_b": code("PORTB_OUTREG"),
        "addr_a": nets("AddressA", 13), "data_a": nets("DataInA", 18),
        "addr_b": nets("AddressB", 13), "data_b": nets("DataInB", 18),
        "out_a": nets("DataOutA", 18), "out_b": nets("DataOutB", 18),
        "ctl": {k: pin(k) for k in ("WeA", "ReA", "ClkEn0", "WeB", "ReB", "ClkEn1")},
        "be_a": nets("ByteEnA", 2), "be_b": nets("ByteEnB", 2),
        "q_a": 0, "q_b": 0, "blk_a": 0, "blk_b": 0, "q_a_reg": 0, "q_b_reg": 0,
        "cycle": -1, "last": {},
    }


def _bram_write_mask(width, blk, be):
    """The 18-bit lane mask a write with sub-word address `blk` lands on (vendor maskA_*)."""
    be18 = (0x1ff if be & 1 else 0) | (0x3fe00 if be & 2 else 0)
    if width == 0b00000:
        return be18
    if width == 0b01000:
        return be18 & (0x3fe00 if blk & 8 else 0x1ff)
    hi = (blk >> 3) & 1
    if width == 0b01100:
        return be18 & (0xf << (((blk >> 2) & 3) * 4 + hi))
    if width == 0b01110:
        return be18 & (0x3 << (((blk >> 1) & 7) * 2 + hi))
    return be18 & (0x1 << ((blk & 0xf) + hi))


def _bram_read_present(width, word, blk):
    """What the 18 DataOut lanes show for row `word` read with sub-word address `blk`."""
    if width == 0b00000:
        return word
    if width == 0b01000:
        v = (word >> 9) & 0x1ff if blk & 8 else word & 0x1ff
        return (1 << 17) | ((v & 0xff) << 9) | (1 << 8) | (((v >> 8) & 1) << 7) | 0x7f
    x16 = ((word >> 9) & 0xff) << 8 | (word & 0xff)
    if width == 0b01100:
        v = (x16 >> (((blk >> 2) & 3) * 4)) & 0xf
        return (0x7ff << 7) | (v << 3) | 0x7
    if width == 0b01110:
        v = (x16 >> (((blk >> 1) & 7) * 2)) & 0x3
        return (0x7fff << 3) | (v << 1) | 0x1
    v = (x16 >> (blk & 0xf)) & 0x1
    return (0x1ffff << 1) | v


def _bram_clock(bram, value, nxt, unconnected_data=0):
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

    def port(tag, width, addr, data, be, we, re, en, q_key, blk_key, reg_key, outreg, outs):
        # Non-blocking semantics of the vendor-shaped model: a read in the same
        # clock as a write returns the OLD word; the output register takes the
        # previous presented value.
        rec = {"en": pinval(en), "we": pinval(we), "re": pinval(re)}
        if rec["en"]:
            a = bus(addr)
            row, blk = (a >> 4) & 0x1ff, a & 0xf
            previous = _bram_read_present(width, bram[q_key], bram[blk_key])
            rec.update(row=row, blk=blk, old=bram["mem"][row])
            if rec["re"]:
                bram[q_key] = bram["mem"][row]
                bram[blk_key] = blk
            if rec["we"]:
                d = bus(data, default=unconnected_data)
                mask = _bram_write_mask(width, blk, bus(be))
                bram["mem"][row] = (bram["mem"][row] & ~mask & 0x3ffff) | (d & mask)
                rec.update(din=d, mask=mask, new=bram["mem"][row])
            bram[reg_key] = previous
        shown = bram[reg_key] if outreg else _bram_read_present(width, bram[q_key], bram[blk_key])
        rec["out"] = shown
        bram["last"][tag] = rec
        for i, net in enumerate(outs):
            if net and net != "__unconnected__":
                nxt[net] = (shown >> i) & 1

    port("A", bram["width_a"], bram["addr_a"], bram["data_a"], bram["be_a"], "WeA", "ReA", "ClkEn0",
         "q_a", "blk_a", "q_a_reg", bram["outreg_a"], bram["out_a"])
    port("B", bram["width_b"], bram["addr_b"], bram["data_b"], bram["be_b"], "WeB", "ReB", "ClkEn1",
         "q_b", "blk_b", "q_b_reg", bram["outreg_b"], bram["out_b"])


def load_stimulus(path):
    """Read a stimulus file: {"schema": 1, "events": [[cycle, {"mcu_cell": 0|1, ...}], ...]}.
    Returns the callable sim_routed() expects. Cycles are absolute; an input holds its last value."""
    doc = json.load(open(path, encoding="utf-8"))
    if doc.get("schema") != 1 or not isinstance(doc.get("events"), list):
        raise ValueError("stimulus %s: expected {\"schema\": 1, \"events\": [[cycle, {cell: bit}], ...]}" % path)
    by_cycle = {}
    for item in doc["events"]:
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict)):
            raise ValueError("stimulus %s: malformed event %r" % (path, item))
        by_cycle.setdefault(int(item[0]), {}).update({str(k): int(v) & 1 for k, v in item[1].items()})
    return lambda cycle, reads: by_cycle.get(cycle, {})


def _canonical_net_names(document, names):
    """Map user-facing net names to the canonical name sim_routed() keys values by."""
    top = document["modules"]["top"]
    nid = {}
    for nm, ni in top["netnames"].items():
        for b in ni.get("bits", []):
            nid[b] = nm
    out = {}
    for name in names:
        ni = top["netnames"].get(name)
        if ni is None or not ni.get("bits"):
            raise KeyError("trace: no net named %r in the routed JSON" % name)
        out[name] = nid[ni["bits"][0]]
    return out


def _run_length(values):
    parts, prev, count = [], None, 0
    for v in values:
        if v == prev:
            count += 1
        else:
            if prev is not None:
                parts.append("%dx%d" % (prev, count))
            prev, count = v, 1
    if prev is not None:
        parts.append("%dx%d" % (prev, count))
    return " ".join(parts)


def summary(routed_json, cycles=96, document=None, stimulus=None, trace=None):
    """Print the read-values predicted by the routed model + the bind check. Returns True if the
    MCU_DOUT bind is sound (h<k> -> AHB bit k). Hardware-free. With `stimulus` (see load_stimulus) the
    per-cycle read sequence is printed run-length encoded; `trace` names nets whose values are printed
    whenever one of them changes."""
    if document is None:
        document = json.load(open(routed_json, encoding="utf-8"))
    rows = []
    probe = None
    if trace:
        canon = _canonical_net_names(document, trace)
        last = [None]

        def probe(cycle, value):
            vals = tuple(value(canon[t]) for t in trace)
            if vals != last[0]:
                rows.append((cycle, vals))
                last[0] = vals
    reads, bind = sim_routed(routed_json, cycles, document=document, stimulus=stimulus, probe=probe)
    simset = sorted(set(reads))
    bind_ok = all(k == bit for (k, bit) in bind.values())
    nff = "?"
    print("verify: routed-netlist sim over %d cycles%s" % (cycles, " with stimulus" if stimulus else ""))
    print("  MCU read-values predicted by this model (AHB 0x60000000): %s" % (simset,))
    if stimulus is not None:
        print("  read sequence (value x cycles): %s" % _run_length(reads))
    for cycle, vals in rows:
        print("  trace @%-6d %s" % (cycle, " ".join("%s=%d" % (t, v) for t, v in zip(trace, vals))))
    if bind:
        print("  MCU_DOUT bind (h<k> -> AHB bit k): %s %s"
              % ("OK" if bind_ok else "SCRAMBLED", {c: b for c, (k, b) in bind.items()}))
        if len(simset) > 2:
            print("  => multi-bit sequential: %d distinct read-values (a stuck/toggle output could reach <=2)"
                  % len(simset))
    else:
        print("  (no MCU_DOUT readout taps in this design -- nothing to read over AHB)")
    return bind_ok


def verify(routed_json, observed, cycles=96, stimulus=None):
    """Check nonempty observed values against the finite model window and binding.

    True means set consistency only, not hardware or sequence qualification.
    """
    obs = set(observed)
    if not obs:
        print("VERDICT: NO_OBSERVATIONS (at least one measured value is required)")
        return False
    reads, bind = sim_routed(routed_json, cycles, stimulus=stimulus)
    simset = set(reads)
    bind_ok = all(k == bit for (k, bit) in bind.values())
    spurious = obs - simset
    cover = len(obs & simset) / max(1, len(simset))
    print("routed-netlist model values in this window:", sorted(simset))
    print("silicon observed values:            ", sorted(obs))
    print("BIND  (MCU_DOUT h<k>->AHB bit k): %s %s"
          % ("OK" if bind_ok else "SCRAMBLED", {c: b for c, (k, b) in bind.items()}))
    print("SOUND (observed subset of model window): %s%s"
          % ("PASS" if not spurious else "FAIL", "" if not spurious else "  spurious=%s" % sorted(spurious)))
    print("COVER (modeled values observed): %.0f%% (%d/%d)  missing=%s"
          % (100 * cover, len(obs & simset), len(simset), sorted(simset - obs)))
    ok = bind_ok and not spurious
    print("VERDICT:", "CONSISTENT_WITH_MODEL" if ok else "MISMATCH")
    print("  Scope: value-set consistency only; sequence, timing and hardware correctness are unqualified.")
    return ok


if __name__ == "__main__":
    rj = sys.argv[1]
    cyc = int(sys.argv[3]) if len(sys.argv) > 3 else 96
    if len(sys.argv) > 2 and sys.argv[2]:
        sys.exit(0 if verify(rj, [int(x) for x in sys.argv[2].split(",")], cyc) else 1)
    else:
        sys.exit(0 if summary(rj, cyc) else 1)
