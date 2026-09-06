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
import csv
import json
import os
import sys


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
    """Experimental transform removing ``emulate_read_first`` input DFFs.

    The silicon-qualified x2 OLD-mode SERV footprint drives AddressA, DataInA,
    and WeA directly from LUT F. Current Yosys can insert cycle-shifting input
    DFFs to emulate that mode even though the hard macro already implements it.
    Bypass only structurally named emulation nets whose DFF shares Clk0, and
    only for a uniform physical initializer.  That is the source-built surface
    once appeared qualified through a wrapper-visible readback. Direct hard-
    macro probes later showed that neither the all-one/write-zero nor the
    all-zero/write-one case changed the BRAM: the wrapper emulation path had
    manufactured the apparent result. This helper remains for reproducing the
    investigation, but the production ``__main__`` path does not call it.
    Mixed/patterned initializers retain Yosys's original
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


def split_shared_qualified_bram_inputs(json_path):
    """Give independently source-qualified BRAM terminals distinct drivers.

    Yosys can reuse one signal for multiple hard-block inputs (for example an
    address bit may also be write data).  The release packer has independently
    qualified source BELs for a bounded set of BRAM terminals.  If two such
    terminals require different BELs, one shared driver cannot satisfy both.
    Insert an identity LUT on every constrained use after the first; this
    preserves the logical net while giving placement one source cell per
    terminal instead of weakening either measured source constraint.
    """
    design = json.load(open(json_path))
    changed = 0
    for module in design.get("modules", {}).values():
        cells = module.get("cells", {})
        max_bit = max(
            [1] + [bit for cell in cells.values()
                   for bits in cell.get("connections", {}).values()
                   for bit in bits if isinstance(bit, int)]
        )
        uses = {}
        for cell_name, cell in sorted(cells.items()):
            if cell.get("type") != "ALTA_BRAM9K":
                continue
            connections = cell.get("connections", {})
            constrained = (
                [("AddressA", index) for index in range(3, 11)] +
                [("AddressB", index) for index in range(13)] +
                [("DataInA", index) for index in range(2)] +
                [("WeA", 0), ("ClkEn1", 0)]
            )
            for port, index in constrained:
                bits = connections.get(port, [])
                if index < len(bits) and isinstance(bits[index], int):
                    uses.setdefault(bits[index], []).append(
                        (cell_name, port, index, bits)
                    )

        additions = {}
        next_bit = max_bit + 1
        for source_bit, terminals in sorted(uses.items()):
            if len(terminals) < 2:
                continue
            for ordinal, (cell_name, port, index, bits) in enumerate(terminals[1:], 1):
                output_bit = next_bit
                next_bit += 1
                name = "$agamemnon$bram_terminal_buffer$%d" % changed
                additions[name] = {
                    "type": "LUT",
                    "parameters": {
                        "INIT": "1010101010101010",
                        "K": "00000000000000000000000000000100",
                    },
                    "attributes": {
                        "agamemnon_bram_terminal_buffer": "1",
                        "agamemnon_bram_terminal": "%s.%s[%d]" %
                            (cell_name, port, index),
                    },
                    "port_directions": {"I": "input", "Q": "output"},
                    "connections": {"I": [source_bit, "0", "0", "0"],
                                    "Q": [output_bit]},
                }
                bits[index] = output_bit
                changed += 1
        cells.update(additions)
    if changed:
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


def lower_local_qin_feedback(json_path):
    """Preserve registered observations and place internal own-Q feedback on C.

    The internal feedback selector replaces LUT axis I[2]. It is independent
    of the ordinary routed D input. This lowering changes only input order and
    INIT, retaining both the DFF Q net and every external reader on that net.
    Explicit legacy direct-D footprints remain on their checkpoint path.
    """
    data = json.load(open(json_path))
    count = 0
    for module in data.get("modules", {}).values():
        cells = module.get("cells", {})
        occupied_bits = [bit for cell in cells.values() for bits in cell.get("connections", {}).values()
                         for bit in bits if type(bit) is int]
        occupied_bits += [bit for group in (module.get("netnames", {}), module.get("ports", {}))
                          for item in group.values() for bit in item.get("bits", []) if type(bit) is int]
        next_bit = max(occupied_bits, default=0) + 1
        additions = {}
        by_d = {}
        for cell in cells.values():
            if cell.get("type") == "DFF" and cell["connections"].get("D"):
                by_d.setdefault(cell["connections"]["D"][0], []).append(cell)
        for cell in cells.values():
            if cell.get("type") != "LUT":
                continue
            attrs = cell.setdefault("attributes", {})
            if "agamemnon_direct_d_feedback" in attrs:
                continue
            output = cell["connections"].get("Q", [])
            attached = by_d.get(output[0], []) if output else []
            if len(attached) != 1:
                continue
            feedback = attached[0]["connections"].get("Q", [])
            inputs = cell["connections"].get("I", [])
            if not feedback or feedback[0] not in inputs:
                continue
            if len(inputs) != 4:
                raise SystemExit("local Qin feedback requires a four-input mapped LUT")
            old = inputs.index(feedback[0])
            if old != 2:
                inputs[old], inputs[2] = inputs[2], inputs[old]
                cell["parameters"]["INIT"] = _perm_init(cell["parameters"]["INIT"], old, 2)
            attrs["agamemnon_local_qin_feedback"] = "1"
            # A local-Qin slice exports registered Q. Its LUT result cannot
            # simultaneously use that physical output. Retain ordinary F
            # observers on an independent combinational copy of the function.
            state = attached[0]
            observed = any(
                other is not state or port != "D"
                for other in cells.values()
                for port, bits in other.get("connections", {}).items()
                if other.get("port_directions", {}).get(port) == "input" and output[0] in bits
            ) or any(output[0] in port.get("bits", []) and port.get("direction") in ("output", "inout")
                     for port in module.get("ports", {}).values())
            if observed:
                name = "$local_qin_observer$%d" % next_bit
                suffix = 0
                while name in cells or name in additions:
                    suffix += 1
                    name = "$local_qin_observer$%d$%d" % (next_bit, suffix)
                additions[name] = {
                    "type": "LUT", "hide_name": 1,
                    "parameters": dict(cell["parameters"]),
                    "attributes": {"agamemnon_local_qin_observer": "1", "src": attrs.get("src", "")},
                    "port_directions": {"I": "input", "Q": "output"},
                    "connections": {"I": list(inputs), "Q": list(output)},
                }
                cell["connections"]["Q"] = [next_bit]
                state["connections"]["D"] = [next_bit]
                next_bit += 1
            count += 1
        cells.update(additions)
    if count:
        json.dump(data, open(json_path, "w"))
    return count


def externalize_multi_selffb(json_path):
    """Break four-or-more own-Q loops with external identity-LUT buffers.

    ``permute_selffb_to_inputD`` (below) exposes one-to-three own-Q feedback
    LUTs to the native, four-site X14Y11 direct-D placement pool.  Four sites
    are individually qualified, but the observed four-site composition set an
    additional static configuration bit.  Never form that unqualified native
    composition: at four or more loops retain the already-qualified external
    feedback construction instead.

    Designs with many state-holding registers (a bit-serial core such as
    SERV) commonly need far more than four such cells. Rather than widen the
    direct-D pool (that requires new per-site silicon qualification, which is
    out of scope here), rewrite every own-Q feedback loop using the external-
    identity-LUT-feedback construction that is already silicon-qualified at
    sixteen simultaneous lanes: see docs/MCU_AHB_REGISTER_BANK.md, "Exact
    16-bit held-scratch checkpoint", trial
    ``mcu-ahb-register-bank16-external-feedback-waited-silicon-20260815``.
    An explicit combinational identity LUT is inserted between the DFF's Q
    and the consuming LUT's own input, so the state-holding LUT no longer
    reads its own Q directly -- it reads the buffer's F output instead. The
    generic packer therefore places the identity buffer on a *separate*
    physical slice (it does not drive the DFF the original LUT drives, so
    ``pack_lut_lutffs`` cannot fuse it in), and the loop closes over ordinary
    general routing: the buffer's Q input is a plain net (any placement), and
    its F output feeding the state LUT is exactly the "cell-to-cell read"
    pattern ``permute_reads_to_inputD`` already moves onto I[3] -- the same
    corridor already exercised device-wide, not a 4-site pool.  No
    ``agamemnon_direct_d_feedback`` tag is ever applied to a buffered cell, so
    the admission gate simply never sees it.

    Only fires when more than three own-Q feedback LUTs are present in a
    module. Idempotent. Returns the number of feedback loops buffered.

    NOTE: this construction is silicon-qualified only for the sixteen
    hand-placed register-bank lanes above. Generic, auto-placed use (as here)
    is proven only through routed-netlist simulation (``agamemnon verify``)
    until a future board session repeats the qualification at arbitrary
    placement.
    """
    d = json.load(open(json_path))
    changed = 0
    dirty = False
    for mod in d.get("modules", {}).values():
        cells = mod.get("cells", {})
        dff_q_by_d = {}
        for c in cells.values():
            if c.get("type") != "DFF":
                continue
            dn = c["connections"].get("D", []); qn = c["connections"].get("Q", [])
            if dn and qn:
                dff_q_by_d[dn[0]] = qn[0]
        feedback = []
        for name, c in cells.items():
            if c.get("type") != "LUT":
                continue
            q = c["connections"].get("Q", [])
            I = c["connections"].get("I", [])
            if not q:
                continue
            fb = dff_q_by_d.get(q[0])
            if fb is None:
                continue
            ks = [k for k, net in enumerate(I) if net == fb]
            if not ks:
                continue
            feedback.append((c, fb, ks))
        if len(feedback) <= 3:
            continue
        max_bit = 1
        for c in cells.values():
            for conn in c.get("connections", {}).values():
                max_bit = max([max_bit] + [n for n in conn if isinstance(n, int)])
        next_bit = max_bit + 1
        additions = {}
        for index, (c, fb, ks) in enumerate(feedback):
            buf_out = next_bit; next_bit += 1
            buf_name = "$agamemnon$feedback_buffer$%d" % index
            additions[buf_name] = {
                "type": "LUT",
                "parameters": {
                    "INIT": "1010101010101010",  # identity of I[0]
                    "K": "00000000000000000000000000000100",
                },
                "attributes": {"agamemnon_external_selffb_buffer": "1"},
                "port_directions": {"I": "input", "Q": "output"},
                "connections": {"I": [fb, "0", "0", "0"], "Q": [buf_out]},
            }
            I = c["connections"]["I"]
            for k in ks:
                I[k] = buf_out
            changed += 1
            dirty = True
        cells.update(additions)
    if dirty:
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
    for mod in d.get("modules", {}).values():
        cells = mod.get("cells", {})
        feedback_luts = []
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
            if "agamemnon_local_qin_feedback" in attrs:
                continue
            had_inferred_origin = (
                attrs.get("agamemnon_direct_d_origin") ==
                "qin-pack-inferred-own-q"
            )
            feedback_luts.append((c, q[0], fb, had_inferred_origin))
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
        # The exact one-, two-, and three-cell compositions are admitted to a
        # native logical pool.  The uarch's hard BEL predicate performs the
        # actual matching over X14Y11_SLICE4..7; no inferred member receives a
        # BEL hint here.  A pre-existing user BEL remains an explicit hard
        # constraint and therefore does not receive native-pool ownership.
        if 1 <= len(feedback_luts) <= 3:
            for feedback_lut, next_state_net, registered_q_net, had_inferred_origin in feedback_luts:
                attrs = feedback_lut.setdefault("attributes", {})
                # Retire N5.3's generated singleton lock on idempotent reruns,
                # while preserving an original user-authored BEL constraint.
                if (had_inferred_origin and
                        attrs.get("BEL") == "X14Y11_SLICE7"):
                    del attrs["BEL"]
                    dirty = True
                if ("BEL" not in attrs and
                        attrs.get("agamemnon_direct_d_origin") ==
                        "qin-pack-inferred-own-q"):
                    wanted = {
                        "AGRV2K_NATIVE_DIRECT_D_POOL": "X14Y11_SLICE4_7_V1",
                        "AGRV2K_NATIVE_DIRECT_D_COUNT": str(len(feedback_luts)),
                    }
                    for name, value in wanted.items():
                        if attrs.get(name) != value:
                            attrs[name] = value
                            dirty = True

                # The qualified topology keeps registered Q on the local
                # feedback branch and presents LUT F (next state) to ordinary
                # routing. Move every external input reader in the admitted
                # composition from Q to F while leaving own-Q I[3] untouched.
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
                # At this pre-iopadmap boundary, a module output/inout is also
                # an external observation. Move its aliases to F before later
                # lowering materializes them as IOB users; input-only ports do
                # not observe the registered Q and are deliberately untouched.
                for port in mod.get("ports", {}).values():
                    if port.get("direction") not in ("output", "inout"):
                        continue
                    for index, net in enumerate(port.get("bits", [])):
                        if net == registered_q_net:
                            port["bits"][index] = next_state_net
                            rewired += 1
                if rewired and attrs.get("agamemnon_direct_d_observe_f") != "1":
                    attrs["agamemnon_direct_d_observe_f"] = "1"
                    dirty = True
        else:
            # Direct calls that bypass externalize_multi_selffb must not carry
            # stale native capability into an unqualified four-cell design.
            for feedback_lut, _, _, _ in feedback_luts:
                attrs = feedback_lut.setdefault("attributes", {})
                for name in ("AGRV2K_NATIVE_DIRECT_D_POOL",
                             "AGRV2K_NATIVE_DIRECT_D_COUNT"):
                    if name in attrs:
                        del attrs[name]
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
    INIT alongside each swap. Generic all-pad four-input LUTs are unchanged, but an exact left-edge
    corridor still enforces its recorded physical pin even when all four inputs are occupied.
    """
    d = json.load(open(json_path)); changed = 0
    # Most characterized top inputs use the high LUT pins, but the exact
    # left-edge link corridors terminate on a specific target_pin recorded by
    # the vendor route (PIN_25..28 -> I[1], I[2], I[2], I[3]).  Apply those
    # identities before the generic high-pin packing.  PCF aliases are resolved
    # the same way as place_auto, so vector-port spellings cannot bypass it.
    exact_pin_by_pad_net = {}
    pcf = json.loads(os.environ.get("AGAMEMNON_PCF_JSON", "{}"))
    data = os.environ.get("AGAMEMNON_DATA")
    exact_targets = {}
    if pcf and data:
        path = os.path.join(data, "pad_input_L48_left_corridors.csv")
        if os.path.exists(path):
            for row in csv.DictReader(open(path, newline="", encoding="utf-8")):
                if not row.get("cell_table"):
                    exact_targets[row["pin"]] = int(row["target_pin"])
        # A top-edge input may likewise have only one measured route into a
        # particular physical LUT pin.  Keep that constraint beside the exact
        # pad-entry row; an absent target_pin retains the generic high-pin
        # packing used by the older qualified inputs.
        path = os.path.join(data, "pad_input_L48.csv")
        if os.path.exists(path):
            for row in csv.DictReader(open(path, newline="", encoding="utf-8")):
                if (row.get("target_pin") or "").strip():
                    exact_targets[row["verified_pin"]] = int(row["target_pin"])
        from agamemnon.engine import pcf_ports
        aliases = pcf_ports.alias_map(pcf)
        for mod in d.get("modules", {}).values():
            for name, cell in mod.get("cells", {}).items():
                if cell.get("type") != "GENERIC_IOB":
                    continue
                port = name.split("$iopadmap$top.", 1)[-1]
                key = aliases.get(port)
                pin = pcf.get(key) if key is not None else None
                target = exact_targets.get(pin)
                nets = cell.get("connections", {}).get("O", [])
                if target is not None and len(nets) == 1 and isinstance(nets[0], int):
                    exact_pin_by_pad_net[nets[0]] = target
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
            if not original:
                continue
            q = c.get("connections", {}).get("Q", [])
            selfnet = dff_q_by_d.get(q[0]) if q else None
            reserved = {I.index(selfnet)} if selfnet in I else set()
            exact = [(net, exact_pin_by_pad_net[net]) for _old, net in original
                     if net in exact_pin_by_pad_net]
            # A generic all-pad LUT has no spare pin and historically needed no
            # movement.  An exact left-edge corridor is different: its physical
            # IMUX fixes the pin even when all four LUT inputs are occupied, so
            # the INIT-preserving permutation remains mandatory.
            if len(original) >= len(I) and not exact:
                continue
            if any(target >= len(I) or target in reserved for _net, target in exact):
                raise SystemExit("exact pad input target pin conflicts with this LUT")
            if len({target for _net, target in exact}) != len(exact):
                raise SystemExit("two exact pad inputs require the same LUT target pin")
            assignments = list(exact)
            remaining = [net for _old, net in original if net not in exact_pin_by_pad_net]
            unavailable = reserved | {target for _net, target in exact}
            targets = [k for k in reversed(range(len(I))) if k not in unavailable]
            assignments += list(zip(remaining, sorted(targets[:len(remaining)])))
            for net, target in assignments:
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
    b = split_shared_qualified_bram_inputs(sys.argv[1])
    w = wrap_pad_dff_inputs(sys.argv[1])
    e = lower_local_qin_feedback(sys.argv[1])
    n = permute_selffb_to_inputD(sys.argv[1])
    m = permute_reads_to_inputD(sys.argv[1])
    p = permute_pad_inputs_high(sys.argv[1])
    print("qin_pack: filled %d uniform narrow-BRAM INIT bit(s), split %d "
          "shared qualified BRAM terminal(s), wrapped %d "
          "registered pad input(s), lowered %d internal Qin-to-C feedback "
          "loop(s), permuted %d self-feedback -> I[3], %d cell-to-cell "
          "reads -> I[3], %d direct-pad input move(s) -> high pins" %
          (i, b, w, e, n, m, p))
