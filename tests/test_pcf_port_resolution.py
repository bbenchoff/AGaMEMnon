"""A PCF constraint that binds nothing must be an error, not a shrug.

Yosys `iopadmap` names the bits of `output [3:0] led` as the cells `led`,
`led_1`, `led_2`, `led_3`.  An ordinary `set_io led[0] PIN_25` therefore matched
no cell in the Python-architecture pre-place hook, which skipped it silently,
left the pad to the placer, and died much later with `bel 'X14Y13_IPAD0' has no
pin 'I'` -- an error naming a pad nobody asked for.  Both halves are tested
here: the name relation, and the fact that the hook fails closed on a miss.

The uarch flow's equivalent (`pcf_bind_json.py`) already resolved vector bits
through the JSON port bit IDs and already failed closed; that asymmetry is what
let this survive, and the release uarch database has no OPAD bels at all, so the
broken path was the only one that could place a pad.
"""

import ast
from pathlib import Path

import pytest

from agamemnon.engine.pcf_ports import alias_candidates, alias_map


ROOT = Path(__file__).resolve().parents[1]
PLACER = ROOT / "agamemnon" / "engine" / "place_auto.py"


def test_a_scalar_port_resolves_to_itself():
    assert alias_candidates("o_pin18") == ["o_pin18"]
    assert alias_map(["o_pin18"]) == {"o_pin18": "o_pin18"}


@pytest.mark.parametrize("key,alias", [
    ("led[0]", "led"),        # yosys drops the index entirely for bit 0
    ("led[1]", "led_1"),
    ("led[3]", "led_3"),
    ("q_out[12]", "q_out_12"),
])
def test_vector_bits_resolve_to_the_yosys_spelling(key, alias):
    assert alias in alias_candidates(key)
    assert alias_map([key])[alias] == key


def test_the_exact_spelling_always_wins_over_a_derived_alias():
    """A design with a real scalar port `led_1` must not be hijacked by `led[1]`."""
    mapping = alias_map(["led[1]", "led_1"])
    assert mapping["led_1"] == "led_1"


def test_an_unknown_port_resolves_to_nothing():
    assert alias_map(["led[0]"]).get("something_else") is None


def _assignments(source, name):
    """Every value assigned to `name` at module level, as source text."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found.append(ast.unparse(node.value))
    return found


def test_the_placer_resolves_pcf_names_through_the_shared_relation():
    source = PLACER.read_text(encoding="utf-8")
    assert "pcf_ports" in source, "the placer no longer uses the shared name relation"
    assert _assignments(source, "_pcf_alias") == ["_pcf_ports.alias_map(_pcf)"]


def test_the_placer_fails_closed_on_a_constraint_that_binds_nothing():
    source = PLACER.read_text(encoding="utf-8")
    assert "_pcf_missed" in source
    # The miss has to raise. A `print` warning is not enough: the build would
    # continue and emit an image for a pad the user never constrained.
    tree = ast.parse(source)
    raised = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "_pcf_missed"
        and any(isinstance(inner, ast.Raise) for inner in ast.walk(node))
    ]
    assert raised, "an unmatched PCF constraint no longer raises"


def test_multi_cell_pinning_resolves_by_net_and_fails_closed():
    """AGAMEMNON_PIN_CELLS keys on the NET, and an unresolved key is fatal.

    Cell names cannot be used for this: yosys emits `$auto$ff.cc:337:slice$79`,
    so matching a design-level name silently pins nothing -- which is how an
    earlier campaign measured images whose flip-flops were never pinned.
    """
    source = PLACER.read_text(encoding="utf-8")
    assert "AGAMEMNON_PIN_CELLS" in source
    assert "ctx.nets" in source
    tree = ast.parse(source)
    fatal = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "_pin_want"
        and any(isinstance(inner, ast.Raise) for inner in ast.walk(node))
    ]
    assert fatal, "an unresolved AGAMEMNON_PIN_CELLS entry no longer raises"
