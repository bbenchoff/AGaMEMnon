import csv
import json
from pathlib import Path

from agamemnon.engine import device


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def _rows(filename):
    with (CHIPDB / filename).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_all_package_maps_match_manifest_and_perimeter():
    manifest = json.loads((CHIPDB / "bondmaps.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    expected = {
        "AGRV2KL100": ("bondmap_L100.csv", 78, "recovered-unqualified"),
        "AGRV2KL64": ("bondmap_L64.csv", 49, "recovered-unqualified"),
        "AGRV2KL48": ("bondmap_L48.csv", 34, "silicon-qualified"),
        "AGRV2KQ32": ("bondmap_Q32.csv", 26, "recovered-unqualified"),
    }
    for name, (filename, count, qualification) in expected.items():
        entry = manifest["devices"][name]
        assert (entry["file"], entry["physical_pin_count"], entry["qualification"]) == (
            filename, count, qualification
        )
        rows = _rows(filename)
        assert len(rows) == count
        assert len({row["pin"] for row in rows}) == count
        assert len({(row["x"], row["y"], row["z"]) for row in rows}) == count
        for row in rows:
            x, y = int(row["x"]), int(row["y"])
            assert x in (0, 22) or y in (0, 13)
            assert row["pin"] in device.get_device(name).user_pins


def test_device_exposes_qualified_and_recovered_maps():
    for name in device.PACKAGES:
        target = device.get_device(name)
        assert target.bond_map
        assert target.bond_map_qualified is (name == "AGRV2KL48")
        for pin, pad in target.bond_map.items():
            assert target.pin_to_pad(pin) == pad
    # gen_vlog calls this a legal L100 user pin, while alta-agr marks its pad NC_73.
    l100 = device.get_device("AGRV2KL100")
    assert "PIN_73" in l100.user_pins
    assert l100.pin_to_pad("PIN_73") is None


def test_qualified_l48_reference_coordinates_are_unchanged():
    l48 = device.get_device("AGRV2KL48")
    assert l48.pin_to_pad("PIN_2") == (22, 2, 3, "RIGHT")
    assert l48.pin_to_pad("PIN_10") == (20, 13, 1, "TOP")
    assert l48.pin_to_pad("PIN_25") == (0, 4, 0, "LEFT")
    assert l48.pin_to_pad("PIN_46") == (19, 0, 3, "BOTTOM")
