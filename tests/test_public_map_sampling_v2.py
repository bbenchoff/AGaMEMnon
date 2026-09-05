"""Versioned sampling improvement preserves the historical functional contract."""
import hashlib
from pathlib import Path
import pytest

Q = Path(__file__).resolve().parents[1] / 'qualification'

@pytest.mark.parametrize('kind,expected', [
    ('public16', 'e2e63d0fde94cdb3e9b474e5b18a635803dc1ed5f7bce272109fb03f0122ffe3'),
    ('public32', '95c71c7ab8c702f28734467d64ae3b276a7f4a8343dfa8116c53b7e58073b1da'),
    ('public32_gpio5_w1c', '0a9ba15add01500b8da61a93b9674569b012b5e07052d6536b4a0897d3901931'),
    ('public32_autoevent_w1c', 'ab25390886f1ed7b0f0f29c2d4a7e987c2c6fbff3e1a8f7d6ca25ea5e4f9dbc4'),
])
def test_sampling_variant_preserves_all_functional_assertions(kind, expected):
    variant = (Q / ('mcu_ahb_' + kind + '_sampling_v2_test.c')).read_text()
    original = (Q / ('mcu_ahb_' + kind + '_exact_map_test.c')).read_text()
    assert hashlib.sha256(variant.encode()).hexdigest() == expected
    restored = variant.replace(
        'u32 sampling_state=0x1234567u;\n  for(u32 i=0;i<2048u;++i)',
        'for(u32 i=0;i<512u;++i)')
    restored = restored.replace(
        'sampling_state^=sampling_state<<13;\n    sampling_state^=sampling_state>>17;\n    sampling_state^=sampling_state<<5;\n    for(volatile u32 j=0;j<(sampling_state&31u);++j);',
        'for(volatile u32 j=0;j<(i&7u);++j);')
    assert restored == original
    assert 'if(seen!=0xffu) ++counter_coverage_errors;' in variant
