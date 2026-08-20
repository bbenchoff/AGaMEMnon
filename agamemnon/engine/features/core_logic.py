"""Core LUT/FF preparation, baseline clearing, and bitstream emission."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from agamemnon.engine import physmap

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion
from .route_through import (
    RouteThroughPolicyError,
    complete_footprint_for_cell,
    load_footprints,
)


# The four-link node build presents its X14Y4 slice0 output-enable source LUT
# on OMUX-F (the head of pad_oe_L48_left_corridors.csv link 3).  That site is
# carried in the ``left_vendor_slices`` constant so the device arch always
# offers the presentation, but its per-design emission must be conditional: an
# ordinary design (including every shipped SERV image) that merely places
# combinational logic at X14Y4 slice0 keeps the plain OMUX presentation and its
# byte-exact release image.  Emit it only for a genuine node-pinout design.
NODE_PINOUT_LEFT_SLICES = frozenset({(14, 4, 0)})


def _direct_d_sites(options):
    if not options.enabled("AGAMEMNON_DIRECT_D"):
        return set()
    raw = options.raw("AGAMEMNON_DIRECT_D_SITES")
    if not raw:
        # Backward compatibility for retained routed replays that predate the
        # site list. New source builds derive the exact tagged subset in CLI.
        return {(14, 11, 4), (14, 11, 5), (14, 11, 6), (14, 11, 7)}
    sites = set()
    for token in str(raw).split(";"):
        match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", token.strip())
        if not match:
            raise SystemExit("invalid AGAMEMNON_DIRECT_D_SITES token %r" % token)
        sites.add(tuple(int(match.group(i)) for i in (1, 2, 3)))
    return sites


def _load_route_through_context(chipdb_root, options, module):
    """Return (footprints, routed_nets) for route_through's OWN predicate.

    ``qin_pack.externalize_multi_selffb`` inserts untagged identity-buffer
    LUTs (any module with more than one own-Q self-feedback register --
    counters, LFSRs, shift registers) at ordinary, device-wide sites. Four of
    those sites are also characterized route-through footprints
    (``route_through_footprints.csv``), and ``route_through``'s
    ``complete_footprint_for_cell()`` claims a cell there whenever its INIT
    and routed edge match -- with no requirement that
    ``AGRV2K_ROUTE_THROUGH`` be set (deliberate; see
    ``tests/test_route_through_footprints.py``). Without this cross-check,
    core_logic and route_through both claim the same LUT-init byte for an
    untagged cell and ``bit_ownership.py`` correctly, but unhelpfully,
    refuses the build (byte 65852 mask 0x08 at X14Y4_SLICE0, 22 campaign
    instances as of 2026-08-19). Reuse route_through's own unmodified table
    loader and predicate here -- never re-derive the site list or footprint
    logic -- so the two features cannot silently diverge again.

    Returns ``(None, None)`` when *chipdb_root* is unavailable (legacy/unit
    call sites that construct ``CoreLogicState`` directly); the exclusion
    then simply falls back to the explicit ``AGRV2K_ROUTE_THROUGH`` tag.
    """
    if chipdb_root is None:
        return None, None
    root = Path(chipdb_root)
    footprints = load_footprints(root / "route_through_footprints.csv")
    if options.enabled("AGAMEMNON_BRAM_SITE_READ_PATHS"):
        experimental = load_footprints(
            root / "bram_control_route_through_footprints.csv"
        )
        # route_through.prepare() fails closed on an overlap between the two
        # tables; that check still runs there. Here we only need a merged
        # view to evaluate the same predicate it will evaluate.
        footprints.update(experimental)
    routed_nets = [
        (name, set(net.get("bits", [])), net.get("attributes", {}).get("ROUTING", ""))
        for name, net in module.get("netnames", {}).items()
    ]
    return footprints, routed_nets


@dataclass
class CoreLogicState:
    lut_sets: list = field(default_factory=list)
    register_sets: list = field(default_factory=list)
    slices: list = field(default_factory=list)
    clocked_tiles: set = field(default_factory=set)
    left_vendor_slices: set = field(default_factory=set)
    selector_cells: dict = field(default_factory=dict)
    route_through_slices: set = field(default_factory=set)


class CoreLogicFeature:
    descriptor = FeatureDescriptor(
        feature_id="core_logic",
        options=(
            "AGAMEMNON_VENDOR_OUT_ALL",
            "AGAMEMNON_VENDOR_OUT_SLICE",
            "AGAMEMNON_LEFT_PAD_OUT",
            "AGAMEMNON_DIRECT_D",
            "AGAMEMNON_DIRECT_D_SITES",
            "AGAMEMNON_DIRECT_D_COMB_F2",
            "AGAMEMNON_BRAM_PORTB_EXIT",
            "AGAMEMNON_DUAL_LUT_CONST",
        ),
        chipdb_files=(),
        writable_regions=(
            WritableRegion("algorithmic_slice_init", "agamemnon/engine/physmap.py"),
            WritableRegion("selector_family", "pips_full.csv", "byte", "mask"),
        ),
        phase=EmissionPhase.LOGIC,
        evidence=(
            "qualification/pack_reproduction_evidence.jsonl",
            "qualification/routing_evidence.jsonl",
        ),
        maturity="release",
        evidence_tier="individually_qualified",
        architecture="Construct LogicTile slice BELs and their qualified OMUX presentations.",
        bitstream=(
            "Clear every placed slice LUT and OMUX field, emit complemented LUT INIT "
            "bits, and select registered or qualified alternate OMUX presentation."
        ),
    )

    def add_architecture(self, context):
        ctx, Loc, options = context.ctx, context.loc, context.options
        shared = context.shared
        wire_name = shared["wire_name"]
        wires = shared["wires"]
        tile_types = shared["tile_types"]
        constants = shared["constants"]
        lut_inputs = constants["lut_inputs"].value

        def has(x, y, resource):
            return wire_name(x, y, resource) in wires

        vendor_out_raw = options.raw("AGAMEMNON_VENDOR_OUT_SLICE")
        vendor_out = (
            options.coordinates("AGAMEMNON_VENDOR_OUT_SLICE")
            if vendor_out_raw else None
        )
        vendor_out_all = options.enabled("AGAMEMNON_VENDOR_OUT_ALL")
        experimental_bram_control = options.enabled(
            "AGAMEMNON_BRAM_SITE_READ_PATHS"
        )
        # This exact-site set also contains the simultaneous four-OE control's
        # X14Y4 slice0 LUT-F presentation.  The device arch always offers it as
        # a capability, but its per-design bitstream emission is gated on a
        # node-pinout design in prepare() (NODE_PINOUT_LEFT_SLICES).
        left_vendor = (
            set(constants["left_vendor_slices"].value)
            if options.enabled("AGAMEMNON_LEFT_PAD_OUT") else set()
        )
        direct_d_sites = _direct_d_sites(options)
        direct_d_comb_f2 = options.raw("AGAMEMNON_DIRECT_D_COMB_F2")
        if direct_d_comb_f2:
            direct_d_sites.discard(
                options.coordinates("AGAMEMNON_DIRECT_D_COMB_F2")
            )
        bram_qsel = (
            dict(constants["bram_portb_qsel"].value)
            if options.enabled("AGAMEMNON_BRAM_PORTB_EXIT") else {}
        )
        dual_const_raw = options.raw("AGAMEMNON_DUAL_LUT_CONST")
        dual_const = (
            options.coordinates("AGAMEMNON_DUAL_LUT_CONST")
            if dual_const_raw else None
        )
        if vendor_out_all:
            print("AGRV2K arch: VENDOR-OUT enabled for every slice "
                  "(F=OMUX[3z], Q=OMUX[3z+1])")
        elif vendor_out:
            print("AGRV2K arch: VENDOR-OUT slice %s -> F on OMUX[3z+0], "
                  "Q on OMUX[3z+1]" % (vendor_out,))

        count = 0
        clock_wires = []
        slice_bels = {}
        for (x, y), tile_type in tile_types.items():
            if tile_type != "LogicTILE":
                continue
            for z in range(16):
                inputs = ["IMUX%02d" % (4 * z + i) for i in range(4)]
                if dual_const == (int(x), int(y), z):
                    output0 = "OMUX%02d" % (3 * z)
                    output2 = "OMUX%02d" % (3 * z + 2)
                    if not all(has(x, y, wire) for wire in (output0, output2)):
                        continue
                    bel = "X%sY%s_DUAL_SLICE%d" % (x, y, z)
                    ctx.addBel(
                        name=bel, type="AGRV2K_DUAL_LUT_CONST",
                        loc=Loc(int(x), int(y), z), gb=False, hidden=False,
                    )
                    ctx.addBelOutput(
                        bel=bel, name="F0", wire=wire_name(x, y, output0)
                    )
                    ctx.addBelOutput(
                        bel=bel, name="F2", wire=wire_name(x, y, output2)
                    )
                    count += 1
                    continue

                output_f = output_q = "OMUX%02d" % (3 * z + 2)
                clock = "ClkMUX%02d" % z
                site = (int(x), int(y), z)
                if site in bram_qsel:
                    output_f = output_q = "OMUX%02d" % (
                        3 * z + bram_qsel[site]
                    )
                if (
                    vendor_out_all or vendor_out == site or site in left_vendor
                    or site in direct_d_sites or
                    (experimental_bram_control and site in {
                        (14, 4, 3), (14, 5, 4)
                    })
                ):
                    output_f = "OMUX%02d" % (3 * z)
                    output_q = "OMUX%02d" % (3 * z + 1)
                if not all(
                    has(x, y, wire)
                    for wire in inputs + [output_f, output_q, clock]
                ):
                    continue
                bel = "X%sY%s_SLICE%d" % (x, y, z)
                ctx.addBel(
                    name=bel, type="GENERIC_SLICE",
                    loc=Loc(int(x), int(y), z), gb=False, hidden=False,
                )
                ctx.addBelInput(
                    bel=bel, name="CLK", wire=wire_name(x, y, clock)
                )
                for index in range(lut_inputs):
                    ctx.addBelInput(
                        bel=bel, name="I[%d]" % index,
                        wire=wire_name(x, y, inputs[index]),
                    )
                ctx.addBelOutput(
                    bel=bel, name="F", wire=wire_name(x, y, output_f)
                )
                ctx.addBelOutput(
                    bel=bel, name="Q", wire=wire_name(x, y, output_q)
                )
                clock_wires.append(wire_name(x, y, clock))
                slice_bels.setdefault((int(x), int(y)), {})[z] = bel
                count += 1
        shared["clock_wires"] = clock_wires
        shared["slice_bels"] = slice_bels
        print("AGRV2K arch: added %d GENERIC_SLICE bels" % count)
        return count

    @staticmethod
    def _require_omux(selector_cells, x, y, z, selection):
        """Return CFG_OMUX<z> sel *selection*, or fail closed.

        This is the bit that PRESENTS a slice output on a mesh wire -- sel=2 for
        an ordinary registered slice, sel 0/1 for the vendor F/Q pair, and the
        BRAM Port-B alternate. Every one of the 132 placeable LogicTiles carries
        all three selections; the twelve right-edge RogicTILE columns carry only
        sel 0 and host no slice BEL. Skipping the lookup therefore never meant
        "this design does not need it" -- it meant the register was placed,
        clocked, and routed with its output never presented, which
        config-accepts (FCB 0x000f0002) and reads static.
        """
        bit = selector_cells.get((x, y, "CFG_OMUX%d" % z, selection))
        if not bit:
            raise SystemExit(
                "core logic: pips_full.csv has no CFG_OMUX%d sel %d cell at "
                "X%dY%d; refusing to emit a slice whose output would never be "
                "presented on a mesh wire" % (z, selection, x, y)
            )
        return bit

    def prepare(self, module, selector_cells, options, constants,
                chipdb_root=None, node_pinout=False):
        state = CoreLogicState(selector_cells=selector_cells)
        route_through_footprints, route_through_routed_nets = (
            _load_route_through_context(chipdb_root, options, module)
        )
        vendor_out_all = options.enabled("AGAMEMNON_VENDOR_OUT_ALL")
        vendor_out_raw = options.raw("AGAMEMNON_VENDOR_OUT_SLICE")
        vendor_out = (
            options.coordinates("AGAMEMNON_VENDOR_OUT_SLICE")
            if vendor_out_raw else None
        )
        state.left_vendor_slices = (
            set(constants["left_vendor_slices"].value)
            if options.enabled("AGAMEMNON_LEFT_PAD_OUT") else set()
        )
        # The four-link node output-enable presentation sites are emitted only
        # for a node-pinout design; an ordinary design that happens to place at
        # the same slice keeps its plain OMUX presentation (see the module
        # note on NODE_PINOUT_LEFT_SLICES).
        if not node_pinout:
            state.left_vendor_slices -= NODE_PINOUT_LEFT_SLICES
        legacy_direct_d_sites = _direct_d_sites(options)

        for cell in module["cells"].values():
            cell_type = cell.get("type")
            if cell_type not in ("GENERIC_SLICE", "AGRV2K_DUAL_LUT_CONST"):
                continue
            bel = cell["attributes"]["NEXTPNR_BEL"]
            match = re.match(r"X(\d+)Y(\d+)_(?:DUAL_)?SLICE(\d+)", bel)
            x, y, z = (int(match.group(index)) for index in (1, 2, 3))
            direct_d_site = (x, y, z) in legacy_direct_d_sites
            if cell_type == "AGRV2K_DUAL_LUT_CONST":
                value = int(cell.get("parameters", {}).get("VALUE", "0"), 2)
                init = 0xFFFF if value else 0
                state.register_sets.append(
                    self._require_omux(selector_cells, x, y, z, 0)
                )
            else:
                init = int(cell["parameters"]["INIT"], 2)

            state.slices.append((x, y, z))
            # An explicitly requested route-through is not ordinary user LUT
            # logic. Its complete, silicon-qualified sparse footprint owns the
            # LUT permutation and final selector as one atomic unit. Keep the
            # slice in the placement inventory, but do not also claim its bits
            # through core_logic; route_through.prepare() still fails closed if
            # the site, INIT, FF mode, or final edge lacks an exact footprint.
            route_through_attribute = cell.get("attributes", {}).get(
                "AGRV2K_ROUTE_THROUGH", "0"
            )
            try:
                explicit_route_through = bool(
                    int(str(route_through_attribute), 2)
                )
            except ValueError:
                explicit_route_through = False
            claimed_by_route_through = explicit_route_through
            if not claimed_by_route_through and route_through_footprints is not None:
                # No explicit tag -- but route_through's OWN predicate (not
                # re-derived here) may still claim this exact cell: an
                # untagged identity-buffer LUT that qin_pack placed at one of
                # the four characterized sites, whose INIT and routed input
                # edge happen to match the table. When it does, it is not
                # "ordinary user LUT logic" either, and core_logic must defer
                # for the same reason as the explicit-tag case above. A
                # RouteThroughPolicyError here (e.g. a characterized site
                # whose edge does NOT match, which is fail-closed by policy)
                # is not this feature's call to make -- leave the cell as
                # ordinary core_logic-owned and let route_through.prepare()
                # raise its own, identical, fail-closed error later in the
                # pipeline.
                try:
                    implicit_footprint = complete_footprint_for_cell(
                        cell, route_through_routed_nets, route_through_footprints
                    )
                except RouteThroughPolicyError:
                    implicit_footprint = ()
                claimed_by_route_through = bool(implicit_footprint)
            if claimed_by_route_through:
                state.route_through_slices.add((x, y, z))
                continue
            bram_selection = cell.get("attributes", {}).get("AGRV2K_OMUX_SEL")
            bram_selection = (
                int(str(bram_selection), 2) if bram_selection is not None else None
            )
            if int(cell["parameters"].get("FF_USED", "0"), 2):
                selections = (
                    (0, 1)
                    if (vendor_out_all or vendor_out == (x, y, z) or
                        (x, y, z) in state.left_vendor_slices or direct_d_site)
                    else ((bram_selection,) if bram_selection is not None else (2,))
                )
                for selection in selections:
                    state.register_sets.append(
                        self._require_omux(selector_cells, x, y, z, selection)
                    )
                state.clocked_tiles.add((x, y))
            elif (vendor_out_all or (x, y, z) in state.left_vendor_slices or
                  direct_d_site):
                state.register_sets.append(
                    self._require_omux(selector_cells, x, y, z, 0)
                )
            elif bram_selection is not None:
                state.register_sets.append(
                    self._require_omux(selector_cells, x, y, z, bram_selection)
                )

            for init_index in range(16):
                byte, mask = physmap.init_bit_pos(x, y, z, init_index)
                if not ((init >> init_index) & 1):
                    state.lut_sets.append((byte, mask))

        print("slices placed:", state.slices, "; LUT-init bits:", len(state.lut_sets))
        return state

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for x, y, z in context.state.slices:
            if (x, y, z) in context.state.route_through_slices:
                continue
            for init_index in range(16):
                byte, mask = physmap.init_bit_pos(x, y, z, init_index)
                if byte < len(context.image):
                    context.image[byte] &= (~mask) & 0xFF
                    if context.ownership is not None:
                        context.ownership.touch(byte, mask, "LUT")
                    count += 1
            for selection in range(3):
                bit = context.state.selector_cells.get(
                    (x, y, "CFG_OMUX%d" % z, selection)
                )
                if bit and bit[0] < len(context.image):
                    context.image[bit[0]] &= (~bit[1]) & 0xFF
                    if context.ownership is not None:
                        context.ownership.touch(bit[0], bit[1], "LUT")
                    count += 1
        return count

    def writable_bits(self, state):
        bits = set(state.lut_sets)
        bits.update(state.register_sets)
        for x, y, z in state.slices:
            if (x, y, z) in state.route_through_slices:
                continue
            bits.update(
                physmap.init_bit_pos(x, y, z, init_index)
                for init_index in range(16)
            )
            bits.update(
                bit for selection in range(3)
                if (bit := state.selector_cells.get(
                    (x, y, "CFG_OMUX%d" % z, selection)
                ))
            )
        return bits

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.lut_sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "LUT")
                count += 1
        return count

    def emit_register_modes(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.register_sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "register_mode")
                count += 1
        print("registered slices (CFG_OMUX<z> sel=2 set): %d" %
              len(context.state.register_sets))
        return count


FEATURE = CoreLogicFeature()
