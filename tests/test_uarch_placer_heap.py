"""HeAP-first policy and canonical AGRV2K BEL buckets."""

import json
from pathlib import Path

from agamemnon.cli import _uarch_attempts, _uarch_prefers_heap


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def _design(path, cell_types):
    cells = {
        "cell_%d" % index: {"type": cell_type}
        for index, cell_type in enumerate(cell_types)
    }
    path.write_text(json.dumps({"modules": {"top": {"cells": cells}}}))
    return path


def test_mcu_boundary_design_selects_heap_first(tmp_path):
    design = _design(tmp_path / "boundary.json", ["LUT", "MCU_DIN"])
    assert _uarch_prefers_heap(design)


def test_existing_more_than_sixteen_cell_dense_boundary_selects_heap(tmp_path):
    assert not _uarch_prefers_heap(_design(tmp_path / "small.json", ["LUT"] * 16))
    assert _uarch_prefers_heap(_design(tmp_path / "dense.json", ["LUT"] * 17))


def test_heap_rung_is_first_except_for_qualified_portb_shape():
    heap_first = _uarch_attempts(5, 2, heap_first=True)
    assert heap_first[0] == (0, 0)
    assert len(heap_first) == len(set(heap_first))

    portb = _uarch_attempts(5, 2, split_first=True, heap_first=True)
    assert portb[0] == (5, 16)
    assert portb[1] == (0, 0)


def test_uarch_advertises_canonical_logic_and_io_bel_buckets():
    source = UARCH.read_text(encoding="utf-8")
    bucket = source.split(
        "BelBucketId getBelBucketForCellType", 1
    )[1].split("bool isValidBelForCellType", 1)[0]
    assert 'ctx->id("LUT")' in bucket
    assert 'ctx->id("DFF")' in bucket
    assert 'ctx->id("AG32_FA")' in bucket
    assert 'return ctx->id("GENERIC_SLICE")' in bucket
    assert 'ctx->id("$nextpnr_ibuf")' in bucket
    assert 'return ctx->id("GENERIC_IOB")' in bucket
    assert 'return ctx->getBelType(bel) == getBelBucketForCellType(cell_type)' in source
