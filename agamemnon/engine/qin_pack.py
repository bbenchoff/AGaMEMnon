#!/usr/bin/env python3
"""Pre-nextpnr JSON pass for registered feedback and characterized input pins.

The vendor TFF routes a slice's registered Q explicitly from ``OMUX[3z+1]``
back to the same slice's D input, ``IMUX[4z+3]``. The older open model moved
self-feedback to C/I[2] and selected the internal Qin mux; silicon ablation at
X1Y4 slice 2 showed that the vendor direct-D selector is necessary while the
alternate Q-to-C arc remains unproven.

This pass therefore moves every LUT/DFF self-feedback input to index 3 and
permutes INIT with it. Later input-packing passes reserve that slot. The
operation is idempotent and leaves combinational LUTs unchanged.
"""
import json, sys


def expand_uniform_bram_init(json_path):
    """Make a uniformly initialized narrow BRAM physical INIT deterministic.

    memory_libmap leaves unused physical lanes as ``x`` for narrow memories.
    The x2 techmap repeats data onto physical lanes at runtime, but previously
    passed this sparse INIT through unchanged.  For an all-zero or all-one
    logical memory the physical value is unambiguous: fill every ``x`` with the
    sole known value.  Mixed/patterned initializers are left untouched until
    their full narrow-lane layout is decoded.  Returns the number of bits filled.
    """
    design = json.load(open(json_path))
    changed = 0
    for module in design.get("modules", {}).values():
        for cell in module.get("cells", {}).values():
            if cell.get("type") != "ALTA_BRAM9K":
                continue
            parameters = cell.get("parameters", {})
            init = parameters.get("INIT_VAL")
            if not isinstance(init, str) or "x" not in init.lower():
                continue
            known = {bit for bit in init.lower() if bit in "01"}
            if len(known) != 1:
                continue
            value = next(iter(known))
            count = init.lower().count("x")
            parameters["INIT_VAL"] = "".join(value if bit.lower() == "x" else bit
                                                for bit in init)
            changed += count
    if changed:
        json.dump(design, open(json_path, "w"))
    return changed


def unwrap_bram_old_write_inputs(json_path):
    """Remove Yosys ``emulate_read_first`` DFFs from BRAM write inputs.

    The silicon-qualified x2 OLD-mode SERV footprint drives AddressA, DataInA,
    and WeA directly from LUT F. Current Yosys can insert cycle-shifting input
    DFFs to emulate that mode even though the hard macro already implements it.
    Bypass only structurally named emulation nets whose DFF shares Clk0, and
    only for a uniform physical initializer.  That is the source-built surface
    qualified on silicon.  Mixed/patterned initializers retain Yosys's original
    register topology because direct write drivers can otherwise acquire more
    hard-BRAM terminals than one qualified BEL can reach.  Remove a bypassed
    DFF only when no cell input still consumes its Q.
    """
    design = json.load(open(json_path))
    changed = 0
    dirty = False
    for module in design.get("modules", {}).values():
        cells = module.get("cells", {})
        emulated = set()
        for name, net in module.get("netnames", {}).items():
            if "emulate_read_first" in name:
                emulated.update(bit for bit in net.get("bits", [])
                                if isinstance(bit, int))

        dff_by_q = {}
        for name, cell in cells.items():
            if cell.get("type") != "DFF":
                continue
            conns = cell.get("connections", {})
            q, d, clk = conns.get("Q", []), conns.get("D", []), conns.get("CLK", [])
            if len(q) == len(d) == len(clk) == 1:
                dff_by_q[q[0]] = (name, d[0], clk[0])

        candidates = set()
        for cell in cells.values():
            if cell.get("type") != "ALTA_BRAM9K":
                continue
            init = cell.get("parameters", {}).get("INIT_VAL")
            if (not isinstance(init, str) or len(init) != 9216 or
                    set(init.lower()) not in ({"0"}, {"1"})):
                continue
            conns = cell.get("connections", {})
            clk = conns.get("Clk0", [])
            if len(clk) != 1:
                continue
            for port in ("AddressA", "DataInA", "WeA", "ByteEnA"):
                bits = conns.get(port, [])
                for index, bit in enumerate(bits):
                    item = dff_by_q.get(bit)
                    if bit not in emulated or item is None or item[2] != clk[0]:
                        continue
                    candidates.add(item[0])
                    bits[index] = item[1]
                    changed += 1
                    dirty = True

        for name in candidates:
            cell = cells.get(name)
            if cell is None:
                continue
            q = cell.get("connections", {}).get("Q", [None])[0]
            used = any(
                q in other.get("connections", {}).get(port, [])
                for other_name, other in cells.items() if other_name != name
                for port, direction in other.get("port_directions", {}).items()
                if direction == "input"
            )
            if not used:
                del cells[name]
                dirty = True

    if dirty:
        json.dump(design, open(json_path, "w"))
    return changed


