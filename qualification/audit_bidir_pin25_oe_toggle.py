#!/usr/bin/env python3
"""Fail-closed static audit for the local self-toggling PIN_25 OE image."""

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
INPUT_PIPS = {"X0Y4_InputMUX00.X1Y4_RMUX11", "X1Y4_RMUX11.X1Y4_IMUX09"}
OE_PIPS = {
    "X10Y4_OMUX02.X10Y4_RMUX08", "X10Y4_RMUX08.X11Y4_RMUX26",
    "X11Y4_RMUX26.X8Y4_RMUX13", "X8Y4_RMUX13.X4Y4_RMUX49",
    "X4Y4_RMUX49.X0Y4_RMUX00", "X0Y4_RMUX00.X0Y4_IOMUX06",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pips(module: dict, net: str) -> set[str]:
    fields = module["netnames"][net]["attributes"]["ROUTING"].split(";")
    return {fields[i] for i in range(1, len(fields), 3) if fields[i]}


def _at(module: dict, bel: str) -> list[tuple[str, dict]]:
    return [(name, cell) for name, cell in module["cells"].items()
            if cell.get("attributes", {}).get("NEXTPNR_BEL") == bel]


def audit(directory: Path) -> dict:
    routed = directory / "bidir_pin25_oe_toggle_routed.json"
    image = directory / "bidir_pin25_oe_toggle.bin"
    design = json.loads(routed.read_text(encoding="utf-8"))
    module = next(iter(design["modules"].values()))

    # The physical site can never drive high.
    link = _at(module, "X0Y4_IOB0")
    assert len(link) == 1
    link = link[0][1]
    assert set(link["connections"]) == {"PAD", "I", "O", "EN"}
    assert link["connections"]["I"] == []
    assert link["attributes"]["AGRV2K_IO_DATA_GND"].endswith("1")

    # Exact input and OE corridors are identical to the causal constant A/B.
    assert _pips(module, "$iopadmap$link") == INPUT_PIPS
    presentation = _at(module, "X10Y4_SLICE0")
    assert len(presentation) == 1
    presentation = presentation[0][1]
    assert presentation["parameters"]["INIT"] == "1010101010101010"
    assert presentation["connections"]["F"] == link["connections"]["EN"]
    assert _pips(module, "$quad_oe0_identity_NET") == OE_PIPS

    # One previously qualified direct-feedback TFF produces drive_low.  Its
    # combinational next-state LUT is fixed at slice7; its registered Q lives
    # at slice0.  The presentation-buffer input is the same drive_low net.
    next_state = _at(module, "X14Y11_SLICE7")
    assert len(next_state) == 1
    next_state = next_state[0][1]
    assert next_state["parameters"]["INIT"] == "0000000011111111"
    assert next_state["connections"]["I"][3] in module["netnames"]["state"]["bits"]
    registered = _at(module, "X14Y11_SLICE0")
    assert len(registered) == 1
    registered = registered[0][1]
    assert registered["parameters"]["FF_USED"].endswith("1")
    assert registered["connections"]["Q"] == module["netnames"]["state"]["bits"]
    clock = module["netnames"]["$iopadmap$clk"]
    assert registered["connections"]["CLK"] == clock["bits"]
    assert "GCLK0.X14Y11_ClkMUX00" in clock["attributes"]["ROUTING"]
    assert presentation["connections"]["I"][0] == module["netnames"]["drive_low"]["bits"][0]
    assert _at(module, "CLKIN")

    # Readback exits on the existing qualified PIN_18 surface.
    observed = _at(module, "X18Y13_OPAD0")
    assert len(observed) == 1 and set(observed[0][1]["connections"]) == {"PAD", "I"}
    assert "X18Y13_RMUX28.X18Y13_IOMUX00" in _pips(module, "$iopadmap$observed")

    with tempfile.TemporaryDirectory(prefix="agamemnon-pin25-toggle-") as tmp:
        repack = Path(tmp) / image.name
        env = dict(os.environ, AGAMEMNON_DATA=str(ROOT / "agamemnon" / "chipdb"))
        result = subprocess.run(
            [sys.executable, str(ENGINE / "to_bin.py"), str(routed), str(repack)],
            cwd=ROOT, env=env, capture_output=True, text=True)
        transcript = result.stdout + result.stderr
        assert result.returncode == 0, transcript
        assert re.search(r"data pips: 41 total, 41 mapped .*0 legacy-abs, 0 predicted\), 0 unmapped", transcript), transcript
        assert repack.read_bytes() == image.read_bytes()

    return {"result": "pass", "image_sha256": _sha(image),
            "routed_sha256": _sha(routed), "mapped_pips": 41,
            "electrical_safety": "release-or-drive-low-only"}


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tools" / "lab"
    print(json.dumps(audit(directory), indent=2))
