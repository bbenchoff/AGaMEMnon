#!/usr/bin/env python3
"""Measure the safe constant-0/constant-1 PIN_25 OE-source differential.

Pico GP12 (PIN_25) and GP8 (PIN_18 readback) remain inputs for the entire run.
No Pico GPIO is driven.  Both FPGA images have a local hard-zero data source,
so the only possible FPGA behaviours are release or drive-low.  Images are
loaded to SRAM only; flash is never written.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from measure_bidir_pin25_campaign import (
    LINE_GP, OBSERVED_GP, ROOT, _get, _load, _openocd, _pico,
)


def run(directory: Path, port: str) -> dict:
    result = {"hardware": True, "sram_only": True, "flash_written": False,
              "pico_outputs": [], "arms": {}}
    try:
        _pico(port, ["ALLIN"])
        for arm in ("const0", "const1"):
            image = directory / f"bidir_pin25_oe_{arm}.bin"
            fcb = _load(image)
            rows = []
            for pull in ("d", "u"):
                # _get only SETs GP4 because it is shared with the prior runner;
                # avoid it here: this experiment has no external control.
                replies = _pico(port, ["MODE 12 " + pull, "GET 12", "GET 8"])
                values = {}
                for command, reply in replies:
                    if command.startswith("GET "):
                        pin = int(command.split()[1])
                        values[pin] = int(reply.rsplit("=", 1)[1])
                assert set(values) == {LINE_GP, OBSERVED_GP}, values
                rows.append({"pull": pull, "observed": values})
            result["arms"][arm] = {"fcb": fcb, "rows": rows}
        a = result["arms"]["const0"]["rows"]
        b = result["arms"]["const1"]["rows"]
        result["causal_change"] = a != b
        result["result"] = "pass" if a != b else "bounded-negative"
        return result
    finally:
        try:
            _pico(port, ["ALLIN"])
        finally:
            _openocd(["init", "reset halt", "reset run", "shutdown"], tolerate=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path,
                        default=ROOT / "tools" / "lab")
    parser.add_argument("--port", default="COM6")
    args = parser.parse_args()
    print(json.dumps(run(args.directory.resolve(), args.port), indent=2, sort_keys=True))
    print("Pico ALLIN, AG32 reset/run, board token may be released")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
