#!/usr/bin/env python3
"""Pre-nextpnr JSON pass for the Qin self-feedback model.

The AGRV2K slice feeds a registered cell's own FF-Q back to its LUT via the INTERNAL FeedbackMux, and
that internal path lands ONLY on the C LUT input (pinC = INIT weight-4 bit = logical input index 2).
nextpnr-generic does NOT permute LUT inputs, and abc puts the self-feedback on input I[0]. So without
help the feedback sink is I[0] (IMUX[4z+0]) and the internal Qin pip (arch.py 4d: OMUX[3z+2]->IMUX[4z+2])
is unusable -> nextpnr routes the feedback through the dead fabric mesh -> counter-freeze.

This pass rewrites the (pre-pack) synth JSON: for every LUT whose input is its own eventual FF-Q
(LUT.Q -> DFF.D, DFF.Q -> LUT.I[k]), it moves that feedback input to index 2 (pinC) and permutes the
LUT INIT to match. Then the feedback sinks on I[2]=IMUX[4z+2], the Qin pip carries it internally, and
bitgen emits CFG_LUTCMUX[2z]=1. Idempotent (a no-op once the feedback is already at I[2]).
"""
import json, sys


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


def permute_selffb_to_pinC(json_path, pin=2):
    """Rewrite json_path in place. Returns the number of LUTs permuted."""
    d = json.load(open(json_path))
    changed = 0
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
            if not ks or pin in ks:            # not fed back, or already on pinC -> nothing to do
                continue
            k = ks[0]
            I[k], I[pin] = I[pin], I[k]
            c["parameters"]["INIT"] = _perm_init(c["parameters"]["INIT"], k, pin)
            changed += 1
    if changed:
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
        outnet = {}                                   # net -> producing cell (Q output of DFF or LUT)
        for cn, c in cells.items():
            qn = c["connections"].get("Q", [])
            if qn: outnet[qn[0]] = cn
        dff_q_by_d = {}
        for c in cells.values():
            if c.get("type") == "DFF":
                dn = c["connections"].get("D", []); qn = c["connections"].get("Q", [])
                if dn and qn: dff_q_by_d[dn[0]] = qn[0]
        for c in cells.values():
            if c.get("type") != "LUT": continue
            q = c["connections"].get("Q", []); I = c["connections"].get("I", [])
            selfnet = dff_q_by_d.get(q[0]) if q else None
            reads = [k for k, net in enumerate(I)
                     if isinstance(net, int) and net != selfnet and net in outnet and k != 2]
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
        for c in cells.values():
            if c.get("type") == "GENERIC_IOB":
                pad_nets.update(n for n in c.get("connections", {}).get("O", []) if isinstance(n, int))
        for c in cells.values():
            if c.get("type") != "LUT":
                continue
            I = c.get("connections", {}).get("I", [])
            original = [(k, net) for k, net in enumerate(I) if net in pad_nets]
            if not original or len(original) >= len(I):
                continue
            targets = list(range(len(I) - len(original), len(I)))
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
    n = permute_selffb_to_pinC(sys.argv[1])
    m = permute_reads_to_inputD(sys.argv[1])
    p = permute_pad_inputs_high(sys.argv[1])
    print("qin_pack: permuted %d self-feedback -> I[2], %d cell-to-cell reads -> I[3], "
          "%d direct-pad input move(s) -> high pins" % (n, m, p))
