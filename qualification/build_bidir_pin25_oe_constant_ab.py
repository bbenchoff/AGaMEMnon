#!/usr/bin/env python3
"""Build a single-variable OE-source A/B from the qualified PIN_25 route.

The ordinary readback campaign image is used as the immutable route template.
Its X10Y4 identity LUT presents the external PIN_10 signal to the characterized
OE corridor.  These two derivatives change only that LUT's INIT parameter to
constant zero or constant one.  The pad data remains a local hard zero, so both
arms are electrically safe: each can only release PIN_25 or drive it low.

This is intentionally a routed-netlist differential, not another place/route.
It removes the unqualified PIN_10-to-X10Y4 mesh route from the experiment while
holding the IOB mode, data, input/readback, OE corridor, and placement constant.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "agamemnon" / "engine"
CELL = "$quad_oe0_identity"
INITS = {"const0": "0" * 16, "const1": "1" * 16}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _only_init_changed(before: dict, after: dict, expected: str) -> None:
    probe = copy.deepcopy(before)
    cell = probe["modules"]["top"]["cells"][CELL]
    assert cell["attributes"]["NEXTPNR_BEL"] == "X10Y4_SLICE0"
    assert cell["parameters"]["INIT"] == "1010101010101010"
    cell["parameters"]["INIT"] = expected
    assert probe == after, "routed JSON changed outside the OE source LUT INIT"


def build(directory: Path) -> dict:
    template = directory / "bidir_pin25_readback_routed.json"
    assert template.is_file(), template
    original = json.loads(template.read_text(encoding="utf-8"))
    module = original["modules"]["top"]
    source = module["cells"][CELL]
    assert source["type"] == "GENERIC_SLICE"
    assert source["attributes"]["NEXTPNR_BEL"] == "X10Y4_SLICE0"
    assert source["parameters"]["INIT"] == "1010101010101010"
    link = next(cell for cell in module["cells"].values()
                if cell.get("attributes", {}).get("NEXTPNR_BEL") == "X0Y4_IOB0")
    assert set(link["connections"]) == {"PAD", "I", "O", "EN"}
    assert link["attributes"]["AGRV2K_IO_DATA_GND"].endswith("1")
    assert link["connections"]["I"] == []
    assert link["connections"]["EN"] == source["connections"]["F"]

    rows = []
    for arm, init in INITS.items():
        routed = directory / f"bidir_pin25_oe_{arm}_routed.json"
        image = directory / f"bidir_pin25_oe_{arm}.bin"
        design = copy.deepcopy(original)
        design["modules"]["top"]["cells"][CELL]["parameters"]["INIT"] = init
        _only_init_changed(original, design, init)
        routed.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
        env = dict(os.environ, AGAMEMNON_DATA=str(ROOT / "agamemnon" / "chipdb"))
        result = subprocess.run(
            [sys.executable, str(ENGINE / "to_bin.py"), str(routed), str(image)],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        transcript = result.stdout + result.stderr
        assert result.returncode == 0, transcript
        match = re.search(
            r"data pips: (\d+) total, (\d+) mapped .*"
            r"0 legacy-abs, 0 predicted\), 0 unmapped", transcript)
        assert match and match.group(1) == match.group(2), transcript
        rows.append({"arm": arm, "init": init,
                     "image_sha256": sha256(image),
                     "routed_sha256": sha256(routed),
                     "mapped_pips": int(match.group(1))})

    a = json.loads((directory / "bidir_pin25_oe_const0_routed.json").read_text())
    b = json.loads((directory / "bidir_pin25_oe_const1_routed.json").read_text())
    _only_init_changed(original, a, INITS["const0"])
    _only_init_changed(original, b, INITS["const1"])
    b_probe = copy.deepcopy(a)
    b_probe["modules"]["top"]["cells"][CELL]["parameters"]["INIT"] = INITS["const1"]
    assert b_probe == b, "A/B differ outside the one source-LUT INIT"
    return {"result": "pass", "template_sha256": sha256(template),
            "single_variable": f"{CELL}.INIT", "arms": rows}


def main() -> int:
    directory = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tools" / "lab"
    print(json.dumps(build(directory), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