def _swapbits(i, p, q):
    bp = (i >> p) & 1; bq = (i >> q) & 1
    if bp == bq:
        return i
    return i ^ ((1 << p) | (1 << q))


def _perm_init(init_str, p, q):
    """INIT is an MSB-first bit string (char[0] = INIT[N-1]); swap input positions p,q."""
    n = len(init_str)
    old = [int(init_str[n - 1 - i]) for i in range(n)]          # old[i] indexed by truth-table row i
    new = [old[_swapbits(i, p, q)] for i in range(n)]
    return "".join(str(new[i]) for i in range(n - 1, -1, -1))   # back to MSB-first


def wrap_pad_dff_inputs(json_path):
    """Insert an identity LUT before selected direct-to-DFF inputs.

    The generic DFF packer otherwise hardwires D onto slice input I[0].  Qualified
    L48 pad paths enter registered slices on input D/I[3].  Making the identity
    LUT explicit lets ``permute_pad_inputs_high`` move the physical input to I[3]
    while the normal nextpnr LUT+DFF packer still performs the final fusion.
    A dedicated-carry COUT endpoint has the same issue: wrap it so
    ``permute_reads_to_inputD`` can select the qualified I[3] corridor. SUM is
    deliberately excluded because its DFF is fused into the carry slice itself.
    """
    d = json.load(open(json_path)); changed = 0
    for mod in d.get("modules", {}).values():
        cells = mod.get("cells", {})
        physical_pad_nets = set()
        wrapped_nets = set()
        max_bit = 1
        for c in cells.values():
            for conn in c.get("connections", {}).values():
                max_bit = max([max_bit] + [n for n in conn if isinstance(n, int)])
            if c.get("type") == "GENERIC_IOB":
                physical_pad_nets.update(n for n in c.get("connections", {}).get("O", [])
                                         if isinstance(n, int))
            if c.get("type") == "AG32_FA":
                wrapped_nets.update(n for n in c.get("connections", {}).get("COUT", [])
                                    if isinstance(n, int))
        wrapped_nets.update(physical_pad_nets)
        dffs_by_d = {}
        for name, c in cells.items():
            if c.get("type") == "DFF":
                dn = c.get("connections", {}).get("D", [])
                if dn:
                    dffs_by_d.setdefault(dn[0], []).append((name, c))
        next_bit = max_bit + 1
        additions = {}

        # ABC emits an identity LUT before the first DFF of the usual two-flop
        # synchronizer. Mark that stage and make the follower's input LUT
        # explicit so the uarch can select and lock the silicon-positive
        # same-tile Q-to-input path.
        for lut_name, lut in list(cells.items()):
            if lut.get("type") != "LUT":
                continue
            inputs = lut.get("connections", {}).get("I", [])
            pads = [net for net in inputs if net in physical_pad_nets]
            qn = lut.get("connections", {}).get("Q", [])
            first = dffs_by_d.get(qn[0], []) if len(pads) == 1 and qn else []
            if len(first) != 1:
                continue
            group = "pad_%s" % pads[0]
            lut.setdefault("attributes", {}).update({
                "agamemnon_pad_sync_stage": "stage1",
                "agamemnon_pad_sync_group": group,
            })
            first_q = first[0][1].get("connections", {}).get("Q", [])
            followers = dffs_by_d.get(first_q[0], []) if first_q else []
            if len(followers) != 1:
                continue
            follower_name, follower = followers[0]
            follower_out = next_bit; next_bit += 1
            additions["$agamemnon$pad_sync_lut$" + follower_name] = {
                "type": "LUT",
                "parameters": {
                    "INIT": "1010101010101010",
                    "K": "00000000000000000000000000000100",
                },
                "attributes": {
                    "agamemnon_pad_sync_stage": "stage2",
                    "agamemnon_pad_sync_group": group,
                },
                "port_directions": {"I": "input", "Q": "output"},
                "connections": {"I": [first_q[0], "0", "0", "0"],
                                "Q": [follower_out]},
            }
            follower["connections"]["D"] = [follower_out]
            changed += 1
        for name, c in list(cells.items()):
            if c.get("type") != "DFF":
                continue
            dn = c.get("connections", {}).get("D", [])
            if not dn or dn[0] not in wrapped_nets:
                continue
            out = next_bit; next_bit += 1
            lut_name = "$agamemnon$pad_dff_lut$" + name
            additions[lut_name] = {
                "type": "LUT",
                "parameters": {
                    "INIT": "1010101010101010",  # identity of I[0]
                    "K": "00000000000000000000000000000100",
                },
                "attributes": {"agamemnon_registered_pad_input": "1"},
                "port_directions": {"I": "input", "Q": "output"},
                "connections": {"I": [dn[0], "0", "0", "0"], "Q": [out]},
            }
            c["connections"]["D"] = [out]
            changed += 1
        cells.update(additions)
    if changed:
        json.dump(d, open(json_path, "w"))
    return changed


