# nextpnr-generic --pre-pack adapter for the AGM AGRV2K eFPGA (Project AGaMEMnon).
# Builds the nextpnr arch from the validated open chip database:
#   wires.csv          -> every fabric wire (RMUX/IMUX/OMUX/ClkMUX/Seam/IO...)
#   rrg_edges_full.csv -> every routing pip (OMUX->RMUX, RMUX->RMUX, RMUX->IMUX, IO<->fabric)
# LE model (positional, from the recovered structure): each LogicTILE has 16 alta_slice LEs;
#   slice z inputs A,B,C,D = IMUX[4z..4z+3]; outputs LutOut=OMUX[3z], Q=OMUX[3z+1]; clk=ClkMUX[z].
# This is a FUNCTIONAL arch (routes on the real wire/pip graph). Exact pin<->wire indexing for a
# byte-exact bitstream is a refinement; documented as positional here.
import os, csv
from pathlib import Path

def build(ctx, Loc, environ=None):

    _ENGINE = os.path.dirname(os.path.abspath(__file__))
    from agamemnon.engine.registry import CONSTANTS, options_from
    from agamemnon.engine.features.core_logic import FEATURE as CORE_LOGIC_FEATURE
    from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
    from agamemnon.engine.features.clocks import FEATURE as CLOCK_FEATURE
    from agamemnon.engine.features.physical_io import FEATURE as PHYSICAL_IO_FEATURE
    from agamemnon.engine.features.routing import FEATURE as ROUTING_FEATURE
    from agamemnon.engine.features.bram import FEATURE as BRAM_FEATURE
    from agamemnon.engine.features.mcu_ahb import FEATURE as MCU_AHB_FEATURE
    from agamemnon.engine.features.mcu_gpio import FEATURE as MCU_GPIO_FEATURE
    from agamemnon.engine.features.protocol import ArchitectureContext
    from agamemnon.engine import routing_tiers

    OPTIONS = options_from(environ)
    DATA = OPTIONS.raw("AGAMEMNON_DATA",
        os.path.join(_ENGINE, "..", "chipdb"))

    # ---- 0. PACKAGE / DEVICE selection (env AGAMEMNON_DEVICE, default = dev board L48) ----
    # One AGRV2K fabric is offered in four packages. The core RMUX/LUT/FF mesh is
    # shared; legal package pins and PIN_n->IOTILE coordinates come from the
    # selected package's recovered bond map. L48 is silicon-qualified, while
    # L100/L64/Q32 builds retain an explicit unqualified-map warning.
    from agamemnon.engine import device as _device
    DEV = _device.get_device(OPTIONS.raw("AGAMEMNON_DEVICE"))
    print("AGRV2K arch: DEVICE=%s (%d-pin package, %d bonded user IO pins) [AGAMEMNON_DEVICE]"
          % (DEV.name, DEV.package_pin_count, DEV.user_pin_count))
    if not DEV.bond_map:
        print("AGRV2K arch: note -- selected package has no PIN_n->IOTILE bond map; "
              "physical package IO cannot be exposed")
    K = CONSTANTS["lut_inputs"].value
    def W(x, y, res): return "X%sY%s_%s" % (x, y, res)
    def fam(res):
        i = len(res)
        while i > 0 and res[i-1].isdigit(): i -= 1
        return res[:i]

    # ---- 1. wires ----
    wireset = set()
    tile_res = {}                    # (x,y) -> {family: [indices...]} for LogicTILE bel binding
    tile_type = {}                   # (x,y) -> tile type
    n_wire = 0
    with open(os.path.join(DATA, "wires.csv")) as f:
        for r in csv.DictReader(f):
            x, y, res, tt = r["x"], r["y"], r["resource"], r["tile"]
            name = W(x, y, res)
            if name in wireset: continue
            ctx.addWire(name=name, type=fam(res), x=int(x), y=int(y))
            wireset.add(name); n_wire += 1
            tile_type[(x, y)] = tt
            tile_res.setdefault((x, y), {}).setdefault(fam(res), []).append(res)
    print("AGRV2K arch: added %d wires" % n_wire)

    ctx.setLutK(K)

    # ---- 2. feature-owned core-logic and carry architecture ----
    def has(x, y, res):
        return W(x, y, res) in wireset

    _architecture_context = ArchitectureContext(
        ctx=ctx,
        loc=Loc,
        device=DEV,
        chipdb_root=Path(DATA),
        options=OPTIONS,
        shared={
            "constants": CONSTANTS,
            "wire_name": W,
            "resource_family": fam,
            "wires": wireset,
            "wire_count": n_wire,
            "tile_types": tile_type,
            "tile_resources": tile_res,
        },
    )
    CORE_LOGIC_FEATURE.add_architecture(_architecture_context)
    CARRY_FEATURE.add_architecture(_architecture_context)
    clk_wires = _architecture_context.shared["clock_wires"]
    slice_bels = _architecture_context.shared["slice_bels"]

    # ---- 3. feature-owned physical-I/O and clock architecture ----
    PHYSICAL_IO_FEATURE.add_architecture(_architecture_context)
    CLOCK_FEATURE.add_architecture(_architecture_context)

    # ---- 4. feature-owned general routing architecture ----
    ROUTING_FEATURE.add_architecture(_architecture_context)

    # ---- 5. feature-owned MCU/hard-boundary architecture ----
    _architecture_context.shared["mcu_gpio_feature"] = MCU_GPIO_FEATURE
    MCU_AHB_FEATURE.add_architecture(_architecture_context)

    # ---- 5b. feature-owned BRAM architecture ----
    BRAM_FEATURE.add_architecture(_architecture_context)

    # ---- 6. feature-owned MCU boundary BELs ----
    MCU_AHB_FEATURE.add_bels(_architecture_context)

    # ---- 7. routing-tier disclosure ---------------------------------------------------
    # Deliberately last. Every feature above may supply a pip of its own, and it
    # does so in EVERY admission model; an edge one of them would have supplied is
    # therefore not an edge --release-strict would refuse, whichever loop happened
    # to add it first. Finalising here is what keeps the confidence manifest's
    # central promise true. See agamemnon/engine/routing_tiers.py.
    _tier_records = _architecture_context.shared.get("routing_tier_records")
    if _tier_records:
        rows, seen_pips, meta = _tier_records
        claimed = getattr(seen_pips, "claimed", set())
        kept = [row for row in rows if row["pip"] not in claimed]
        meta["tier_1_witnessed"] += len(rows) - len(kept)
        meta["tier_2_admitted"] = len(kept)
        meta["tier_2_reclaimed_by_a_later_block"] = len(rows) - len(kept)
        print("AGRV2K arch: %s admission -> %d witnessed (tier 1), %d encoding-certain "
              "(tier 2, recorded), %d encoding-ambiguous refused (tier 3: %d at the "
              "clean-sel prune + %d at the gate)"
              % (str(meta["admission_model"]).upper(), meta["tier_1_witnessed"],
                 meta["tier_2_admitted"], meta["tier_3_refused"],
                 meta["tier_3_refused_at_clean_sel_prune"],
                 meta["tier_3_refused_at_admission_gate"]))
        _sidecar_dir = routing_tiers.sidecar_directory()
        if _sidecar_dir:
            routing_tiers.write_sidecar(_sidecar_dir, kept, meta)
            print("AGRV2K arch: recorded %d tier-2 edge(s) in %s"
                  % (len(kept), routing_tiers.SIDECAR))

    # ---- API probe (AGAMEMNON_PROBE=1) ----
    if os.environ.get("AGAMEMNON_PROBE"):
        try:
            for c in ctx.cells:
                print("PROBE cell:", repr(c), type(c).__name__)
        except Exception as e:
            print("PROBE iterate cells ERR:", repr(e))
        print("PROBE bindBel doc:", getattr(ctx.bindBel, "__doc__", None))
        try:
            print("PROBE X10Y4_SLICE0 avail:", ctx.checkBelAvail("X10Y4_SLICE0"))
        except Exception as e:
            print("PROBE checkBelAvail ERR:", repr(e))
