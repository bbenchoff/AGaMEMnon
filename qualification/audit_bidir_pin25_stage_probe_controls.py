#!/usr/bin/env python3
"""Static audit for the X14Y4 stage-output probe and constant controls."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "agamemnon" / "engine"
ARMS = {"external": "1111000011110000", "const0": "0" * 16, "const1": "1" * 16}
INGRESS = {
    "X20Y13_InputMUX02.X20Y12_RMUX20",
    "X20Y12_RMUX20.X18Y12_RMUX80",
    "X18Y12_RMUX80.X18Y8_RMUX43",
    "X18Y8_RMUX43.X14Y8_RMUX73",
    "X14Y8_RMUX73.X14Y4_RMUX22",
    "X14Y4_RMUX22.X14Y4_IMUX18",
}
OE_BRANCH = {
    "X14Y4_OMUX14.X14Y4_RMUX43",
    "X14Y4_RMUX43.X10Y4_RMUX94",
    "X10Y4_RMUX94.X10Y4_IMUX00",
}
OBS_BRANCH = {
    "X14Y4_OMUX14.X14Y4_RMUX32",
    "X14Y4_RMUX32.X14Y8_RMUX32",
    "X14Y8_RMUX32.X14Y11_RMUX27",
    "X14Y11_RMUX27.X14Y9_RMUX15",
    "X14Y9_RMUX15.X18Y9_RMUX69",
    "X18Y9_RMUX69.X18Y13_RMUX28",
    "X18Y13_RMUX28.X18Y13_IOMUX00",
}
OE_TAIL = {
    "X10Y4_OMUX02.X10Y4_RMUX08",
    "X10Y4_RMUX08.X11Y4_RMUX26",
    "X11Y4_RMUX26.X8Y4_RMUX13",
    "X8Y4_RMUX13.X4Y4_RMUX49",
    "X4Y4_RMUX49.X0Y4_RMUX00",
    "X0Y4_RMUX00.X0Y4_IOMUX06",
}
LINK_INPUT = {
    "X0Y4_InputMUX00.X1Y4_RMUX11",
    "X1Y4_RMUX11.X1Y4_IMUX09",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pips(module: dict, net: str) -> set[str]:
    fields = module["netnames"][net]["attributes"].get("ROUTING", "").split(";")
    return {fields[index] for index in range(1, len(fields), 3) if fields[index]}


def _cell(module: dict, bel: str) -> dict:
    rows = [cell for cell in module["cells"].values()
            if cell.get("attributes", {}).get("NEXTPNR_BEL") == bel]
    assert len(rows) == 1, (bel, len(rows))
    return rows[0]


def audit(directory: Path) -> dict:
    rows = []
    route_shapes = []
    for arm, expected_init in ARMS.items():
        routed = directory / f"bidir_pin25_stage_probe_{arm}_routed.json"
        image = directory / f"bidir_pin25_stage_probe_{arm}.bin"
        module = next(iter(json.loads(routed.read_text(encoding="utf-8"))["modules"].values()))

        control = _cell(module, "X20Y13_IPAD1")
        stage = _cell(module, "X14Y4_SLICE4")
        link = _cell(module, "X0Y4_IOB0")
        observed = _cell(module, "X18Y13_OPAD0")
        assert stage["parameters"]["INIT"] == expected_init
        assert stage["connections"]["I"][2] == control["connections"]["O"][0]
        assert observed["connections"]["I"] == stage["connections"]["F"]
        assert _pips(module, "$iopadmap$drive_low") == INGRESS
        assert _pips(module, "staged") == OE_BRANCH | OBS_BRANCH
        assert _pips(module, "$quad_oe0_identity_NET") == OE_TAIL
        assert _pips(module, "$iopadmap$link") == LINK_INPUT
        assert set(link["connections"]) == {"PAD", "O", "I", "EN"}
        assert link["connections"]["I"] == []
        assert link["attributes"]["AGRV2K_IO_DATA_GND"].endswith("1")
        _cell(module, "X1Y4_SLICE2")
        route_shapes.append({name: _pips(module, name) for name in
                             ("$iopadmap$drive_low", "staged",
                              "$quad_oe0_identity_NET", "$iopadmap$link")})

        with tempfile.TemporaryDirectory(prefix=f"agamemnon-stage-{arm}-") as tmp:
            repack = Path(tmp) / image.name
            env = dict(os.environ, AGAMEMNON_DATA=str(ROOT / "agamemnon" / "chipdb"))
            result = subprocess.run(
                [sys.executable, str(ENGINE / "to_bin.py"), str(routed), str(repack)],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            transcript = result.stdout + result.stderr
            assert result.returncode == 0, transcript
            assert re.search(
                r"data pips: 32 total, 32 mapped .*"
                r"0 legacy-abs, 0 predicted\), 0 unmapped", transcript,
            ), transcript
            assert repack.read_bytes() == image.read_bytes()
        rows.append({"arm": arm, "image_sha256": _sha(image),
                     "routed_sha256": _sha(routed), "mapped_pips": 32})

    # The three images are a single-variable LUT-INIT experiment: placement
    # and all four relevant route trees must be byte-for-byte shape-equivalent.
    assert route_shapes[1:] == route_shapes[:-1]
    return {"result": "pass", "claim": "static-controls-only", "arms": rows}


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tools" / "lab"
    print(json.dumps(audit(directory), indent=2))
