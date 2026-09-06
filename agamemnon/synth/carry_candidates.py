"""Physical costs of coarse Yosys ALUs before irreversible carry mapping."""
import json
import sys


def candidates(document):
    for module_name, module in document.get("modules", {}).items():
        cells = module.get("cells", {})
        used = {bit for cell in cells.values()
                for port, bits in cell.get("connections", {}).items()
                if cell.get("port_directions", {}).get(port) in ("input", "inout")
                for bit in bits if type(bit) is int}
        used.update(bit for port in module.get("ports", {}).values()
                    if port.get("direction") in ("output", "inout")
                    for bit in port.get("bits", []) if type(bit) is int)
        for name, cell in cells.items():
            if cell.get("type") != "$alu":
                continue
            value = cell["parameters"]["Y_WIDTH"]
            width = value if isinstance(value, int) else int(value, 2)
            carry = cell.get("connections", {}).get("CO", [])
            if not 1 <= width <= 32 or len(carry) != width:
                continue
            # A physical chain has no independent interior carry taps. Leave
            # such an ALU to the general techmap rather than changing its uses.
            if any(bit in used for bit in carry[:-1]):
                continue
            cost = width + 1 + int(carry[-1] in used)  # seed and optional export
            path = module_name + "/" + name
            if cost <= 33 and not any(c in path for c in "\t\r\n"):
                yield width, path, cost


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as stream:
        for width, path, cost in candidates(json.load(stream)):
            print("%d\t%d\t%s" % (width, cost, path))
