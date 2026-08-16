#!/usr/bin/env python3
"""Fail-closed static audit for the PIN10 -> PIN25 vendor-stage diagnostic.

This image changes one architectural boundary relative to the failed direct
external-OE arm: PIN10 is re-buffered through the vendor-observed X14Y4 slice4
before entering the already-qualified X10Y4 presentation LUT and PIN25 OE
corridor.  This checker proves that exact route, release-or-drive-low safety,
zero selector debt, and a byte-identical fresh repack.  It makes no electrical
claim; a separately controlled SRAM-only board A/B decides conduction.
"""

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
INGRESS_PIPS = {
    "X20Y13_InputMUX02.X20Y12_RMUX20",
    "X20Y12_RMUX20.X18Y12_RMUX80",
    "X18Y12_RMUX80.X18Y8_RMUX43",
    "X18Y8_RMUX43.X14Y8_RMUX73",
    "X14Y8_RMUX73.X14Y4_RMUX22",
    "X14Y4_RMUX22.X14Y4_IMUX18",
}
STAGE_PIPS = {
    "X14Y4_OMUX14.X14Y4_RMUX43",
    "X14Y4_RMUX43.X10Y4_RMUX94",
    "X10Y4_RMUX94.X10Y4_IMUX00",
}
OE_PIPS = {
    "X10Y4_OMUX02.X10Y4_RMUX08",
    "X10Y4_RMUX08.X11Y4_RMUX26",
    "X11Y4_RMUX26.X8Y4_RMUX13",
    "X8Y4_RMUX13.X4Y4_RMUX49",
    "X4Y4_RMUX49.X0Y4_RMUX00",
    "X0Y4_RMUX00.X0Y4_IOMUX06",
}
INPUT_PIPS = {
    "X0Y4_InputMUX00.X1Y4_RMUX11",
    "X1Y4_RMUX11.X1Y4_IMUX09",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pips(module: dict, net: str) -> set[str]:
    fields = module["netnames"][net]["attributes"]["ROUTING"].split(";")
    return {fields[index] for index in range(1, len(fields), 3) if fields[index]}


def _cell(module: dict, bel: str) -> tuple[str, dict]:
    rows = [(name, cell) for name, cell in module["cells"].items()
            if cell.get("attributes", {}).get("NEXTPNR_BEL") == bel]
    assert len(rows) == 1, (bel, [name for name, _cell in rows])
    return rows[0]


def audit(directory: Path) -> dict:
    routed = directory / "bidir_pin25_oe_vendor_stage_routed.json"
    image = directory / "bidir_pin25_oe_vendor_stage.bin"
    design = json.loads(routed.read_text(encoding="utf-8"))
    module = next(iter(design["modules"].values()))

    # The only physical control input is PIN10 and it takes the exact retained
    # target branch to X14Y4 slice4 input I2.
    _, control = _cell(module, "X20Y13_IPAD1")
    assert set(control["connections"]) == {"PAD", "O"}
    assert _pips(module, "$iopadmap$drive_low") == INGRESS_PIPS
    _, stage = _cell(module, "X14Y4_SLICE4")
    assert stage["parameters"]["INIT"] == "1111000011110000"
    assert stage["connections"]["I"][2] == control["connections"]["O"][0]
    assert _pips(module, "staged") == STAGE_PIPS

    # X10Y4 is a transparent presentation boundary, followed by the exact
    # silicon-qualified six-pip OE tail.
    _, presentation = _cell(module, "X10Y4_SLICE0")
    assert presentation["parameters"]["INIT"] == "1010101010101010"
    assert presentation["connections"]["I"][0] == stage["connections"]["F"][0]
    assert _pips(module, "$quad_oe0_identity_NET") == OE_PIPS

    # Electrical safety is structural: PIN25 can only release or drive a local
    # hard zero.  Its input corridor and PIN18 observation output are retained.
    _, link = _cell(module, "X0Y4_IOB0")
    assert set(link["connections"]) == {"PAD", "O", "I", "EN"}
    assert link["connections"]["I"] == []
    assert link["attributes"]["AGRV2K_IO_DATA_GND"].endswith("1")
    assert link["connections"]["EN"] == presentation["connections"]["F"]
    assert _pips(module, "$iopadmap$link") == INPUT_PIPS
    _cell(module, "X1Y4_SLICE2")
    _, observed = _cell(module, "X18Y13_OPAD0")
    assert set(observed["connections"]) == {"PAD", "I"}
    assert "X18Y13_RMUX28.X18Y13_IOMUX00" in _pips(module, "$iopadmap$observed")

    with tempfile.TemporaryDirectory(prefix="agamemnon-pin25-vendor-stage-") as tmp:
        repack = Path(tmp) / image.name
        env = dict(os.environ, AGAMEMNON_DATA=str(ROOT / "agamemnon" / "chipdb"))
        result = subprocess.run(
            [sys.executable, str(ENGINE / "to_bin.py"), str(routed), str(repack)],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        transcript = result.stdout + result.stderr
        assert result.returncode == 0, transcript
        assert re.search(
            r"data pips: 36 total, 36 mapped .*"
            r"0 legacy-abs, 0 predicted\), 0 unmapped", transcript,
        ), transcript
        assert repack.read_bytes() == image.read_bytes()

    return {
        "result": "pass",
        "image_sha256": _sha256(image),
        "routed_sha256": _sha256(routed),
        "mapped_pips": 36,
        "electrical_safety": "release-or-drive-low-only",
        "claim": "static-route-audit-only",
    }


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tools" / "lab"
    print(json.dumps(audit(directory), indent=2))
