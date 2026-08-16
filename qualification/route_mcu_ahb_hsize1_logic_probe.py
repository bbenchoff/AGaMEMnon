#!/usr/bin/env python3
"""Write the retained exact HSIZE1 discriminator route.

The script operates on synthesized JSON because it is a qualification replay,
not a replacement router. The ordinary architecture also exposes these three
edges; retaining the exact JSON makes the silicon observation byte-reproducible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


HSIZE_ROUTE = (
    "X14Y12_IMUX14;X14Y12_RMUX34.X14Y12_IMUX14;5;"
    "X14Y12_RMUX34;X13Y12_InputMUX05.X14Y12_RMUX34;5;"
    "X13Y12_InputMUX05;X13Y12_BufMUX04.X13Y12_InputMUX05;5;"
    "X13Y12_BufMUX04;;5"
)
OBSERVED_ROUTE = (
    "X0Y5_SinkMUXPseudo02;X13Y12_BBMUXE02.X0Y5_SinkMUXPseudo02;5;"
    "X13Y12_BBMUXE02;X14Y12_RMUX03.X13Y12_BBMUXE02;5;"
    "X14Y12_RMUX03;X14Y12_OMUX11.X14Y12_RMUX03;1;"
    "X14Y12_OMUX11;;1"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="synthesized JSON")
    parser.add_argument("output", type=Path, help="routed JSON")
    args = parser.parse_args()

    design = json.loads(args.input.read_text(encoding="utf-8"))
    top = design["modules"]["top"]
    cells, nets = top["cells"], top["netnames"]
    required = {"hsize1_identity", "mcu_hsize1", "mcu_h0"}
    if not required <= set(cells) or not {"hsize1", "observed"} <= set(nets):
        raise SystemExit("input is not the HSIZE1 discriminator netlist")

    for name, bel in {
        "hsize1_identity": "X14Y12_SLICE3",
        "mcu_hsize1": "X10Y5_MCU_AHB_HSIZE1105",
        "mcu_h0": "X10Y5_MCU_DOUT10",
    }.items():
        cells[name]["attributes"].update({
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": "00000000000000000000000000000101",
        })
    nets["hsize1"].setdefault("attributes", {})["ROUTING"] = HSIZE_ROUTE
    nets["observed"].setdefault("attributes", {})["ROUTING"] = OBSERVED_ROUTE
    args.output.write_text(
        json.dumps(design, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
