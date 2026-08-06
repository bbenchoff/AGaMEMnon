#!/usr/bin/env python3
"""Attach physical IPAD/OPAD bel constraints to a synthesized generic JSON.

The Python pre-place flow consumes AGAMEMNON_PCF_JSON directly, but a Viaduct
uarch packs before that hook exists.  Encoding the same constraint as the
standard NEXTPNR_BEL cell attribute makes PCF behavior identical in both flows.
"""
import csv
import json
import os
import re
import sys

# Keep direct script entry points working in a clean checkout.  Python otherwise
# puts only this engine directory on sys.path, not the package's repository root.
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

from agamemnon.engine.device import get_device


BOND_MAPS = {
    "AGRV2KL100": "bondmap_L100.csv",
    "AGRV2KL64": "bondmap_L64.csv",
    "AGRV2KL48": "bondmap_L48.csv",
    "AGRV2KQ32": "bondmap_Q32.csv",
}


def main():
    path, pcf_json, data = sys.argv[1:4]
    if os.path.exists(pcf_json):
        constraints = {}
        with open(pcf_json) as f:
            for raw in f:
                fields = raw.split("#", 1)[0].split()
                if not fields:
                    continue
                if len(fields) != 3 or fields[0] != "set_io":
                    raise SystemExit("pcf_bind_json: unsupported PCF line %r" % raw.rstrip())
                constraints[fields[1]] = fields[2]
    else:
        constraints = json.loads(pcf_json)
    device = get_device(os.environ.get("AGAMEMNON_DEVICE"))
    if not device.bond_map_qualified:
        print("WARN: %s physical map is %s; generated image is not silicon-qualified for this package"
              % (device.name, device.bond_map_qualification), file=sys.stderr)
    bond_name = BOND_MAPS[device.name]
    bond_path = os.path.join(data, bond_name)
    if not os.path.exists(bond_path):
        raise SystemExit("pcf_bind_json: physical bond map for %s is not qualified (%s missing)" %
                         (device.name, bond_name))
    bonds = {}
    with open(bond_path) as f:
        for row in csv.DictReader(f):
            bonds[row["pin"].upper()] = (int(row["x"]), int(row["y"]), int(row["z"]))
    bidir_bonds = {}
    bidir_path = os.path.join(data, "physical_iob_L48.csv")
    if device.name == "AGRV2KL48" and os.path.exists(bidir_path):
        with open(bidir_path) as f:
            for row in csv.DictReader(f):
                bidir_bonds[row["pin"].upper()] = (int(row["x"]), int(row["y"]), int(row["z"]))

    with open(path) as f:
        design = json.load(f)
    modules = design["modules"]
    topname = next((n for n, m in modules.items()
                    if str(m.get("attributes", {}).get("top", "0"))
                    in ("1", "00000000000000000000000000000001")), None)
    if topname is None:
        topname = max(modules, key=lambda n: len(modules[n].get("cells", {})))
    top = modules[topname]
    cells = top["cells"]

    def iob_matches(signal):
        """Resolve a scalar PCF name or a Verilog vector bit to its pad cell.

        Yosys iopadmap names ``foo[2:0]`` cells ``foo``, ``foo_1``, and
        ``foo_2`` rather than preserving bracket notation.  Cell-name matching
        therefore cannot bind ordinary PCFs containing ``foo[0]``.  The JSON
        top port and each IOB's PAD connection retain the authoritative bit ID,
        so use that relation for indexed signals.
        """
        exact = [(name, cell) for name, cell in cells.items()
                 if cell.get("type") == "GENERIC_IOB" and name.endswith("." + signal)]
        if exact:
            return exact
        # Yosys names a scalar ``-tinoutpad`` cell ``link[0]`` even though the
        # top-level port and PCF signal are simply ``link``.  Resolve that case
        # through the same authoritative PAD bit relation used for vectors.
        scalar_port = top.get("ports", {}).get(signal)
        if scalar_port is not None and len(scalar_port.get("bits", [])) == 1:
            pad_bit = scalar_port["bits"][0]
            return [(name, cell) for name, cell in cells.items()
                    if cell.get("type") == "GENERIC_IOB"
                    and cell.get("connections", {}).get("PAD") == [pad_bit]]
        match = re.fullmatch(r"(.+)\[(-?\d+)\]", signal)
        if match is None:
            return []
        base, index_text = match.groups()
        port = top.get("ports", {}).get(base)
        if port is None:
            return []
        index = int(index_text)
        offset = int(port.get("offset", 0))
        position = index - offset
        bits = port.get("bits", [])
        if position < 0 or position >= len(bits):
            return []
        pad_bit = bits[position]
        return [(name, cell) for name, cell in cells.items()
                if cell.get("type") == "GENERIC_IOB"
                and cell.get("connections", {}).get("PAD") == [pad_bit]]

    bound = 0
    for signal, pin in constraints.items():
        # PIN_HSE is a dedicated package function, not a general I/O-pad bond.
        # The strict database exposes its already-qualified fabric presentation
        # as CLKIN, so bind that one typed resource explicitly instead of
        # inventing an IOTILE coordinate.  Keep this deliberately L48-only:
        # the other package maps have not been exercised on silicon.
        if pin.upper() == "PIN_HSE":
            if device.name != "AGRV2KL48":
                raise SystemExit("pcf_bind_json: PIN_HSE is not characterized for %s" %
                                 device.name)
            matches = iob_matches(signal)
            if len(matches) != 1:
                raise SystemExit("pcf_bind_json: signal %s matched %d GENERIC_IOB cells" %
                                 (signal, len(matches)))
            name, cell = matches[0]
            ports = cell.get("port_directions", {})
            if ports.get("O") != "output" or ports.get("I") == "input" or ports.get("EN") == "input":
                raise SystemExit("pcf_bind_json: PIN_HSE requires a scalar input signal")
            cell.setdefault("attributes", {})["NEXTPNR_BEL"] = "CLKIN"
            print("PCF JSON bind %s (%s) -> CLKIN [PIN_HSE]" % (signal, name))
            bound += 1
            continue
        xyz = bonds.get(pin.upper())
        if xyz is None:
            raise SystemExit("pcf_bind_json: %s is not bonded in %s" % (pin, bond_name))
        matches = iob_matches(signal)
        if len(matches) != 1:
            raise SystemExit("pcf_bind_json: signal %s matched %d GENERIC_IOB cells" % (signal, len(matches)))
        name, cell = matches[0]
        ports = cell.get("port_directions", {})
        is_bidir = (ports.get("O") == "output" and ports.get("I") == "input"
                    and ports.get("EN") == "input")
        characterized_xyz = bidir_bonds.get(pin.upper())
        if is_bidir and characterized_xyz is not None:
            if characterized_xyz != xyz:
                raise SystemExit("pcf_bind_json: combined-I/O characterization/bond mismatch for %s" % pin)
            kind = "IOB"
        elif not is_bidir and characterized_xyz is not None and xyz[0] == 0:
            # The strict L48 database exposes characterized combined IOB sites
            # at the left-edge bonds. Scalar input/output cells use the same
            # physical site; binding them to synthetic IPAD/OPAD names makes
            # nextpnr abort because those separate bels do not exist there.
            if characterized_xyz != xyz:
                raise SystemExit("pcf_bind_json: combined-I/O characterization/bond mismatch for %s" % pin)
            kind = "IOB"
        elif is_bidir:
            if characterized_xyz is None:
                raise SystemExit("pcf_bind_json: bidirectional pin %s is not characterized for %s" %
                                 (pin, device.name))
        elif ports.get("O") == "output":
            kind = "IPAD"
        elif ports.get("I") == "input":
            kind = "OPAD"
        else:
            raise SystemExit("pcf_bind_json: cannot determine direction of %s" % signal)
        x, y, z = xyz
        bel = "X%dY%d_%s%d" % (x, y, kind, z)
        cell.setdefault("attributes", {})["NEXTPNR_BEL"] = bel
        print("PCF JSON bind %s (%s) -> %s" % (signal, name, bel))
        bound += 1

    with open(path, "w") as f:
        json.dump(design, f)
    print("pcf_bind_json: bound %d I/O cell(s)" % bound)


if __name__ == "__main__":
    main()
