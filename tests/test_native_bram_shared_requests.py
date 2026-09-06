"""Generic shared trees may be negotiated only while retaining every consumer."""
import pytest

from test_native_bram_bridges import address_origin, design, run


@pytest.mark.parametrize('memory', ['ram', 'independent_shared_memory'])
def test_shared_request_preserves_both_consumers_and_displaced_source(tmp_path, memory):
    fixture = design((5, 9, 11), explicit=True, shared=9, memory_name=memory)
    proc, transcript, packed = run(tmp_path, fixture)
    assert proc.returncode == 0, transcript
    assert 'evicted generic BRAM AddressA[5] to free AddressA[9]' in transcript
    assert 'evicted generic BRAM AddressA[9]' not in transcript
    address = packed['cells'][memory]['connections']['AddressA']
    other = packed['cells']['additional_consumer']['connections']['I'][0]
    assert address[9] == other
    assert address_origin(packed, other) == ('mcu_haddr11', 1)
    assert address_origin(packed, address[5]) == ('mcu_haddr7', 1)
    assert address_origin(packed, address[11]) == ('mcu_haddr13', 0)


@pytest.mark.parametrize('memory', ['ram', 'independent_shared_memory'])
def test_existing_shared_tree_preserves_consumers_during_negotiation(tmp_path, memory):
    proc, transcript, packed = run(tmp_path, design((5, 9, 11), explicit=True,
                                                  shared=5, memory_name=memory),
                                   AGRV2K_TRACE_BRAM_CORRIDORS="1")
    assert proc.returncode == 0, transcript
    address = packed['cells'][memory]['connections']['AddressA']
    other = packed['cells']['additional_consumer']['connections']['I'][0]
    assert address[5] == other
    for bit in (5, 9, 11):
        assert address_origin(packed, address[bit]) == (f'mcu_haddr{bit + 2}', int(bit != 11))
        assert f'BRAM trace verified AddressA[{bit}] ' in transcript
