from copy import deepcopy
from types import SimpleNamespace

import pytest

from agamemnon.engine.features.physical_io import PhysicalIoState
from agamemnon.engine.features.routing import FEATURE, omux_output_sources
from agamemnon.engine.registry import options_from


def module(port='F', offset=0, ff_used=0):
    wire = 'X4Y5_OMUX%d' % (6 + offset)
    return {'cells': {'slice': {
        'type': 'GENERIC_SLICE', 'parameters': {'FF_USED': str(ff_used)},
        'attributes': {'NEXTPNR_BEL': 'X4Y5_SLICE2'},
        'connections': {port: [10]},
    }}, 'netnames': {'signal': {'bits': [10], 'attributes': {
        'ROUTING': '%s;X4Y5_OMUX8.%s;1;X4Y5_OMUX8;;1' % (wire, wire)}}}}


def prepare(pips, sources, cell=None, bram_mapped=None):
    return FEATURE.prepare(
        pips=pips, cell=cell if cell is not None else {
            (4, 5, 'CFG_OMUX2', i): (100, 1 << i) for i in range(3)},
        options=options_from({}),
        tables=SimpleNamespace(admission_binding=None, admitted_edge={}),
        physical_io_state=PhysicalIoState(), exact_mcu_pips={}, mcu_cells={},
        mcu_exit_pairs={}, bram_feature=SimpleNamespace(resolve_route=lambda *a, **kw: bram_mapped),
        bram_state=SimpleNamespace(), slice_config={}, left_vendor_slices=set(),
        omux_sources=sources)


@pytest.mark.parametrize('offset', [0, 1])
@pytest.mark.parametrize('port,ff_used', [('F', 0), ('F', 1), ('Q', 1)])
def test_secondary_alias_selects_actual_output(port, ff_used, offset):
    sources = omux_output_sources(module(port, offset, ff_used))
    state = prepare(['X4Y5_OMUX8.X4Y5_OMUX%d' % (6 + offset)], sources)
    assert state.mapped == 1 and state.unmapped == 0
    assert state.sets == ([(100, 1 << offset)] if port == 'Q' else [])


@pytest.mark.parametrize('offset', [0, 1])
@pytest.mark.parametrize('port,ff_used', [('F', 0), ('F', 1), ('Q', 1)])
def test_secondary_exit_selects_actual_output(port, ff_used, offset):
    # A resolved BRAM route lets this isolate the preceding OMUX source setter.
    sources = omux_output_sources(module(port, offset, ff_used))
    state = prepare(['X4Y5_OMUX%d.X13Y4_RMUX0' % (6 + offset)], sources, bram_mapped=True)
    assert state.sets == ([(100, 1 << offset)] if port == 'Q' else [])


def test_mixed_f_and_q_are_not_inferred_from_ff_used():
    doc = module('F', 0, 1)
    doc['cells']['slice']['connections']['Q'] = [11]
    doc['netnames']['signal']['attributes']['ROUTING'] = 'X4Y5_OMUX6;;1'
    doc['netnames']['q'] = {'bits': [11], 'attributes': {'ROUTING': 'X4Y5_OMUX7;;1'}}
    assert omux_output_sources(doc) == {(4, 5, 6): False, (4, 5, 7): True}
    doc['netnames']['alias'] = deepcopy(doc['netnames']['signal'])
    assert omux_output_sources(doc) == {(4, 5, 6): False, (4, 5, 7): True}


@pytest.mark.parametrize('corruption', ['missing', 'both_ports', 'inactive_q', 'foreign_net'])
def test_missing_or_ambiguous_ownership_rejected(corruption):
    doc = module()
    connections = doc['cells']['slice']['connections']
    if corruption == 'missing':
        connections.clear()
    elif corruption == 'both_ports':
        connections['Q'] = [10]
    elif corruption == 'inactive_q':
        connections['Q'] = connections.pop('F')
    else:
        doc['netnames']['signal']['bits'] = [99]
    with pytest.raises(SystemExit, match='OMUX output ownership'):
        omux_output_sources(doc)


def test_setter_requires_explicit_ownership_and_complete_field():
    with pytest.raises(SystemExit, match='ownership missing'):
        prepare(['X4Y5_OMUX8.X4Y5_OMUX6'], None)
    with pytest.raises(SystemExit, match='no config cell'):
        prepare(['X4Y5_OMUX8.X4Y5_OMUX6'], {(4, 5, 6): False}, cell={})
