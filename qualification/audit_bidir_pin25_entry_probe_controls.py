#!/usr/bin/env python3
"""Static audit for the qualified PIN10 entry-boundary control matrix."""

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
ARMS = {"external": "1111111100000000", "const0": "0" * 16, "const1": "1" * 16}
INGRESS = {
    "X20Y13_InputMUX02.X20Y12_RMUX15",
    "X20Y12_RMUX15.X19Y12_RMUX53",
    "X19Y12_RMUX53.X19Y12_IMUX11",
}
STAGE_FANOUT = {
    "X19Y12_OMUX08.X19Y12_RMUX03",
    "X19Y12_RMUX03.X15Y12_RMUX14",
    "X15Y12_RMUX14.X15Y8_RMUX50",
    "X15Y8_RMUX50.X15Y4_RMUX13",
    "X15Y4_RMUX13.X11Y4_RMUX48",
    "X11Y4_RMUX48.X10Y4_IMUX00",
    "X19Y12_RMUX03.X18Y12_RMUX14",
    "X18Y12_RMUX14.X18Y11_RMUX56",
    "X18Y11_RMUX56.X14Y11_RMUX27",
    "X14Y11_RMUX27.X14Y9_RMUX15",
    "X14Y9_RMUX15.X18Y9_RMUX69",
    "X18Y9_RMUX69.X18Y13_RMUX28",
    "X18Y13_RMUX28.X18Y13_IOMUX00",
}
OE_TAIL = {
    "X10Y4_OMUX02.X10Y4_RMUX08", "X10Y4_RMUX08.X11Y4_RMUX26",
    "X11Y4_RMUX26.X8Y4_RMUX13", "X8Y4_RMUX13.X4Y4_RMUX49",
    "X4Y4_RMUX49.X0Y4_RMUX00", "X0Y4_RMUX00.X0Y4_IOMUX06",
}
LINK_INPUT = {"X0Y4_InputMUX00.X1Y4_RMUX11", "X1Y4_RMUX11.X1Y4_IMUX09"}


def _pips(module: dict, name: str) -> set[str]:
    fields = module["netnames"][name]["attributes"].get("ROUTING", "").split(";")
    return {fields[i] for i in range(1, len(fields), 3) if fields[i]}


def _cell(module: dict, bel: str) -> dict:
    rows = [cell for cell in module["cells"].values()
            if cell.get("attributes", {}).get("NEXTPNR_BEL") == bel]
    assert len(rows) == 1, (bel, len(rows))
    return rows[0]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory: Path) -> dict:
    rows, shapes = [], []
    for arm, init in ARMS.items():
        routed = directory / f"bidir_pin25_entry_probe_{arm}_routed.json"
        image = directory / f"bidir_pin25_entry_probe_{arm}.bin"
        module = next(iter(json.loads(routed.read_text(encoding="utf-8"))["modules"].values()))
        control = _cell(module, "X20Y13_IPAD1")
        stage = _cell(module, "X19Y12_SLICE2")
        link = _cell(module, "X0Y4_IOB0")
        observed = _cell(module, "X18Y13_OPAD0")
        assert stage["parameters"]["INIT"] == init
        assert stage["connections"]["I"][3] == control["connections"]["O"][0]
        assert observed["connections"]["I"] == stage["connections"]["F"]
        assert _pips(module, "$iopadmap$drive_low") == INGRESS
        assert _pips(module, "staged") == STAGE_FANOUT
        assert _pips(module, "$quad_oe0_identity_NET") == OE_TAIL
        assert _pips(module, "$iopadmap$link") == LINK_INPUT
        assert link["connections"]["I"] == []
        assert link["attributes"]["AGRV2K_IO_DATA_GND"].endswith("1")
        shape = {name: _pips(module, name) for name in
                 ("$iopadmap$drive_low", "staged", "$quad_oe0_identity_NET", "$iopadmap$link")}
        shapes.append(shape)
        with tempfile.TemporaryDirectory(prefix=f"agamemnon-entry-{arm}-") as tmp:
            repack = Path(tmp) / image.name
            env = dict(os.environ, AGAMEMNON_DATA=str(ROOT / "agamemnon" / "chipdb"))
            result = subprocess.run(
                [sys.executable, str(ENGINE / "to_bin.py"), str(routed), str(repack)],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            transcript = result.stdout + result.stderr
            assert result.returncode == 0, transcript
            assert re.search(r"data pips: 32 total, 32 mapped .*0 legacy-abs, 0 predicted\), 0 unmapped",
                             transcript), transcript
            assert repack.read_bytes() == image.read_bytes()
        rows.append({"arm": arm, "image_sha256": _sha(image),
                     "routed_sha256": _sha(routed), "mapped_pips": 32})
    assert shapes[1:] == shapes[:-1]
    return {"result": "pass", "claim": "qualified-entry-static-control", "arms": rows}


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tools" / "lab"
    print(json.dumps(audit(directory), indent=2))
