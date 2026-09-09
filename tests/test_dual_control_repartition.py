"""Compiled regression for infeasible paired native-control clusters.

The dual-line experiment may group two enable nets while their combined
population fits a tile.  A later physical slot restriction can still make the
heterogeneous cluster impossible.  It must then become two ordinary
single-enable native clusters before the optional one-group repartitioner is
considered.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import test_uarch_register_input_legality as support


def _dffe(enable: int, data: int, q: int) -> dict:
    return {
        "hide_name": 0,
        "type": "DFFE",
        "parameters": {},
        "attributes": {"AGRV2K_SHARED_CONTROL_MODE": "CLOCK_ENABLE_POS"},
        "port_directions": {
            "CLK": "input", "EN": "input", "D": "input", "Q": "output",
        },
        "connections": {"CLK": [2], "EN": [enable], "D": [data], "Q": [q]},
    }


def _reserved_combinational_slice(z: int, index: int) -> dict:
    """Occupy one non-FF slot without creating a control consumer."""
    # Keep inputs disconnected.  A constant INIT does not depend on them, and
    # this avoids `$PACKER_GND` pseudo-cell users in upstream HeAP's HPWL map.
    cell = support._lut("reserve_%d" % z, 0, ("x", "x", "x", "x"),
                        10000 + 100 * index)
    # Let the real packer turn this LUT into its normal F-present,
    # FF_UNUSED GENERIC_SLICE.  Forging a post-pack Q-only unused slice trips
    # unrelated timing bookkeeping before the control-placement test runs.
    cell["attributes"].update({
        "NEXTPNR_BEL": "X14Y11_SLICE%d" % z,
        "BEL_STRENGTH": format(5, "032b"),
    })
    return cell


def _dual_pair_with_one_feasible_group_per_tile() -> dict:
    """A 3-FF direct-D group and 8-FF feedthrough group that cannot pair.

    DIRECT_D_I3 limits the first group to X14Y11_SLICE4..7.  Fixed LUT-only
    occupants reserve the other twelve slots in that tile.  The direct-D group
    can still use three of its four slots; the feedthrough group can still use
    another tile.  A paired 3+8 group, however, cannot fit at its only direct-D
    candidate tile.
    """
    cells = {}
    netnames = {"enable_a": 3, "enable_b": 4}

    # These are deliberately real drivers, rather than merely named JSON
    # bits.  A packed control root consumes its enable on I.  HeAP seeds a
    # relative-cluster root only when that input net has a driver and a user;
    # otherwise it locks the root and never initialises its children in
    # cell_locs.  A source design always has an enable expression here.
    cells["enable_a_driver"] = support._lut(
        "enable_a_driver", 0x0000, ("x", "x", "x", "x"), 3,
    )
    cells["enable_b_driver"] = support._lut(
        "enable_b_driver", 0x0000, ("x", "x", "x", "x"), 4,
    )

    # The direct-D shape is an actual LUT+FF packing form.  Its registered Q
    # is the LUT I[3] feedback input, with the exact direct-D marker.
    for index in range(3):
        q, data = 300 + index, 100 + index
        cells["logic_a_%d" % index] = support._lut(
            "logic_a_%d" % index, 0x00FF, ("0", "0", "0", q), data,
            tags=("agamemnon_direct_d_feedback",),
        )
        cells["state_a_%d" % index] = _dffe(3, data, q)
        netnames["data_a_%d" % index] = data
        netnames["q_a_%d" % index] = q

    # A second real LUT+FF shape has ordinary I[0] feedthrough semantics.
    for index in range(8):
        source, data, q = 500 + index, 600 + index, 700 + index
        cells["logic_b_%d" % index] = support._lut(
            "logic_b_%d" % index, 0xAAAA, (source, "x", "x", "x"), data,
        )
        cells["state_b_%d" % index] = _dffe(4, data, q)
        netnames["source_b_%d" % index] = source
        netnames["data_b_%d" % index] = data
        netnames["q_b_%d" % index] = q

    for index, z in enumerate(tuple(range(4)) + tuple(range(8, 16))):
        cells["reserve_%d" % z] = _reserved_combinational_slice(z, index)
        netnames["reserve_q_%d" % z] = 10000 + 100 * index

    return support._design(cells, netnames)


def _native_groups(module: dict) -> dict[str, list[tuple[str, dict]]]:
    groups: dict[str, list[tuple[str, dict]]] = {}
    for name, cell in module["cells"].items():
        enable = cell.get("attributes", {}).get("AGRV2K_CLOCK_ENABLE_NET")
        if cell.get("type") == "GENERIC_SLICE" and enable in {"enable_a", "enable_b"}:
            groups.setdefault(enable, []).append((name, cell))
    return groups


def test_infeasible_dual_pair_unpairs_before_single_group_repartition(tmp_path, monkeypatch):
    if os.environ.get("AGAMEMNON_UARCH_DEVDB"):
        monkeypatch.setattr(support, "DEVDB", Path(os.environ["AGAMEMNON_UARCH_DEVDB"]))
    monkeypatch.setenv("AGRV2K_SHARED_CONTROL_ENABLE", "1")
    monkeypatch.setenv("AGRV2K_CONTROL_REPARTITION", "1")

    # Establish that the slots left by the fixture really admit the two
    # single-enable clusters.  This is the control that distinguishes an
    # unpairing regression from a generally illegal fixture.
    monkeypatch.setenv("AGRV2K_DUAL_NATIVE_CONTROL", "0")
    single_result, single_log, _ = support._run(
        tmp_path,
        "independent_controls",
        _dual_pair_with_one_feasible_group_per_tile(),
        "--no-route", "--placer", "heap", "--seed", "1",
    )
    assert single_result.returncode == 0, single_log

    monkeypatch.setenv("AGRV2K_DUAL_NATIVE_CONTROL", "1")

    result, log, output = support._run(
        tmp_path,
        "dual_unpair",
        _dual_pair_with_one_feasible_group_per_tile(),
        "--no-route", "--placer", "heap", "--seed", "1",
    )
    assert result.returncode == 0, log
    assert "unpair infeasible native groups" in log
    assert "repartition impossible enable group" not in log

    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    groups = _native_groups(module)
    assert {enable: len(members) for enable, members in groups.items()} == {
        "enable_a": 3,
        "enable_b": 8,
    }
    assert all(
        cell["attributes"].get("AGRV2K_SHARED_CONTROL_MODE") == "CLOCK_ENABLE_POS"
        for members in groups.values() for _, cell in members
    )

    controls = {}
    for name, cell in module["cells"].items():
        if cell.get("type") != "AGRV2K_TILE_CONTROL":
            continue
        enable = cell.get("attributes", {}).get("AGRV2K_CLOCK_ENABLE_NET")
        if enable in {"enable_a", "enable_b"}:
            controls[enable] = (name, cell)
    assert set(controls) == {"enable_a", "enable_b"}

    # Rebuilt clusters own CLKEN0 independently.  The direct-D group has its
    # one admitted tile; native isolation sends the feedthrough group elsewhere.
    tiles = set()
    for enable, (_, control) in controls.items():
        bel = control["attributes"]["NEXTPNR_BEL"]
        assert bel.endswith("_CLKEN0")
        tile = bel.rsplit("_", 1)[0]
        tiles.add(tile)
        assert all(
            cell["attributes"]["NEXTPNR_BEL"].startswith(tile + "_SLICE")
            for _, cell in groups[enable]
        )
    assert len(tiles) == 2
    assert controls["enable_a"][1]["attributes"]["NEXTPNR_BEL"].startswith("X14Y11_")
