#!/usr/bin/env python3
"""Reproduce the silicon-qualified aligned-halfword bank16 checkpoint."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_register_bank16_word_byte_waited_routed.json"
DEFAULT_OUT = HERE / "mcu_ahb_register_bank16_word_byte_halfword_waited_routed.json"
BASE_SHA256 = "87473ec45b9af35e0158b7ba31bd908dee4a0d4fe494a883b6eb5e0ed516fc7c"
ROUTED_SHA256 = "2b70e625bf82f71c6fda3f50f1467a25adbfce81716d47a1809d7b483c62802a"
HSIZE0 = 303960


def triples(net):
    fields = net["attributes"]["ROUTING"].split(";")
    if len(fields) % 3:
        raise SystemExit("malformed retained route")
    return [fields[index:index + 3] for index in range(0, len(fields), 3)]


def encode(items):
    return ";".join(value for item in items for value in item)


def edit(net, *, remove=(), add=()):
    remove = set(remove)
    items = triples(net)
    found = {item[1] for item in items if item[1] in remove}
    if found != remove:
        raise SystemExit("route removal mismatch: %r" % (remove - found))
    items = [item for item in items if item[1] not in remove]
    present = {item[1] for item in items}
    for source, destination, strength in add:
        pip = "%s.%s" % (source, destination)
        if pip not in present:
            items.insert(0, [destination, pip, str(strength)])
    net["attributes"]["ROUTING"] = encode(items)


def route(source, edges, strength=5):
    return encode([[destination, "%s.%s" % (start, destination), str(strength)]
                   for start, destination in edges] + [[source, "", str(strength)]])


def compose():
    raw = BASE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != BASE_SHA256:
        raise SystemExit("word/byte base hash mismatch: %s" % digest)
    design = json.loads(raw)
    top = design["modules"]["top"]
    cells, nets = top["cells"], top["netnames"]
    if any(HSIZE0 in net.get("bits", []) for net in nets.values()):
        raise SystemExit("HSIZE0 bit is already occupied")
    if any(cell.get("type") == "MCU_AHB_HSIZE0" for cell in cells.values()):
        raise SystemExit("HSIZE0 cell is already present")

    hsize0_cell = copy.deepcopy(cells["mcu_hsize1"])
    hsize0_cell["type"] = "MCU_AHB_HSIZE0"
    hsize0_cell["connections"] = {"DIN": [HSIZE0]}
    hsize0_cell["attributes"].update({
        "NEXTPNR_BEL": "X10Y5_MCU_AHB_HSIZE0104",
        "hdlname": "mcu_hsize0",
    })
    cells["mcu_hsize0"] = hsize0_cell
    nets["hsize0"] = {
        "hide_name": 0,
        "bits": [HSIZE0],
        "attributes": {"ROUTING": route("X13Y12_BufMUX03", [
            ("X13Y12_BufMUX03", "X13Y12_InputMUX03"),
            ("X13Y12_InputMUX03", "X14Y12_RMUX41"),
            ("X14Y12_RMUX41", "X14Y12_IMUX15"),
        ])},
    }

    high = cells["high_request"]
    if high["connections"]["I"] != [303953, 303954, 303955, 302818]:
        raise SystemExit("high-request input contract changed")
    high["connections"]["I"] = [303953, 303954, 303955, HSIZE0]
    # I=[A0,A1,HSIZE1,HSIZE0]: !A1 & (A0 | HSIZE1 | HSIZE0).
    high["parameters"]["INIT"] = format(0x3332, "016b")

    buffer_cell = cells["high_request_buffer"]
    if buffer_cell["connections"]["I"] != ["0", 303957, "0", "0"]:
        raise SystemExit("high-request buffer input contract changed")
    buffer_cell["connections"]["I"] = ["0", 303957, 302818, "0"]
    # I=[0,predecode,HTRANS1,0]: predecode & HTRANS1.
    buffer_cell["parameters"]["INIT"] = format(0xC0C0, "016b")

    edit(nets["htrans1"], remove={
        "X14Y9_RMUX55.X14Y12_RMUX47",
        "X14Y12_RMUX47.X14Y12_IMUX15",
    }, add=[
        ("X15Y8_RMUX02", "X15Y9_RMUX19", 5),
        ("X15Y9_RMUX19", "X15Y12_RMUX94", 5),
        ("X15Y12_RMUX94", "X15Y12_IMUX58", 5),
    ])
    return design


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    encoded = (json.dumps(compose(), indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != ROUTED_SHA256:
        raise SystemExit("composed routed hash mismatch: %s" % digest)
    args.out.write_bytes(encoded)
    print("%s  %s" % (digest, args.out))


if __name__ == "__main__":
    main()
