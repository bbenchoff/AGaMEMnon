"""AG32 family part registry (T25, agamemnon/engine/family.py) tests.

The family table sits above device.py's four-package legality model: it maps
the seven real AG32 part numbers onto those packages plus flash/PSRAM/
ADC-DAC surround metadata (tools/AG32_RefManual.txt Sec 1.2). These tests
pin the table's shape and its cross-consistency with device.py so the two
can never silently drift.
"""
import pytest

from agamemnon.engine import device, family


def test_seven_family_parts_are_registered():
    assert len(family.PART_NAMES) == 7
    assert set(family.PART_NAMES) == {
        "AG32VF303KCU6", "AG32VF303CCT6", "AG32VF303VCT6", "AG32VH303RCT6",
        "AG32VF407RGT6", "AG32VF407VGT6", "AG32VH407VGT6",
    }


def test_every_agrv2k_package_is_reachable_by_at_least_one_part():
    covered = {family.get_part(name).device_id for name in family.PART_NAMES}
    assert covered == set(device.PACKAGES)


def test_default_part_matches_the_default_device():
    default = family.get_part(family.DEFAULT_PART)
    assert default.part_number == "AG32VF303CCT6"
    assert default.device_id == device.DEFAULT_DEVICE == "AGRV2KL48"


def test_ref_manual_table_transcribed_exactly():
    """Pin the exact tools/AG32_RefManual.txt Sec 1.2 part table (flash/PSRAM/ADC-DAC)."""
    expected = {
        # part: (device_id, flash_bytes, psram_bytes, adc_channels, dac_channels)
        "AG32VF303KCU6": ("AGRV2KQ32", 256 * 1024, 0, 9, 2),
        "AG32VF303CCT6": ("AGRV2KL48", 256 * 1024, 0, 10, 2),
        "AG32VF303VCT6": ("AGRV2KL100", 256 * 1024, 0, 16, 2),
        "AG32VH303RCT6": ("AGRV2KL64", 256 * 1024, 8 * 1024 * 1024, 11, 1),
        "AG32VF407RGT6": ("AGRV2KL64", 1024 * 1024, 0, 16, 2),
        "AG32VF407VGT6": ("AGRV2KL100", 1024 * 1024, 0, 16, 2),
        "AG32VH407VGT6": ("AGRV2KL100", 1024 * 1024, 8 * 1024 * 1024, 16, 1),
    }
    for name, (device_id, flash_bytes, psram_bytes, adc_channels, dac_channels) in expected.items():
        part = family.get_part(name)
        assert (part.device_id, part.flash_bytes, part.psram_bytes, part.adc_channels, part.dac_channels) == (
            device_id, flash_bytes, psram_bytes, adc_channels, dac_channels
        ), name
    # SRAM, ADC/DAC unit counts, comparators, and max frequency are uniform
    # across the datasheet's part table.
    for name in family.PART_NAMES:
        part = family.get_part(name)
        assert part.sram_bytes == 128 * 1024
        assert part.adc_units == 3
        assert part.comparators == 2
        assert part.max_cpu_hz == 248_000_000


def test_only_the_qualified_dev_board_and_second_board_claim_hardware():
    with_board = {name for name in family.PART_NAMES if family.get_part(name).has_qualified_board}
    assert with_board == {"AG32VF303CCT6", "AG32VF407VGT6"}


def test_parts_for_package_matches_family_table():
    assert family.parts_for_package("AGRV2KL48") == ("AG32VF303CCT6",)
    assert family.parts_for_package("AGRV2KQ32") == ("AG32VF303KCU6",)
    assert set(family.parts_for_package("AGRV2KL64")) == {"AG32VH303RCT6", "AG32VF407RGT6"}
    assert set(family.parts_for_package("AGRV2KL100")) == {
        "AG32VF303VCT6", "AG32VF407VGT6", "AG32VH407VGT6",
    }


def test_get_part_rejects_unknown_names():
    with pytest.raises(KeyError, match="Unknown AG32 family part"):
        family.get_part("BOGUS")


def test_part_from_env_defaults_and_honors_override():
    assert family.part_from_env({}).part_number == family.DEFAULT_PART
    assert family.part_from_env({"AGAMEMNON_PART": "AG32VH407VGT6"}).part_number == "AG32VH407VGT6"


def test_validate_family_registry_is_already_clean():
    # validate_family_registry() also runs at import time; re-running it here
    # documents the invariant it enforces and guards against a future refactor
    # that calls it conditionally.
    family.validate_family_registry()


def test_manifest_is_stable_and_matches_the_table():
    data = family.manifest()
    assert data["schema"] == 1
    assert data["default_part"] == family.DEFAULT_PART
    assert {row["part_number"] for row in data["parts"]} == set(family.PART_NAMES)
    for row in data["parts"]:
        part = family.get_part(row["part_number"])
        assert row["device_id"] == part.device_id
        assert row["flash_bytes"] == part.flash_bytes
        assert row["psram_bytes"] == part.psram_bytes
        assert row["bond_map_file"] == device.BOND_MAP_FILES[part.device_id]
        assert row["bond_map_qualification"] == device.BOND_MAP_QUALIFICATION[part.device_id]
