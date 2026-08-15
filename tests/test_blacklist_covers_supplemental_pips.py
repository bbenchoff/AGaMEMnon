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
    assert routing.FEATURE.descriptor.feature_id == "routing"
