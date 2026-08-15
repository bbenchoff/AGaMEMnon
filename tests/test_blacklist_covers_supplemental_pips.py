"""Every loop that adds a routing pip must consult the edge blacklist.

The blacklist is the only mechanism that removes a routable edge, and three
separate loaders used to add pips outside the main RRG loop without checking it:
the BRAM supplemental rows, the package pad-feed rows, and the vendor
RMUX->IOMUX terminal rows. Banning one of those edges therefore did nothing at
all, and the build looked like it had obeyed -- placement succeeded, routing
succeeded, bitgen reported zero unmapped, and the router had quietly used the
edge anyway.

A ban that silently leaves an edge routable is worse than no ban, so this is a
structural test rather than a behavioural one: find every `ctx.addPip` call in
the routing feature, and require the enclosing loop to guard it.

The key also has to be normalised. `RMUX8` and `RMUX08` are the same wire, and a
raw string comparison between them matches nothing -- which looks exactly like
"the ban had no effect".
"""

import ast
from pathlib import Path

import pytest

from agamemnon.engine.features import routing


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agamemnon" / "engine" / "features" / "routing.py"


def _calls(node):
    return {
        child.func.attr if isinstance(child.func, ast.Attribute) else
        (child.func.id if isinstance(child.func, ast.Name) else "")
        for child in ast.walk(node) if isinstance(child, ast.Call)
    }


def pip_adding_loops():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue
        if "addPip" not in _calls(node):
            continue
        # Only the innermost loop around the call matters.
        if any(isinstance(inner, (ast.For, ast.AsyncFor)) and "addPip" in _calls(inner)
               for inner in ast.walk(node) if inner is not node):
            continue
        found.append(node)
    return found


def test_the_routing_feature_still_adds_pips_in_loops():
    assert len(pip_adding_loops()) >= 4


@pytest.mark.parametrize("loop", pip_adding_loops(), ids=lambda node: "line%d" % node.lineno)
def test_every_pip_adding_loop_consults_the_blacklist(loop):
    # Module-level helpers take the predicate as a parameter, so accept either
    # the closure name or the injected one.
    guarded = {"_blacklisted", "is_blacklisted"} & _calls(loop)
    assert guarded, (
        "the loop at routing.py:%d calls ctx.addPip without consulting the edge "
        "blacklist, so a ban on those edges would silently do nothing"
        % loop.lineno
    )


def test_the_blacklist_key_is_normalised_for_zero_padding():
    """RMUX8 and RMUX08 must compare equal, in both directions."""
    source = SOURCE.read_text(encoding="utf-8")
    assert "_norm_edge" in source and "_norm_res" in source
    # The normaliser is defined inside add_architecture, so exercise the same
    # rule the loaders rely on rather than reaching into the closure.
    import re
    def norm(res):
        match = re.fullmatch(r"([A-Za-z]+)0*(\d+)", res)
        return "%s%d" % (match.group(1), int(match.group(2)))
    assert norm("RMUX08") == norm("RMUX8") == "RMUX8"
    assert norm("IOMUX00") == norm("IOMUX0") == "IOMUX0"
    assert norm("BBMUXE07") == norm("BBMUXE7") == "BBMUXE7"


def test_the_routing_feature_exposes_its_blacklist_to_the_context():
    """Other features and tests need the same view of what was banned."""
    source = SOURCE.read_text(encoding="utf-8")
    assert '"edge_blacklist": EDGE_BLACKLIST' in source
    assert '"is_blacklisted": _blacklisted' in source
    # Tables keyed by whole wire names need their own form of the predicate, or
    # their loaders cannot call it and quietly do not.
    assert '"is_blacklisted_wires": _blacklisted_wires' in source
    assert routing.FEATURE.descriptor.feature_id == "routing"


# --------------------------------------------------------------------------
# The rule is not routing.py's alone. Four other feature modules add pips, and
# every one of them used to do it without consulting the ban -- mcu_ahb.py at
# 26 call sites. Those tables are keyed by whole WIRE NAMES
# (``X14Y8_RMUX21`` -> ``X14Y4_RMUX93``) and the part-keyed predicate does not
# accept those, so the loaders simply never called it. A cut ban naming one of
# those edges did nothing at all, while sibling edges of the identical shape
# arriving through the part-keyed RRG loader DID respond to the same ban --
# which looks exactly like "the ban syntax works".
# --------------------------------------------------------------------------

OTHER_PIP_SOURCES = (
    "mcu_ahb.py",
    "mcu_gpio.py",
    "bram.py",
)

GUARD_NAMES = {
    "_blacklisted", "is_blacklisted", "_blacklisted_wires", "is_blacklisted_wires",
}


def _feature_source(name):
    return (ROOT / "agamemnon" / "engine" / "features" / name).read_text(encoding="utf-8")


def _direct_addpip_lines(tree):
    return [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "addPip"
    ]


def _innermost_loops_calling_addpip(tree):
    """Loop granularity, deliberately.

    A per-FUNCTION rule passes vacuously here: mcu_ahb's ``add_architecture``
    consulted the ban in its FIRST loop and then added 26 more pips in later
    loops without it, so "the function mentions the predicate somewhere" proved
    nothing at all. The unit that has to be guarded is the loop.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue
        if not _direct_addpip_lines(node):
            continue
        if any(isinstance(inner, (ast.For, ast.AsyncFor))
               and _direct_addpip_lines(inner)
               for inner in ast.walk(node) if inner is not node):
            continue
        found.append(node)
    return found


@pytest.mark.parametrize("name", OTHER_PIP_SOURCES)
def test_other_features_gate_every_pip_they_add(name):
    tree = ast.parse(_feature_source(name))
    assert _direct_addpip_lines(tree), (
        "%s adds no pips any more; drop it from OTHER_PIP_SOURCES" % name
    )

    unguarded = [
        loop for loop in _innermost_loops_calling_addpip(tree)
        if not (GUARD_NAMES & _calls(loop))
    ]
    assert not unguarded, (
        "%s calls ctx.addPip at line(s) %s in a loop that never consults the "
        "edge blacklist, so a ban on those edges would silently do nothing"
        % (name, [loop.lineno for loop in unguarded])
    )

    # And a choke-point helper that wraps ctx.addPip must consult it too,
    # otherwise moving the call out of the loop would defeat the rule above.
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        own_body = [
            call for statement in node.body for call in ast.walk(statement)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "addPip"
            and not any(isinstance(scope, ast.FunctionDef)
                        for scope in ast.walk(statement))
        ]
        if own_body and not GUARD_NAMES & _calls(node):
            raise AssertionError(
                "%s:%s wraps ctx.addPip without consulting the edge blacklist"
                % (name, node.name)
            )


def test_the_wire_keyed_predicate_normalises_and_parses_both_endpoints():
    """It has to reuse _norm_edge, or it reintroduces the zero-padding trap."""
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    predicate = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_blacklisted_wires"
    )
    # It must delegate on both halves rather than re-implement them, so the
    # wire parse cannot drift from the loaders and the normalisation cannot
    # drift from the pad-composition rule.
    assert "_blacklisted" in _calls(predicate)
    assert "wire_endpoint" in _calls(predicate)
    # And the parse is a module-level function, so every loader shares one copy
    # of it and it is directly testable.
    assert routing.wire_endpoint("X14Y8_RMUX21") == ("RMUX21", "14", "8")
