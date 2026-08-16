#!/usr/bin/env python3
"""SRAM-only measurement for the audited local self-toggling PIN_25 OE image.

GP12 (PIN_25) and GP8 (PIN_18 readback) remain inputs.  No Pico GPIO is ever
driven.  Under pull-up, both pins must report edges; under pull-down PIN_25 must
remain low while the fabric-side inverted readback may remain high.  The image
can only release PIN_25 or drive it low.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from measure_bidir_pin25_campaign import ROOT, _load, _openocd, _pico


def _edges(port: str, pin: int) -> dict:
    reply = _pico(port, [f"EDGES {pin} 200000 0"])[0][1]
    match = re.fullmatch(r"EDGES GP(\d+) n=(\d+) us=(\d+) edges=(\d+) elapsed-us=(\d+)", reply)
    assert match and int(match.group(1)) == pin, reply
    return {"pin": pin, "edges": int(match.group(4)),
            "elapsed_us": int(match.group(5))}


def run(directory: Path, port: str) -> dict:
    try:
        _pico(port, ["ALLIN"])
        fcb = _load(directory / "bidir_pin25_oe_toggle.bin")
        rows = []
        for pull in ("d", "u"):
            _pico(port, ["MODE 12 " + pull])
            rows.append({"pull": pull, "GP12": _edges(port, 12),
                         "GP8": _edges(port, 8)})
        pad_dynamic = (rows[0]["GP12"]["edges"] == 0 and
                       rows[1]["GP12"]["edges"] > 0)
        readback_dynamic = rows[1]["GP8"]["edges"] > 0
        result = ("pass_dynamic_oe_pad_and_readback" if pad_dynamic and readback_dynamic
                  else "pass_dynamic_oe_pad_readback_unqualified" if pad_dynamic
                  else "fail_dynamic_oe_pad")
        return {"result": result, "pad_dynamic_oe": pad_dynamic,
                "simultaneous_dynamic_readback": readback_dynamic,
                "hardware": True, "sram_only": True,
                "flash_written": False, "pico_outputs": [], "fcb": fcb,
                "rows": rows}
    finally:
        try:
            _pico(port, ["ALLIN"])
        finally:
            _openocd(["init", "reset halt", "reset run", "shutdown"], tolerate=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "tools" / "lab")
    parser.add_argument("--port", default="COM6")
    args = parser.parse_args()
    print(json.dumps(run(args.directory.resolve(), args.port), indent=2, sort_keys=True))
    print("Pico ALLIN, AG32 reset/run, board token may be released")
