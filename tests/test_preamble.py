from pathlib import Path

from agamemnon.engine import lzw_codec, pll_emit, preamble


ROOT = Path(__file__).resolve().parents[1]


def _baseline_raw():
    data = (ROOT / "agamemnon" / "chipdb" / "fabric_default.bin").read_bytes()
    return data[8:] if len(data) - 8 == 99936 else lzw_codec.decode(data[8:])


def test_idle_profile_reconstructs_every_baseline_preamble_byte():
    assert preamble.IDLE_PROFILE == _baseline_raw()[:preamble.PREAMBLE_LENGTH]
    assert preamble.describe(preamble.IDLE_PROFILE)["profile"] == "idle"


def test_supported_clock_profiles_are_complete_and_recognized():
    for sysclk, hse in pll_emit.SUPPORTED_RATIOS:
        built = preamble.build(clocked=True, sysclk=sysclk, hse=hse)
        assert len(built) == 164
        assert built[83:86] == preamble.CLOCK_DISTRIBUTION_100_8
        assert preamble.describe(built)["profile"] == "pll-%d-%d" % (sysclk, hse)


def test_apply_discards_inherited_preamble():
    raw = bytearray([0x5A]) * 99936
    tail = bytes(raw[164:200])
    preamble.apply(raw, clocked=False)
    assert raw[:164] == preamble.IDLE_PROFILE
    assert raw[164:200] == tail


def test_custom_preamble_is_reported_honestly():
    custom = bytearray(preamble.IDLE_PROFILE)
    custom[50] ^= 1
    report = preamble.describe(custom)
    assert report["profile"] == "custom"
    assert not report["generated_profile"]
    assert sum(region["bytes_changed_from_idle"] for region in report["regions"]) == 1
