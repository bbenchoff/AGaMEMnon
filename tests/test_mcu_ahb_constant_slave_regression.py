"""Regression guards for the 2026-08-18 mcu_ahb_constant_slave investigation.

History, because this file's assertions are the inverse of what T26 first
concluded and the reversal is the whole point:

T22-T24 found that a fresh build of ``examples/designs/mcu_ahb_constant_slave.v``
read ``0x795fe3dd`` instead of the 2026-08-02-qualified ``0x4147414d`` -- 10 of 32
bits wrong -- reproduced 96/96 on an LQFP-100 unit and again on the L48 reference
board, so it was never unit- or package-specific.

T26 traced all ten wrong bits to a shared ``X14Y8`` RMUX->IMUX->RMUX detour (still
open; see docs/CONDUCTION_REFRAME_STATUS.md) and, separately, proposed that
``X14Y11_RMUX03 -> X13Y11_BBMUXE09`` needed an exact ``(1,6)`` tuple, because that
is the value which byte-reproduces the retained 2026-08-02 golden.

**A1b refuted that proposal on hardware.** Byte-matching an old golden is not
evidence of encoding correctness: the 2026-08-02 image carried the pre-``48cda69``
value on a lane that *this* design does not observe. The matched A/B, on the L48
reference board in one session:

* ``mcu_ahb_public32_gpio5_w1c_exact_map`` packed with ``(2,4)`` (no exact tuple)
  is image ``bc338504...`` -- the 2026-08-15 silicon golden -- and PASSES, all nine
  error groups zero, ID32 ``0x4147414d``.
* The same netlist packed with ``(1,6)`` is image ``8673ae0d...`` and FAILS:
  ID32 reads ``0x4107414d``. ``0x4147414d ^ 0x4107414d == 0x00400000`` -- bit 22,
  exactly the lane ``BBMUXE09`` feeds. Bit 22 is live in that design.
* The constant slave packed with ``(1,6)`` (``b2047ed2...``) reads ``0x4147414d``,
  and packed with ``(2,4)`` (``3ef719a0...``) *also* reads ``0x4147414d``: 72/72
  direct reads, 6/6 mailbox reads, FCB_STAT ``0x000f0002`` every cycle.

So ``(2,4)`` is correct for both designs, ``(1,6)`` is wrong for one and merely
harmless for the other, and ``48cda69`` was right. The exact tuple was dropped.
These tests pin that outcome so it cannot be quietly undone.
"""

import csv
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

from agamemnon import cli as CLI
from agamemnon.engine import bitstream_inspect as inspect


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION = ROOT / "qualification"
CHIPDB = ROOT / "agamemnon" / "chipdb"
ROUTED = QUALIFICATION / "mcu_ahb_constant_slave_routed.json"

# Silicon-correct for this pip: witnessed through public32's live bit 22, and
# accepted by the constant slave (image 3ef719a0..., 72/72 reads of 0x4147414d).
EXPECTED_SELECTOR = {2, 4}
# Refuted on hardware: reads bit 22 as 0 in public32 (ID32 -> 0x4107414d).
REFUTED_SELECTOR = {1, 6}
# The board-verified image the pinned netlist must pack to.
BOARD_VERIFIED_IMAGE = \
    "3ef719a08885b6eb6dba6dc25f08d9db79ad19399d8e18943b92929049e73bbc"
THE_EDGE = (13, 11, 9, 14, 11, 3)  # X13Y11_BBMUXE09 <- X14Y11_RMUX03


def _bbmuxe9_x13y11_selection(raw):
    by_bit, _ = inspect.agasc.load_feature_map(CHIPDB)
    selected = set()
    for (byte, mask), (x, y, feature) in by_bit.items():
        if x == 13 and y == 11 and feature.startswith("BBMUXE9["):
            if raw[byte] & mask:
                selected.add(int(feature[len("BBMUXE9["):-1]))
    return selected


def _pack_pinned_routed_json(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("AGAMEMNON_")}
    env.update({"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"})
    output = tmp_path / "constant_slave.bin"
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", str(ROUTED), str(output)],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_pinned_constant_slave_packs_to_the_board_verified_image(tmp_path):
    output = _pack_pinned_routed_json(tmp_path)
    assert output.stat().st_size == 99_944
    assert hashlib.sha256(output.read_bytes()).hexdigest() == BOARD_VERIFIED_IMAGE, (
        "the pinned 2026-08-02 netlist no longer packs to the image that was "
        "read on the L48 board (72/72 reads of 0x4147414d). Do not re-baseline "
        "this hash without a fresh board run -- that is exactly how the T22-T24 "
        "regression went unnoticed."
    )


def test_constant_slave_bbmuxe09_selector_is_the_silicon_correct_encoding(tmp_path):
    output = _pack_pinned_routed_json(tmp_path)
    _header, raw, _metadata = CLI._read_fabric_image(str(output))
    selection = _bbmuxe9_x13y11_selection(raw)

    assert selection != REFUTED_SELECTOR, (
        "X13Y11 BBMUXE9 is back to the (1,6) encoding that A1b refuted on "
        "hardware: it reads bit 22 as 0, breaking every public32/status-overlay "
        "artifact (ID32 0x4147414d -> 0x4107414d). See this module's docstring."
    )
    assert selection == EXPECTED_SELECTOR, (
        "X13Y11 BBMUXE9 selector is %r, expected the silicon-correct %r"
        % (selection, EXPECTED_SELECTOR)
    )


def test_no_exact_tuple_overrides_the_fallback_for_this_edge():
    """Guard against re-adding the refuted row.

    bitgen consults the exact exit-pair tuples before the BBMUXE_PAIR
    source-index fallback, so a row here silently wins over the value that is
    actually silicon-witnessed. T26 added one; A1b removed it. If a future
    session re-adds it, this fails with the reason attached rather than
    breaking seven qualified pack artifacts.
    """
    from agamemnon.engine.features.mcu_ahb import EXIT_PAIR_FILES

    found = []
    for filename in EXIT_PAIR_FILES:
        path = CHIPDB / filename
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                edge = re.fullmatch(r"BBMUX[A-Z]+0*([0-9]+)", row.get("edge_res", ""))
                source = re.fullmatch(r"RMUX0*([0-9]+)", row.get("src_res", ""))
                if not edge or not source:
                    continue
                key = (int(row["edge_x"]), int(row["edge_y"]), int(edge.group(1)),
                       int(row["src_x"]), int(row["src_y"]), int(source.group(1)))
                if key == THE_EDGE:
                    found.append((filename, row.get("selectors"),
                                  row.get("evidence")))
    assert not found, (
        "an exact exit-pair tuple for X13Y11_BBMUXE09 <- X14Y11_RMUX03 is back: "
        "%r. The fallback value (2,4) is the one witnessed on silicon; the "
        "(1,6) tuple was refuted on the board in A1b. If new evidence really "
        "does justify an override, update this test and re-run the seven "
        "public32/status-overlay board matrices first." % (found,)
    )
