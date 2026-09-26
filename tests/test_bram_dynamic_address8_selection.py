"""A constant-address witness must not contaminate a changing address mux."""
import csv
from pathlib import Path

from agamemnon.engine.features.mcu_ahb import FEATURE, exact_wire
from agamemnon.engine.registry import options_from

CHIPDB = Path(__file__).resolve().parents[1] / 'agamemnon/chipdb'


def test_address8_terminal_uses_single_source_codeword():
    with (CHIPDB / 'bram_address_gnd_terminal_pip_cfg.csv').open(newline='') as stream:
        row = next(r for r in csv.DictReader(stream)
                   if r['dst_wire'] == 'X13Y4_IMUX04')
    assert row['src_wire'] == 'X13Y4_RMUX28'
    assert row['clear_selectors'] == ';'.join(map(str, range(12)))
    assert row['set_selectors'] == '5;10'


def test_effective_address8_override_replaces_the_complete_field():
    metadata = FEATURE.load_routing_metadata(CHIPDB, options_from({}))
    key = exact_wire('X13Y4_RMUX28') + exact_wire('X13Y4_IMUX04')
    assert metadata.exact_pips[key] == (
        'fabric', 'CFG_IMUX1', tuple(range(12)), (5, 10))
