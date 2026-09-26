"""Find synchronous memories with independent read and write address buses.

Small single-address memories can be cheaper as logic. Independent address
buses need a separate read mux and write decoder, making that estimate too
optimistic. Prefer the hard-memory mapper for these shapes without forcing an
unsupported mapping or overriding an explicit source attribute.
"""
import json
from pathlib import Path
import sys


def independent_memories(document):
    selected = []
    for module_name, module in document["modules"].items():
        cells = module.get("cells", {})
        mux_outputs = {}
        for cell in cells.values():
            if cell["type"] != "$mux":
                continue
            ports = cell["connections"]
            # Yosys masks write addresses with X when no write occurs. Remove
            # only that don't-care mask; a real address mux remains distinct.
            for empty, data in (("A", "B"), ("B", "A")):
                if ports[empty] and all(bit == "x" for bit in ports[empty]):
                    mux_outputs.update(zip(ports["Y"], ports[data]))

        def unmask(bits):
            answer = []
            for bit in bits:
                seen = set()
                while isinstance(bit, int) and bit in mux_outputs and bit not in seen:
                    seen.add(bit)
                    bit = mux_outputs[bit]
                answer.append(bit)
            return answer

        for name, cell in cells.items():
            if cell["type"] != "$mem_v2":
                continue
            if any(key in cell.get("attributes", {}) for key in
                   ("ram_style", "rom_style", "ram_block", "ramstyle", "BEL")):
                continue
            params, ports = cell["parameters"], cell["connections"]
            def number(key):
                value = params[key]
                return int(value, 2) if isinstance(value, str) else int(value)
            if (number("RD_PORTS") != 1 or number("WR_PORTS") != 1 or
                    number("RD_CLK_ENABLE") != 1 or number("WR_CLK_ENABLE") != 1 or
                    number("RD_CLK_POLARITY") != number("WR_CLK_POLARITY") or
                    ports["RD_CLK"] != ports["WR_CLK"] or number("SIZE") * number("WIDTH") < 128):
                continue
            read, write = unmask(ports["RD_ADDR"]), unmask(ports["WR_ADDR"])
            # Only independently registered address bits qualify. Combinational
            # address transformations can hide a shared underlying address and
            # require a better cost model rather than a guess here.
            registers = {bit for item in cells.values() if item["type"] in
                         ("$dff", "$dffe", "$sdff", "$sdffe", "$sdffce", "$adff", "$adffe")
                         for bit in item["connections"].get("Q", [])}
            read_bits = {bit for bit in read if isinstance(bit, int)}
            write_bits = {bit for bit in write if isinstance(bit, int)}
            if (read_bits and write_bits and read_bits.isdisjoint(write_bits) and
                    read_bits <= registers and write_bits <= registers):
                selected.append(module_name + "/" + name)
    return selected


if __name__ == "__main__":
    document = json.loads(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text("".join(name + "\n" for name in independent_memories(document)))
