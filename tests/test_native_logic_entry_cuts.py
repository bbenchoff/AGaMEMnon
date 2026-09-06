"""Placement must account for capacity-one entries shared by ordinary logic nets."""
import pytest
from test_native_endpoint_legality import _run, _slice


@pytest.mark.parametrize('mode', ['conflict', 'same_net', 'alternate_sink'])
@pytest.mark.parametrize('ordered', [False, True])
@pytest.mark.parametrize('repair', [False, True])
def test_logic_entry_cut_ownership(tmp_path, monkeypatch, mode, ordered, repair):
    if repair:
        monkeypatch.setenv('AGRV2K_HEAP_CUT_REPAIR', '1')
    else:
        monkeypatch.delenv('AGRV2K_HEAP_CUT_REPAIR', raising=False)
    if ordered:
        monkeypatch.setenv('AGRV2K_HEAP_CONSTRAINT_ORDER', '1')
    else:
        monkeypatch.delenv('AGRV2K_HEAP_CONSTRAINT_ORDER', raising=False)
    cells = {}
    for name, bel, bit in [('source_a', 'X4Y3_SLICE14', 2),
                           ('source_b', 'X9Y1_SLICE10', 3)]:
        cell = _slice(bel=bel, output_bit=bit)
        cell['parameters']['INIT'] = format(0, '016b')
        cell['connections']['I'] = ['x'] * 4
        cells[name] = cell
    for name, bel, bit in [('sink_a', 'X1Y1_SLICE12', 2),
                           ('sink_b', 'X9Y1_SLICE8' if mode == 'alternate_sink'
                            else 'X1Y1_SLICE14', 2 if mode == 'same_net' else 3)]:
        cell = _slice(bel=bel)
        cell['connections'] = {'I': [bit, 'x', 'x', 'x'], 'F': [], 'Q': []}
        cells[name] = cell
    if mode == 'same_net':
        del cells['source_b']
    design = {'modules': {'top': {
        'attributes': {'top': 1}, 'ports': {}, 'cells': cells,
        'netnames': {'a': {'bits': [2], 'attributes': {}},
                     'b': {'bits': [3], 'attributes': {}}},
    }}}
    result, log, _ = _run(tmp_path, mode, design,
                          '--no-pack', '--no-route', '--placer', 'heap',
                          condplace=False, pinpack=False)
    if mode == 'conflict':
        assert result.returncode != 0, log
        assert 'require shared entry X2Y1_RMUX48' in log
    else:
        assert result.returncode == 0, log
    assert ('HeAP static-domain ordering:' in log) == ordered


@pytest.mark.parametrize('same_net', [False, True])
@pytest.mark.parametrize('exact', [False, True])
def test_multi_predecessor_alternate_path(tmp_path, monkeypatch, same_net, exact):
    """An alternate path keeps this pair legal despite one shared short path."""
    monkeypatch.setenv('AGRV2K_HEAP_CUT_REPAIR', '1')
    monkeypatch.setenv('AGRV2K_LOGIC_DOMINATORS', '1' if exact else '0')
    cells = {}
    for name, bel, bit in [('source_a', 'X17Y10_SLICE2', 2),
                           ('source_b', 'X1Y3_SLICE10', 3)]:
        cell = _slice(bel=bel, output_bit=bit)
        cell['parameters']['INIT'] = format(0, '016b')
        cell['connections']['I'] = ['x'] * 4
        cells[name] = cell
    for name, bel, pin, bit in [('sink_a', 'X1Y3_SLICE2', 2, 2),
                                ('sink_b', 'X1Y3_SLICE4', 0, 2 if same_net else 3)]:
        cell = _slice(bel=bel)
        cell['parameters']['INIT'] = format(sum(((i >> pin) & 1) << i for i in range(16)), '016b')
        inputs = ['x'] * 4
        inputs[pin] = bit
        cell['connections'] = {'I': inputs, 'F': [], 'Q': []}
        cells[name] = cell
    if same_net:
        del cells['source_b']
    design = {'modules': {'top': {'attributes': {'top': 1}, 'ports': {},
        'cells': cells, 'netnames': {'a': {'bits': [2], 'attributes': {}},
                                   'b': {'bits': [3], 'attributes': {}}}}}}
    result, log, _ = _run(tmp_path, 'multi_entry', design,
        '--no-pack', '--no-route', '--placer', 'heap', condplace=False, pinpack=False)
    assert result.returncode == 0, log


@pytest.mark.parametrize('omit', [None, 'a', 'b', 'c', 'd'])
def test_entry_wire_set_capacity(tmp_path, monkeypatch, omit):
    """Four demands cannot cross three wires; every proper subset remains legal."""
    monkeypatch.setenv('AGRV2K_ENTRY_SET_CAPACITY', '1')
    monkeypatch.setenv('AGRV2K_HEAP_CUT_REPAIR', '1')
    monkeypatch.setenv('AGRV2K_LOGIC_DOMINATORS', '0')
    arcs = [('a', 'X17Y10_SLICE2', 'X1Y3_SLICE2', 2),
            ('b', 'X1Y3_SLICE10', 'X1Y3_SLICE4', 0),
            ('c', 'X2Y3_SLICE2', 'X1Y3_SLICE12', 0),
            ('d', 'X1Y4_SLICE8', 'X1Y3_SLICE8', 0)]
    cells = {}
    names = {}
    for bit, (name, source, sink, pin) in enumerate(arcs, 2):
        if name == omit:
            continue
        driver = _slice(bel=source, output_bit=bit)
        driver['parameters']['INIT'] = format(0, '016b')
        driver['connections']['I'] = ['x'] * 4
        target = _slice(bel=sink)
        target['parameters']['INIT'] = format(sum(((i >> pin) & 1) << i for i in range(16)), '016b')
        inputs = ['x'] * 4
        inputs[pin] = bit
        target['connections'] = {'I': inputs, 'F': [], 'Q': []}
        cells['source_' + name] = driver
        cells['sink_' + name] = target
        names[name] = {'bits': [bit], 'attributes': {}}
    design = {'modules': {'top': {'attributes': {'top': 1}, 'ports': {},
                                  'cells': cells, 'netnames': names}}}
    result, log, _ = _run(tmp_path, 'wire_set', design,
        '--no-pack', '--no-route', '--placer', 'heap', condplace=False, pinpack=False)
    if omit is None:
        assert result.returncode != 0, log
        assert '4 distinct nets require entry wire-set capacity 3' in log
    else:
        assert result.returncode == 0, log
