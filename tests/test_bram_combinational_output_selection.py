"""A BRAM pin hint cannot select Q for an unregistered F-output driver."""
import pytest

from agamemnon.engine.features.core_logic import FEATURE
from agamemnon.engine.registry import CONSTANTS, options_from


def prepare(selection, registered, init=0xaaaa, fields=True):
    cell = dict(type='GENERIC_SLICE',
        parameters={'K': '100', 'INIT': format(init, '016b'), 'FF_USED': str(int(registered))},
        attributes={'NEXTPNR_BEL': 'X14Y4_SLICE9', 'AGRV2K_OMUX_SEL': format(selection, '032b')},
        connections={'I': [10, 'x', 'x', 'x'], 'F': [] if registered else [11],
                     'Q': [12] if registered else [], 'CLK': [13] if registered else []})
    module = {'cells': {'driver': cell}, 'ports': {},
              'netnames': {f'n{bit}': {'bits': [bit]} for bit in range(10, 14)}}
    selectors = {(14, 4, 'CFG_OMUX9', i): (200, 1 << i) for i in range(3)} if fields else {}
    return FEATURE.prepare(module, selectors, options_from({}), CONSTANTS)


@pytest.mark.parametrize('selection', [0, 1, 2])
@pytest.mark.parametrize('init', [0, 0xaaaa, 0xffff])
def test_combinational_bram_hint_does_not_select_register(selection, init):
    assert prepare(selection, False, init).register_sets == []


@pytest.mark.parametrize('selection', [0, 1, 2])
def test_registered_bram_hint_preserves_requested_register_selection(selection):
    assert prepare(selection, True).register_sets == [(200, 1 << selection)]


def test_unused_register_selection_needs_no_register_field():
    assert prepare(2, False, fields=False).register_sets == []


def test_live_register_selection_still_requires_its_field():
    with pytest.raises(SystemExit, match='CFG_OMUX9'):
        prepare(2, True, fields=False)