def permute_selffb_to_inputD(json_path, pin=3):
    """Move registered self-feedback to direct D/I[3].

    Returns the number of LUT input permutations. Every detected feedback LUT
    is tagged even when it was already on D so downstream diagnostics can
    distinguish the characterized lowering from an accidental input choice.
    """
    d = json.load(open(json_path))
    changed = 0
    dirty = False
    feedback_luts = []
    for mod in d.get("modules", {}).values():
        cells = mod.get("cells", {})
        # DFF.D net -> DFF.Q net (the FF that a LUT output feeds; its Q is the feedback signal)
        dff_q_by_d = {}
        for c in cells.values():
            if c.get("type") != "DFF":
                continue
            dn = c["connections"].get("D", []); qn = c["connections"].get("Q", [])
            if dn and qn:
                dff_q_by_d[dn[0]] = qn[0]
        for c in cells.values():
            if c.get("type") != "LUT":
                continue
            q = c["connections"].get("Q", [])
            I = c["connections"].get("I", [])
            if not q:
                continue
            fb = dff_q_by_d.get(q[0])          # this LUT drives a DFF; fb = that DFF's Q
            if fb is None:
                continue
            ks = [k for k, net in enumerate(I) if net == fb]
            if not ks:
                continue
            attrs = c.setdefault("attributes", {})
            feedback_luts.append((mod, c, q[0], fb))
            if attrs.get("agamemnon_direct_d_feedback") != "1":
                attrs["agamemnon_direct_d_feedback"] = "1"
                attrs.setdefault("agamemnon_direct_d_origin", "qin-pack-inferred-own-q")
                dirty = True
            if pin not in ks:
                k = ks[0]
                I[k], I[pin] = I[pin], I[k]
                c["parameters"]["INIT"] = _perm_init(c["parameters"]["INIT"], k, pin)
                changed += 1
                dirty = True
    # One direct-D cell has a silicon-qualified open-flow home whose distinct
    # F/Q presentations and HRDATA[0] corridor were exercised together. Keep
    # this deliberately narrow: multiple feedback cells remain unplaced and
    # fail closed until a multi-site pool is qualified.
    if len(feedback_luts) == 1:
        mod, feedback_lut, next_state_net, registered_q_net = feedback_luts[0]
        attrs = feedback_lut.setdefault("attributes", {})
        if "BEL" not in attrs:
            attrs["BEL"] = "X14Y11_SLICE7"
            dirty = True
        # The qualified vendor topology keeps registered Q on the local
        # feedback-only OMUX and presents LUT F (the next-state value) on the
        # routable mesh. For the single supported feedback cell, move external
        # input consumers of Q to F while leaving the LUT's own feedback input
        # on Q. This is the TFF's phase-complement observation branch.
        rewired = 0
        for other in mod.get("cells", {}).values():
            if other is feedback_lut:
                continue
            directions = other.get("port_directions", {})
            for port, nets in other.get("connections", {}).items():
                if directions.get(port) != "input":
                    continue
                for index, net in enumerate(nets):
                    if net == registered_q_net:
                        nets[index] = next_state_net
                        rewired += 1
        if rewired:
            attrs["agamemnon_direct_d_observe_f"] = "1"
            dirty = True
    if dirty:
        json.dump(d, open(json_path, "w"))
    return changed


