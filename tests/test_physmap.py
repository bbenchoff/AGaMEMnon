from agamemnon.engine import physmap


def test_lut_map_retains_odd_column_half_byte_phase():
    # Cross-checked against physical_map_full.csv and the silicon-proven LUT at X19Y12_SLICE0.
    assert [physmap.init_bit_pos(19, 12, 0, b) for b in range(8)] == [
        (2725, 0x04), (2726, 0x80), (2725, 0x02), (2725, 0x01),
        (2841, 0x02), (2841, 0x01), (2841, 0x04), (2842, 0x80),
    ]


def test_lut_map_even_column_remains_byte_aligned():
    assert [physmap.init_bit_pos(20, 12, 0, b) for b in range(4)] == [
        (2721, 0x40), (2721, 0x08), (2721, 0x20), (2721, 0x10),
    ]
