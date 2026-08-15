"""Resolve PCF signal names against the port names yosys actually emits.

`iopadmap` does not preserve bracket notation.  The bits of ``output [3:0] led``
arrive as pad cells named ``led``, ``led_1``, ``led_2``, ``led_3``, so an
ordinary IceStorm-style ``set_io led[0] PIN_25`` matches no cell by name.  The
pre-place hook used to skip such a constraint silently, leave the pad to the
placer, and fail much later with an unrelated bel error -- nothing ever said the
constraint had been ignored.

This module holds only the name relation, so it can be tested without a nextpnr
context.  The authoritative resolution for the uarch flow lives in
``pcf_bind_json.py``, which has the JSON port bit IDs available and uses those;
this is the same relation expressed for the flow that does not.
"""
from __future__ import annotations

import re


_INDEXED = re.compile(r"(.+)\[(\d+)\]")


def alias_candidates(key):
    """Port names that a PCF signal name may appear as, most exact first.

    >>> alias_candidates("o_pin18")
    ['o_pin18']
    >>> alias_candidates("led[0]")
    ['led[0]', 'led']
    >>> alias_candidates("led[3]")
    ['led[3]', 'led_3']
    """
    candidates = [key]
    match = _INDEXED.fullmatch(key)
    if match:
        base, index = match.group(1), int(match.group(2))
        candidates.append(base if index == 0 else "%s_%d" % (base, index))
    return candidates


def alias_map(keys):
    """{port name yosys may emit: PCF key} for every key.

    The exact spelling always wins over a derived alias, so a design that really
    does have a scalar port called ``led_1`` is not hijacked by ``led[1]``.
    """
    mapping = {}
    for key in keys:
        for candidate in alias_candidates(key)[1:]:
            mapping.setdefault(candidate, key)
    for key in keys:
        mapping[key] = key
    return mapping
