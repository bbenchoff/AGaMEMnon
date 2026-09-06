"""Exact high-address logic ingress; vendor observation, not silicon qualification."""
import csv
from pathlib import Path
from types import SimpleNamespace

import pytest
from agamemnon.engine.features.mcu_ahb import FEATURE as MCU, exact_wire
from agamemnon.engine.features.protocol import BitstreamContext
from agamemnon.engine.features.routing import FEATURE as ROUTING
from agamemnon.engine.registry import options_from

CHIPDB = Path(__file__).resolve().parents[1]/'agamemnon/chipdb'


def rows(name):
    with (CHIPDB/name).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize('lane,target', [(4, 1), (29, 2), (30, 3), (31, 0)])
def test_region_paths_are_three_contiguous_edges_to_distinct_lut_inputs(lane, target):
    path = [r for r in rows('mcu_haddr_region_logic_paths.csv') if int(r['source_bit']) == lane]
    assert [int(r['step']) for r in path] == [0, 1, 2]
    assert all(a['dst_wire'] == b['src_wire'] for a, b in zip(path, path[1:]))
    assert path[-1]['dst_wire'] == f'X14Y10_IMUX{target:02d}'
    fields = MCU.load_exact_pip_fields(CHIPDB)
    assert all(exact_wire(r['src_wire']) + exact_wire(r['dst_wire']) in fields for r in path)


@pytest.mark.parametrize('index', range(12))
@pytest.mark.parametrize('missing', [False, True])
def test_exact_field_emission_replaces_only_its_field_and_refuses_missing_cells(index, missing):
    row = rows('mcu_haddr_region_logic_pip_cfg.csv')[index]
    fields = MCU.load_exact_pip_fields(CHIPDB)
    clear = tuple(int(x) for x in row['clear_selectors'].split(';') if x)
    selected = tuple(int(x) for x in row['set_selectors'].split(';') if x)
    if row['cell_table'] == 'mcu':
        assert clear == (0,)
        assert selected == (() if row['dst_wire'].endswith('InputMUX01') else (0,))
    else:
        assert len(selected) == 2
    x, y = int(row['x']), int(row['y'])
    cell = {(x, y, row['cfg_group'], s): (s+10, 1) for s in clear}
    if missing: del cell[x, y, row['cfg_group'], clear[-1]]
    def prepare(allow_unmapped=False):
        return ROUTING.prepare(
        pips=[row['src_wire']+'.'+row['dst_wire']],
        cell=cell if row['cell_table'] == 'fabric' else {},
        mcu_cells=cell if row['cell_table'] == 'mcu' else {},
        options=options_from({'AGAMEMNON_ALLOW_UNMAPPED': '1'} if allow_unmapped else {}),
        tables=SimpleNamespace(admission_binding=None, admitted_edge={}),
        physical_io_state=SimpleNamespace(physical_fixed_pip=set(), physical_oe_pip={}),
        exact_mcu_pips=fields, mcu_exit_pairs={}, bram_feature=None, bram_state=None,
        slice_config={}, left_vendor_slices=set())
    if missing:
        with pytest.raises(SystemExit, match='refusing to emit a partial bitstream'):
            prepare()
        # Diagnostic state inspection only: strict production refusal above
        # remains required, and even permissive mode must not write half a field.
        state = prepare(allow_unmapped=True)
        assert state.unmapped == 1 and state.mapped == 0
        assert state.clears == state.sets == []
        return
    state = prepare()
    assert state.unmapped == state.predicted == 0 and state.mapped == 1
    assert set(state.clears) == {(s+10, 1) for s in clear}
    assert set(state.sets) == {(s+10, 1) for s in selected}
    image = bytearray([255])*100
    context = BitstreamContext(image=image, module={}, chipdb_root=CHIPDB,
                               options=options_from({}), state=state)
    ROUTING.clear_bitstream(context)
    ROUTING.emit_bitstream(context)
    assert image == bytearray(254 if i-10 in set(clear)-set(selected) else 255 for i in range(100))
