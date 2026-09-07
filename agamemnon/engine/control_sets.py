"""Count register control sets and check them against the per-tile control budget.

A LogicTile carries a small fixed number of shared control lines, and each slice
selects which of them it uses.  The decoded tile template
(``agamemnon/chipdb/logictile_config_template.csv``, rows W32-W35) lays them out
in four families, each split into two equal groups -- two lines per tile per
family:

===================  =====  ==============================  =====
family               bits   layout                          lines
===================  =====  ==============================  =====
``CFG_TILECLKMUX``       8  rows W32/W35, 4 bits each           2
``CFG_TILEASYNCMUX``     8  rows W33/W34, 4 bits each           2
``CFG_TILECLKENMUX``     6  rows W32/W35, 3 bits each           2
``CFG_TILESYNCMUX``      6  rows W33/W34, 3 bits each           2
``CFG_CTRLMUX``         48  16 slices x 3 bits                  --
===================  =====  ==============================  =====

The two-line reading is anchored on ``CFG_TILEASYNCMUX``, whose two-asynchronous-
lines-per-tile behaviour is independently established; the other three families
share its exact split shape.

Why this matters: a register control that is *not* carried on one of these lines
has to be lowered into the D-path, which turns a signal shared by every register
in the design into an ordinary high-fanout fabric net.  Such a net cannot be
confined to a tile, so it inflates routing demand for the whole design.  Whether
that lowering is avoidable is a counting question -- does the design's control-set
demand fit the budget? -- and this module answers it from a netlist, before
packing.

The budget check is necessary, not sufficient: fitting the per-tile line count
says nothing about whether a legal placement exists that groups the right
registers together, nor about codeword evidence for the selectors involved.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass


CONTROL_SET_SCHEMA = "agamemnon.control-sets.v1"

#: Shared control lines available per LogicTile, by family.
TILE_CONTROL_BUDGET = {
    "clock": 2,
    "async": 2,
    "sync": 2,
    "enable": 2,
}

# Port names that carry each control family on a register-like cell.  Both the
# vendor primitive spelling and the generic nextpnr spelling are accepted so the
# same check works either side of a mapping change.
_PORT_FAMILY = {
    "clock": ("CLK", "CLOCK", "C"),
    "enable": ("ENA", "EN", "CE"),
    "sync": ("SCLR", "SR", "SRST", "SLOAD"),
    "async": ("CLRN", "ACLR", "ALOAD", "PRN", "R"),
}

#: Constant tie-offs: a control held at a constant needs no shared line.
_CONSTANT = frozenset({"1'h1", "1'h0", "1", "0", "vcc", "gnd", "$true", "$false", ""})


@dataclass(frozen=True)
class ControlSet:
    """One distinct combination of control signals."""

    clock: str
    enable: str
    sync: str
    asynchronous: str

    def signals(self):
        return {
            "clock": self.clock,
            "enable": self.enable,
            "sync": self.sync,
            "async": self.asynchronous,
        }


@dataclass(frozen=True)
class ControlSetReport:
    registers: int
    counts: dict            # ControlSet -> register count
    distinct_signals: dict  # family -> set of non-constant signal names

    @property
    def distinct_sets(self):
        return len(self.counts)

    def demand(self):
        """Lines needed per family, ignoring constant tie-offs."""
        return {family: len(names) for family, names in self.distinct_signals.items()}

    def fits_budget(self, budget=None):
        """Whether every family's demand is within one tile's line count.

        A design whose whole-design demand fits the per-tile budget can, in
        principle, carry every control on a shared line without lowering any of
        them into the D-path.  Exceeding it does not make native controls
        impossible -- registers can be grouped so each tile sees at most the
        budget -- but it does mean packing has to partition by control set.
        """
        budget = budget or TILE_CONTROL_BUDGET
        demand = self.demand()
        return all(demand.get(f, 0) <= limit for f, limit in budget.items())

    def over_budget(self, budget=None):
        budget = budget or TILE_CONTROL_BUDGET
        demand = self.demand()
        return {f: (demand.get(f, 0), limit)
                for f, limit in budget.items() if demand.get(f, 0) > limit}

    def as_dict(self):
        return {
            "schema": CONTROL_SET_SCHEMA,
            "registers": self.registers,
            "distinct_sets": self.distinct_sets,
            "demand": self.demand(),
            "budget": dict(TILE_CONTROL_BUDGET),
            "fits_tile_budget": self.fits_budget(),
            "over_budget": {f: {"needed": n, "available": a}
                            for f, (n, a) in self.over_budget().items()},
            "sets": [
                {"signals": cs.signals(), "registers": n}
                for cs, n in sorted(self.counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
            ],
        }


def _is_constant(signal):
    return signal is None or str(signal).strip().lower() in _CONSTANT


def control_sets(registers):
    """Summarise an iterable of ``{family: signal}`` register control mappings."""
    counts = collections.Counter()
    distinct = {family: set() for family in _PORT_FAMILY}
    total = 0
    for mapping in registers:
        total += 1
        resolved = {}
        for family in _PORT_FAMILY:
            signal = mapping.get(family)
            signal = "" if _is_constant(signal) else str(signal).strip()
            resolved[family] = signal
            if signal:
                distinct[family].add(signal)
        counts[ControlSet(resolved["clock"], resolved["enable"],
                          resolved["sync"], resolved["async"])] += 1
    return ControlSetReport(registers=total, counts=dict(counts), distinct_signals=distinct)


def _top_module(document):
    modules = document.get("modules") or {}
    if not modules:
        raise ValueError("document contains no modules")
    return max(modules.values(), key=lambda m: len(m.get("cells") or {}))


def control_sets_from_document(document):
    """Extract control sets from a nextpnr/yosys JSON document.

    A cell counts as a register if it drives any recognised clock port.  Signals
    are identified by net bit, so this works before net names are assigned.
    """
    module = _top_module(document)
    bit_to_net = {}
    for name, netname in (module.get("netnames") or {}).items():
        for bit in netname.get("bits") or ():
            if isinstance(bit, int):
                bit_to_net[bit] = name

    def signal_for(cell, ports):
        for port in ports:
            bits = (cell.get("connections") or {}).get(port)
            if not bits:
                continue
            bit = bits[0]
            if isinstance(bit, str):          # a literal "0"/"1" tie-off
                return None
            return bit_to_net.get(bit, "bit%d" % bit)
        return None

    registers = []
    for cell in (module.get("cells") or {}).values():
        clock = signal_for(cell, _PORT_FAMILY["clock"])
        if clock is None:
            continue
        registers.append({
            "clock": clock,
            "enable": signal_for(cell, _PORT_FAMILY["enable"]),
            "sync": signal_for(cell, _PORT_FAMILY["sync"]),
            "async": signal_for(cell, _PORT_FAMILY["async"]),
        })
    return control_sets(registers)


def format_report(report):
    lines = [
        "registers            : %d" % report.registers,
        "distinct control sets: %d" % report.distinct_sets,
        "demand vs budget     :",
    ]
    demand = report.demand()
    for family, limit in sorted(TILE_CONTROL_BUDGET.items()):
        need = demand.get(family, 0)
        mark = "ok" if need <= limit else "OVER"
        lines.append("    %-8s %d needed / %d per tile   %s" % (family, need, limit, mark))
    lines.append("fits per-tile budget : %s" % ("yes" if report.fits_budget() else "no"))
    return "\n".join(lines)