def permute_reads_to_inputD(json_path, pin=3):
    """Move a single CELL-TO-CELL read (a LUT input driven by ANOTHER cell's output, not self, not const)
    onto input index `pin` (=3 = input D). The vendor routes cell-to-cell reads to IMUX offset-3 targets
    (IMUX07/11/15) which CONDUCT; our default lands them on offset-0 (dead pairs). Since I[i]=IMUX[4z+i],
    putting the read on I[3] lands it on the conducting offset-3 IMUX target -- a permutation fix, not a
    bel remodel. Permutes the LUT INIT to match. Skips LUTs with >1 cell-to-cell read (need the full
    conducting-pair map). Idempotent. Returns count permuted."""
    d = json.load(open(json_path)); changed = 0
    for mod in d.get("modules", {}).values():
        cells = mod.get("cells", {})
        outnet = {}                                   # net -> producing cell
        for cn, c in cells.items():
            # Ordinary mapped cells drive Q. Explicit dedicated-carry cells
            # drive SUM/COUT; their endpoint consumers need the same proven
            # input-D permutation as LUT/DFF reads.
            for port in ("Q", "SUM", "COUT"):
                nets = c["connections"].get(port, [])
                if nets:
                    outnet[nets[0]] = cn
        dff_q_by_d = {}
        for c in cells.values():
            if c.get("type") == "DFF":
                dn = c["connections"].get("D", []); qn = c["connections"].get("Q", [])
                if dn and qn: dff_q_by_d[dn[0]] = qn[0]
        for c in cells.values():
            if c.get("type") != "LUT": continue
            q = c["connections"].get("Q", []); I = c["connections"].get("I", [])
            selfnet = dff_q_by_d.get(q[0]) if q else None
            # D/I[3] belongs to the characterized direct self-feedback branch.
            # Do not let a second cell-to-cell read displace it.
            if selfnet is not None and selfnet in I:
                continue
            reads = [k for k, net in enumerate(I)
                     if isinstance(net, int) and net != selfnet and net in outnet]
            if len(reads) == 1 and reads[0] != pin and pin < len(I):
                k = reads[0]
                I[k], I[pin] = I[pin], I[k]
                c["parameters"]["INIT"] = _perm_init(c["parameters"]["INIT"], k, pin)
                changed += 1
    if changed:
        json.dump(d, open(json_path, "w"))
    return changed


def permute_pad_inputs_high(json_path):
    """Pack LUT inputs driven directly by top-level IOBs onto the highest physical input pins.

    Vendor routing consistently uses IMUX2/3 for a two-pad combinational LUT; IMUX0/1 on the same
    slice can be present in the graph yet nonconducting. Preserve the logical input order and permute
    INIT alongside each swap. Four-input LUTs already occupy every pin and are unchanged.
    """
    d = json.load(open(json_path)); changed = 0
    for mod in d.get("modules", {}).values():
        cells = mod.get("cells", {})
        pad_nets = set()
        dff_q_by_d = {}
        for c in cells.values():
            if c.get("type") == "GENERIC_IOB":
                pad_nets.update(n for n in c.get("connections", {}).get("O", []) if isinstance(n, int))
            elif c.get("type") == "DFF":
                dn = c.get("connections", {}).get("D", [])
                qn = c.get("connections", {}).get("Q", [])
                if dn and qn:
                    dff_q_by_d[dn[0]] = qn[0]
        for c in cells.values():
            if c.get("type") != "LUT":
                continue
            I = c.get("connections", {}).get("I", [])
            original = [(k, net) for k, net in enumerate(I) if net in pad_nets]
            if not original or len(original) >= len(I):
                continue
            q = c.get("connections", {}).get("Q", [])
            selfnet = dff_q_by_d.get(q[0]) if q else None
            reserved = {I.index(selfnet)} if selfnet in I else set()
            targets = [k for k in reversed(range(len(I))) if k not in reserved]
            targets = sorted(targets[:len(original)])
            for (_old, net), target in zip(original, targets):
                current = I.index(net)
                if current == target:
                    continue
                I[current], I[target] = I[target], I[current]
                c["parameters"]["INIT"] = _perm_init(c["parameters"]["INIT"], current, target)
                changed += 1
    if changed:
        json.dump(d, open(json_path, "w"))
    return changed


if __name__ == "__main__":
    i = expand_uniform_bram_init(sys.argv[1])
    b = unwrap_bram_old_write_inputs(sys.argv[1])
    w = wrap_pad_dff_inputs(sys.argv[1])
    n = permute_selffb_to_inputD(sys.argv[1])
    m = permute_reads_to_inputD(sys.argv[1])
    p = permute_pad_inputs_high(sys.argv[1])
    print("qin_pack: filled %d uniform narrow-BRAM INIT bit(s), bypassed %d BRAM "
          "OLD-mode input emulation bit(s), wrapped %d "
          "registered pad input(s), permuted %d self-feedback -> I[3], %d cell-to-cell "
          "reads -> I[3], %d direct-pad input move(s) -> high pins" %
          (i, b, w, n, m, p))
