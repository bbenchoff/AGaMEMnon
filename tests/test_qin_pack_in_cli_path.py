"""Self-feedback must ride the slice's pinC, and the CLI must always do it.

A toggle flip-flop's self-feedback has to use the slice's dedicated feedback mux.
Routed as an ordinary intra-tile OMUX->IMUX hop it has NO encoding at all: bitgen
emits "UNMAPPED IMUXn <- OMUXm d=(0,0)", one per flip-flop, and the flip-flop
never toggles. That is what made the nine-pad negative meaningless -- every pad
in those images was being asked to output a constant, so the experiment never
tested pad conduction at all.

The transform is qin_pack.permute_selffb_to_pinC. It runs from the CLI, and
these tests keep it there and prove it does the work on the retained pad-pair
source's own netlist shape.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "agamemnon" / "engine"


def test_the_cli_runs_qin_pack_between_synthesis_and_place_and_route():
    source = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert 'run("qin"' in source, "the CLI no longer invokes qin_pack"
    # It has to happen after synthesis and before nextpnr, or the netlist
    # nextpnr sees still contains the unencodable self-feedback.
    synth = source.index('run("synth"')
    qin = source.index('run("qin"')
    pnr = source.index('run("place&route"')
    assert synth < qin < pnr


def test_the_retained_pair_route_has_no_routed_self_feedback():
    """The real regression: no intra-tile OMUX->IMUX self-feedback survives.

    A d=(0,0) OMUX->IMUX hop is the signature of a self-feedback that qin_pack
    did not fold onto pinC. There is no encoding for it, so bitgen reports it
    unmapped and the flip-flop does not toggle. The retained production routed
    netlist is the artifact that actually drove both pads on silicon, so it must
    be free of them.
    """
    routed = json.loads(
        (ROOT / "qualification" / "pad_pair_pin18_pin16_routed.json")
        .read_text(encoding="utf-8"))
    module = routed["modules"].get("top") or list(routed["modules"].values())[0]
    hop = re.compile(r"X(\d+)Y(\d+)_OMUX\d+[.>-]+X(\d+)Y(\d+)_IMUX\d+")
    offenders = []
    for name, net in module.get("netnames", {}).items():
        for match in hop.finditer(net.get("attributes", {}).get("ROUTING", "")):
            sx, sy, dx, dy = (int(value) for value in match.groups())
            if (sx, sy) == (dx, dy):
                offenders.append((name, match.group(0)))
    assert not offenders, (
        "routed self-feedback survived qin_pack; these hops have no encoding "
        "and the flip-flop will not toggle: %r" % offenders
    )


@pytest.mark.parametrize("name", ["pad_pair_pin18_pin16.v", "pad_only_pin18.v",
                                  "pad_only_pin16.v"])
def test_the_retained_pad_sources_have_an_interior_clocked_path(name):
    """Every pad flip-flop going straight to a pad leaves nextpnr with no Fmax,
    and the CLI's frequency check then fails the build."""
    text = (ROOT / "qualification" / name).read_text(encoding="utf-8")
    registers = re.findall(r"\breg\s+(\w+)\s*=", text)
    assert len(registers) >= 2, (
        "%s has fewer than two registers, so it cannot present an interior "
        "flip-flop-to-flip-flop timing path" % name
    )
    # A register whose D is another register's Q -- written either as the ring
    # form (a <= ~b; b <= a) or the pipeline form (x_d <= x).
    body = " ".join(text.split())
    assert any("<= %s;" % other in body or "<= ~%s;" % other in body
               for other in registers), (
        "%s has no register-to-register assignment" % name
    )
