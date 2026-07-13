import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def _source():
    return SOURCE.read_text(encoding="utf-8")


def _scalar(src, name):
    match = re.search(rf"static constexpr double {name} = ([0-9.]+);", src)
    assert match, name
    return float(match.group(1))


def _array(src, name):
    match = re.search(rf"static constexpr double {name}\[[0-9]+\] = \{{([^}}]+)\}};", src)
    assert match, name
    return [float(value.strip()) for value in match.group(1).split(",")]


def test_slice_timing_constants_are_vendor_worst_case_maxima():
    src = _source()
    assert "8974d47eb279091a60b2ab2ed9b532c3577b806a6a7bcbbb135bdabb4945e815" in src
    assert _array(src, "SLICE_LUT_TO_F_NS") == [0.608, 0.565, 0.474, 0.149]
    assert _array(src, "SLICE_SETUP_NS") == [1.040, 0.998, 0.904, 0.582]
    assert _scalar(src, "SLICE_HOLD_NS") == 0.0
    assert _scalar(src, "SLICE_CLK_TO_Q_NS") == 0.312
    assert _scalar(src, "SLICE_CIN_TO_F_NS") == 0.631
    assert _array(src, "SLICE_CARRY_TO_COUT_NS") == [0.635, 0.551, 0.153]
    assert _scalar(src, "SLICE_CIN_SETUP_NS") == 1.063


def test_slice_timing_is_registered_after_packing_with_nextpnr_apis():
    src = _source()
    pack = src[src.index("void pack() override") : src.index("// parse \"X14Y8_OMUX02\"")]
    assert pack.index("pack_dense(ctx)") < pack.index("add_slice_timing(ctx)")

    timing = src[src.index("static void add_slice_timing") : src.index("// ---- Packing:")]
    for api in (
        "addCellTimingClock(",
        "addCellTimingDelay(",
        "addCellTimingSetupHold(",
        "addCellTimingClockToOut(",
    ):
        assert api in timing
    assert 'ctx->id("I[" + std::to_string(i) + "]")' in timing
    assert "SLICE_LUT_TO_F_NS[i]" in timing
    assert "SLICE_SETUP_NS[i]" in timing
    assert "SLICE_CARRY_TO_COUT_NS[0]" in timing
    assert "SLICE_CARRY_TO_COUT_NS[1]" in timing
    assert "SLICE_CARRY_TO_COUT_NS[2]" in timing
    assert "SLICE_CIN_SETUP_NS" in timing
