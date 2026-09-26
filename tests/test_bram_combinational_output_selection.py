"""A BRAM pin hint cannot select Q for an unregistered F-output driver."""
import pytest

from agamemnon.engine.features.core_logic import FEATURE
from agamemnon.engine.registry import CONSTANTS, options_from


def prepare(selection, registered, init=0xaaaa, fields=True, routed_outputs=(), f_outputs=()):
    cell = dict(type='GENERIC_SLICE',
        parameters={'K': '100', 'INIT': format(init, '016b'), 'FF_USED': str(int(registered))},
        attributes={'NEXTPNR_BEL': 'X14Y4_SLICE9', 'AGRV2K_OMUX_SEL': format(selection, '032b')},
        connections={'I': [10, 'x', 'x', 'x'], 'F': [] if registered else [11],
                     'Q': [12] if registered else [], 'CLK': [13] if registered else []})
    module = {'cells': {'driver': cell}, 'ports': {},
              'netnames': {f'n{bit}': {'bits': [bit]} for bit in range(10, 14)}}
    output = 12 if registered else 11
    module['netnames'][f'n{output}']['attributes'] = {'ROUTING': ';'.join(
        f'X14Y4_RMUX{i};X14Y4_OMUX{27 + i}.X14Y4_RMUX{i};1'
        for i in routed_outputs)}
    if f_outputs:
        cell['connections']['F'] = [11]
        module['netnames']['n11']['attributes'] = {'ROUTING': ';'.join(
            f'X14Y4_OMUX{27 + i};;1' for i in f_outputs)}
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


@pytest.mark.parametrize('hint', range(3))
@pytest.mark.parametrize('fanout', [(0, 2), (1, 2), (0, 1, 2)])
def test_bram_hint_preserves_every_routed_register_output(hint, fanout):
    state = prepare(hint, True, routed_outputs=fanout)
    assert set(state.register_sets) == {(200, 1 << i) for i in {*fanout, hint}}


@pytest.mark.parametrize('hint', range(3))
def test_bram_fanout_does_not_select_an_inactive_register(hint):
    assert prepare(hint, False, routed_outputs=(0, 1, 2)).register_sets == []


def test_bram_register_fanout_does_not_claim_independent_lut_output():
    assert set(prepare(0, True, routed_outputs=(0, 2), f_outputs=(1,)).register_sets) == {
        (200, 1), (200, 4)}
