"""A ground-only mux witness must not AND an independent live address input."""
import csv
import json
from pathlib import Path

from agamemnon.engine.features.mcu_ahb import FEATURE, exact_wire
from agamemnon.engine.registry import options_from

ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / 'agamemnon/chipdb'


def test_address9_exact_word_selects_only_rmux54_not_rmux78():
    with (CHIPDB / 'bram_address_gnd_terminal_pip_cfg.csv').open(newline='') as stream:
        row = next(r for r in csv.DictReader(stream) if r['dst_wire'] == 'X13Y4_IMUX03')
    assert row['src_wire'] == 'X14Y4_RMUX54'
    assert row['clear_selectors'] == ';'.join(map(str, range(36, 48)))
    assert row['set_selectors'] == '42;45'
    assert row['evidence'] == 'qualification/BRAM_ADDRESS9_TERMINAL_20260905.md'


def test_generic_exact_tuple_agrees_with_corrected_boundary_override():
    resolver = json.loads((CHIPDB / 'bram_resolver.json').read_text())
    assert resolver['L0']['IMUX|3|RMUX|54|-1|0'] == [6, 9]


def test_effective_loader_keeps_single_source_word_and_complete_clear_field():
    metadata = FEATURE.load_routing_metadata(CHIPDB, options_from({}))
    key = exact_wire('X14Y4_RMUX54') + exact_wire('X13Y4_IMUX03')
    assert metadata.exact_pips[key] == ('fabric', 'CFG_IMUX0', tuple(range(36, 48)), (42, 45))
