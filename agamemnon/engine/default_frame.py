"""From-scratch design-neutral AGRV2K base-image generator (experimental).

This module synthesizes as much of the 99,936-byte design-neutral configuration
image as the *already-shipped* AGaMEMnon data allows, without loading the
vendor-derived ``fabric_default.bin`` canvas and without the not-yet-promoted
reserved routing/seam reset-polarity table.  Its purpose is to make one fact
concrete and tested: AGaMEMnon's last vendor dependency is *exactly one*
promotable table.

Emitted entirely from shipped constants/tables (no canvas byte is read):

* **Preamble** (164 B) via :mod:`agamemnon.engine.preamble` (``build``), which
  reconstructs the configuration-chain records from declarative constants.
* **Border/edge NAMED config** (:data:`BORDER_NAMED_CONFIG`) resolved to
  physical bits through the shipped feature tables
  (:func:`agamemnon.engine.agasc.load_feature_map`).  These are the same bit
  families the open flow already emits for real designs; only their
  design-neutral *selection* is declared here, exactly as the preamble declares
  ``IDLE_PROFILE``.
* **Per-word-line col-58 framing nibble** (0x0f on word-lines 22..497), a
  geometric rule measured from the decoded canvas.
* **The unconfigured-LUT / all-zero regions** -- a zeros base reproduces the
  0x00 default (measured; see ``docs/FABRIC_DEFAULT_CANVAS.md``).
* **CRC-32/BZIP2** recomputed over the canonical header + image.

Reserved routing/seam SRAM region -- now emitted from the promoted table:

* The **reserved routing/seam SRAM all-ones default** is the LogicTile crossbar
  selector footprint (the CFG_RMUX/IMUX/SEAM/CTRL families decoded in the
  promoted ``logictile_config_template.csv``) whose unconfigured reset polarity
  is all-ones.  :func:`reserved_reset_fill` paints that footprint at its reset
  polarity, driven by the promoted table (fail-closed if the table does not
  decode the expected selector families); no canvas byte is copied.  The table's
  ``(word-row, bank-col)`` cells map into the config body through the
  vendor-validated transform (y-stride 63104, x-stride 36 bits, one bit-line per
  bank column), byte-exact on 279,672 shipped selector cells across 181 tiles.

Declared, documented residual (left as zeros -- never copied or faked):

* ~227 region-edge/partial bytes carry partially-set bit-lines needing a
  per-bit decode; they are left at zero.  See ``docs/FABRIC_DEFAULT_CANVAS.md``.

Measured today: the body region ``[164:99932]`` reconstructs to ~99.77 percent
byte-exact vs the decoded canvas (99,541 / 99,768); zeros/preamble alone give
70.33 percent, named/framing carry it to ~71 percent, and the reserved-reset
fill closes it to ~99.77 percent.

Nothing here changes default bitgen: it is reached only through the opt-in
``AGAMEMNON_FROM_SCRATCH_BASE`` switch (off by default).
"""

from __future__ import annotations

import struct
from pathlib import Path

from agamemnon.engine import agasc, preamble


CHIPDB_ROOT = Path(__file__).resolve().parent.parent / "chipdb"

RAW_LEN = agasc.RAW_LEN                     # 99,936
CRC_OFFSET = agasc.CRC_OFFSET              # 99,932
PREAMBLE_LENGTH = preamble.PREAMBLE_LENGTH  # 164
BODY_START = PREAMBLE_LENGTH

# Config-chain geometry: the body is a grid of 116-byte word-lines; a byte's
# position is  byte = 116*word_line + column + 164  (column in 0..115).
WORD_LINE_BYTES = 116

# Measured geometric rule (see docs/FABRIC_DEFAULT_CANVAS.md): every word-line in
# [22, 497] carries a 0x0f framing nibble at column 58; outside that contiguous
# range the column is 0x00.  A structural per-row marker, NOT the per-bit-line
# reset-polarity map that the reserved region needs.
FRAMING_COLUMN = 58
FRAMING_NIBBLE = 0x0F
FRAMING_WORD_LINES = range(22, 498)

# Reserved routing/seam SRAM: the LogicTile crossbar/selector bit-lines whose
# unconfigured reset polarity is all-ones.  RESERVED_COLUMNS is the main block's
# right-half column span; RESERVED_RECTANGLES is the full config-body footprint
# (measured geometry over the 116-byte word-line grid, the same measured-geometry
# basis as FRAMING_*).  reserved_reset_fill() paints these with RESERVED_RESET_BYTE
# using the promoted table for the bit-line resource identity; no canvas byte is
# ever read.  The four rectangles are the (word_line_range, column_range) spans of
# the all-ones region and cover exactly the 28,570 canvas 0xFF body bytes.
RESERVED_COLUMNS = range(59, 115)
RESERVED_RESET_BYTE = 0xFF
RESERVED_RECTANGLES = (
    (range(0, 498), range(59, 115)),   # main crossbar block (right-half columns)
    (range(0, 22), range(36, 59)),     # top tile-row selector band
    (range(0, 22), range(0, 4)),       # top-left seam band
    (range(838, 860), range(0, 4)),    # bottom-left seam band
)

# The decoded per-LogicTile bit-line template (promoted vendor DATA): maps each
# (word-row, bank-col) config cell to its CFG_<MUX> resource.  It supplies the
# resource identity + all-ones reset authority for the reserved region above and
# is registered in research_knowledge_manifest.json.
LOGICTILE_TEMPLATE = "logictile_config_template.csv"
# Crossbar/selector families that populate the reserved routing/seam region; the
# fill fails closed if the promoted table does not decode all of them.
RESERVED_SELECTOR_FAMILIES = ("CFG_RMUX", "CFG_IMUX", "CFG_SEAMMUX", "CFG_CTRLMUX")

# Canonical 8-byte image header (DEVICE_ID | max_index) -- pure constants.
DEVICE_ID = agasc.DEFAULT_DEVICE
MAX_INDEX = agasc.DEFAULT_MAX_INDEX
HEADER = struct.pack(">II", DEVICE_ID, MAX_INDEX)


# Design-neutral border/edge configuration.  Each entry is a shipped-feature-table
# key (X, Y) -> feature names; build() resolves every name to its physical
# (byte, mask) through agasc.load_feature_map, so the emitted *values* come
# entirely from the shipped tables.  The neutral *selection* below was recovered
# from the shipped design-neutral image (same provenance model as
# preamble.IDLE_PROFILE) and expressed purely as understood, named routing/
# slice-control fields -- it contains NO reserved-SRAM (opaque) bit.
# 1460 features across 23 edge tiles.
BORDER_NAMED_CONFIG = {
    (0, 1): (
        "CFG_IOMUX0[6]", "CFG_IOMUX1[6]", "CFG_IOMUX2[6]", "CFG_IOMUX3[6]", "CFG_IOMUX4[6]",
                "CFG_IOMUX5[6]"
    ),
    (0, 2): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]",
                "CFG_IOMUX4[13]", "CFG_IOMUX4[20]", "CFG_IOMUX4[27]", "CFG_IOMUX4[34]",
                "CFG_IOMUX4[41]", "CFG_IOMUX4[6]", "CFG_IOMUX5[13]", "CFG_IOMUX5[20]",
                "CFG_IOMUX5[27]", "CFG_IOMUX5[34]", "CFG_IOMUX5[41]", "CFG_IOMUX5[6]"
    ),
    (0, 3): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]",
                "CFG_IOMUX4[13]", "CFG_IOMUX4[20]", "CFG_IOMUX4[27]", "CFG_IOMUX4[34]",
                "CFG_IOMUX4[41]", "CFG_IOMUX4[6]", "CFG_IOMUX5[13]", "CFG_IOMUX5[20]",
                "CFG_IOMUX5[27]", "CFG_IOMUX5[34]", "CFG_IOMUX5[41]", "CFG_IOMUX5[6]"
    ),
    (0, 4): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]",
                "CFG_IOMUX4[13]", "CFG_IOMUX4[20]", "CFG_IOMUX4[27]", "CFG_IOMUX4[34]",
                "CFG_IOMUX4[41]", "CFG_IOMUX4[6]", "CFG_IOMUX5[13]", "CFG_IOMUX5[20]",
                "CFG_IOMUX5[27]", "CFG_IOMUX5[34]", "CFG_IOMUX5[41]", "CFG_IOMUX5[6]"
    ),
    (1, 0): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[34]", "CFG_IOMUX0[41]", "CFG_IOMUX0[6]",
                "CFG_IOMUX1[20]", "CFG_IOMUX1[27]", "CFG_IOMUX2[13]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[20]", "CFG_IOMUX3[27]"
    ),
    (2, 0): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]"
    ),
    (3, 0): (
        "CFG_IOMUX0[34]", "CFG_IOMUX0[6]", "CFG_IOMUX1[20]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[6]", "CFG_IOMUX3[20]"
    ),
    (14, 13): (
        "CFG_IOMUX0[34]", "CFG_IOMUX0[6]", "CFG_IOMUX1[20]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[6]", "CFG_IOMUX3[20]"
    ),
    (15, 13): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]"
    ),
    (16, 0): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[34]", "CFG_IOMUX0[41]",
                "CFG_IOMUX0[6]", "CFG_IOMUX1[20]", "CFG_IOMUX1[27]", "CFG_IOMUX1[34]",
                "CFG_IOMUX1[6]", "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[20]", "CFG_IOMUX3[27]",
                "CFG_IOMUX3[34]", "CFG_IOMUX3[6]"
    ),
    (16, 13): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]"
    ),
    (17, 0): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[34]", "CFG_IOMUX0[41]", "CFG_IOMUX0[6]",
                "CFG_IOMUX1[20]", "CFG_IOMUX1[27]", "CFG_IOMUX2[13]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[20]", "CFG_IOMUX3[27]"
    ),
    (17, 13): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]"
    ),
    (18, 13): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[34]",
                "CFG_IOMUX0[41]", "CFG_IOMUX0[6]", "CFG_IOMUX1[13]", "CFG_IOMUX1[20]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[34]", "CFG_IOMUX1[41]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[41]", "CFG_IOMUX2[6]", "CFG_IOMUX3[13]", "CFG_IOMUX3[20]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[41]", "CFG_IOMUX3[6]"
    ),
    (19, 0): (
        "CFG_IOMUX0[34]", "CFG_IOMUX0[6]", "CFG_IOMUX1[20]", "CFG_IOMUX2[34]",
                "CFG_IOMUX2[6]", "CFG_IOMUX3[20]"
    ),
    (19, 13): (
        "CFG_IOMUX0[12]", "CFG_IOMUX0[17]", "CFG_IOMUX0[19]", "CFG_IOMUX0[8]",
                "CFG_IOMUX2[41]", "CFG_IOMUX3[27]", "CFG_IOMUX3[34]", "CFG_IOMUX3[6]"
    ),
    (20, 0): (
        "CFG_CTRLMUX0[0]", "CFG_CTRLMUX0[10]", "CFG_CTRLMUX0[11]", "CFG_CTRLMUX0[1]",
                "CFG_CTRLMUX0[2]", "CFG_CTRLMUX0[3]", "CFG_CTRLMUX0[4]", "CFG_CTRLMUX0[5]",
                "CFG_CTRLMUX0[6]", "CFG_CTRLMUX0[7]", "CFG_CTRLMUX0[8]", "CFG_CTRLMUX0[9]",
                "CFG_CTRLMUX1[0]", "CFG_CTRLMUX1[10]", "CFG_CTRLMUX1[11]", "CFG_CTRLMUX1[1]",
                "CFG_CTRLMUX1[2]", "CFG_CTRLMUX1[3]", "CFG_CTRLMUX1[4]", "CFG_CTRLMUX1[5]",
                "CFG_CTRLMUX1[6]", "CFG_CTRLMUX1[7]", "CFG_CTRLMUX1[8]", "CFG_CTRLMUX1[9]",
                "CFG_CTRLMUX2[0]", "CFG_CTRLMUX2[10]", "CFG_CTRLMUX2[11]", "CFG_CTRLMUX2[1]",
                "CFG_CTRLMUX2[2]", "CFG_CTRLMUX2[3]", "CFG_CTRLMUX2[4]", "CFG_CTRLMUX2[5]",
                "CFG_CTRLMUX2[6]", "CFG_CTRLMUX2[7]", "CFG_CTRLMUX2[8]", "CFG_CTRLMUX2[9]",
                "CFG_CTRLMUX3[0]", "CFG_CTRLMUX3[10]", "CFG_CTRLMUX3[11]", "CFG_CTRLMUX3[1]",
                "CFG_CTRLMUX3[2]", "CFG_CTRLMUX3[3]", "CFG_CTRLMUX3[4]", "CFG_CTRLMUX3[5]",
                "CFG_CTRLMUX3[6]", "CFG_CTRLMUX3[7]", "CFG_CTRLMUX3[8]", "CFG_CTRLMUX3[9]",
                "CFG_INDA_DELAY[0]", "CFG_INDA_DELAY[10]", "CFG_INDA_DELAY[11]",
                "CFG_INDA_DELAY[1]", "CFG_INDA_DELAY[2]", "CFG_INDA_DELAY[3]",
                "CFG_INDA_DELAY[4]", "CFG_INDA_DELAY[5]", "CFG_INDA_DELAY[6]",
                "CFG_INDA_DELAY[7]", "CFG_INDA_DELAY[8]", "CFG_INDA_DELAY[9]",
                "CFG_INPUTMUX0[0]", "CFG_INPUTMUX0[1]", "CFG_INPUTMUX1[0]",
                "CFG_INPUTMUX1[1]", "CFG_INPUTMUX2[0]", "CFG_INPUTMUX2[1]",
                "CFG_INPUTMUX3[0]", "CFG_INPUTMUX3[1]", "CFG_INREG_DELAY[0]",
                "CFG_INREG_DELAY[10]", "CFG_INREG_DELAY[11]", "CFG_INREG_DELAY[1]",
                "CFG_INREG_DELAY[2]", "CFG_INREG_DELAY[3]", "CFG_INREG_DELAY[4]",
                "CFG_INREG_DELAY[5]", "CFG_INREG_DELAY[6]", "CFG_INREG_DELAY[7]",
                "CFG_INREG_DELAY[8]", "CFG_INREG_DELAY[9]", "CFG_IN_ASYNC_MODE[0]",
                "CFG_IN_ASYNC_MODE[1]", "CFG_IN_ASYNC_MODE[2]", "CFG_IN_ASYNC_MODE[3]",
                "CFG_IN_POWERUP[0]", "CFG_IN_POWERUP[1]", "CFG_IN_POWERUP[2]",
                "CFG_IN_POWERUP[3]", "CFG_IN_SYNC_MODE[0]", "CFG_IN_SYNC_MODE[1]",
                "CFG_IN_SYNC_MODE[2]", "CFG_IN_SYNC_MODE[3]", "CFG_IOMUX0[0]",
                "CFG_IOMUX0[10]", "CFG_IOMUX0[11]", "CFG_IOMUX0[12]", "CFG_IOMUX0[13]",
                "CFG_IOMUX0[14]", "CFG_IOMUX0[15]", "CFG_IOMUX0[16]", "CFG_IOMUX0[17]",
                "CFG_IOMUX0[18]", "CFG_IOMUX0[19]", "CFG_IOMUX0[1]", "CFG_IOMUX0[20]",
                "CFG_IOMUX0[21]", "CFG_IOMUX0[22]", "CFG_IOMUX0[23]", "CFG_IOMUX0[24]",
                "CFG_IOMUX0[25]", "CFG_IOMUX0[26]", "CFG_IOMUX0[27]", "CFG_IOMUX0[28]",
                "CFG_IOMUX0[29]", "CFG_IOMUX0[2]", "CFG_IOMUX0[30]", "CFG_IOMUX0[31]",
                "CFG_IOMUX0[32]", "CFG_IOMUX0[33]", "CFG_IOMUX0[34]", "CFG_IOMUX0[35]",
                "CFG_IOMUX0[36]", "CFG_IOMUX0[37]", "CFG_IOMUX0[38]", "CFG_IOMUX0[39]",
                "CFG_IOMUX0[3]", "CFG_IOMUX0[40]", "CFG_IOMUX0[41]", "CFG_IOMUX0[4]",
                "CFG_IOMUX0[5]", "CFG_IOMUX0[6]", "CFG_IOMUX0[7]", "CFG_IOMUX0[8]",
                "CFG_IOMUX0[9]", "CFG_IOMUX1[0]", "CFG_IOMUX1[10]", "CFG_IOMUX1[11]",
                "CFG_IOMUX1[12]", "CFG_IOMUX1[13]", "CFG_IOMUX1[14]", "CFG_IOMUX1[15]",
                "CFG_IOMUX1[16]", "CFG_IOMUX1[17]", "CFG_IOMUX1[18]", "CFG_IOMUX1[19]",
                "CFG_IOMUX1[1]", "CFG_IOMUX1[20]", "CFG_IOMUX1[21]", "CFG_IOMUX1[22]",
                "CFG_IOMUX1[23]", "CFG_IOMUX1[24]", "CFG_IOMUX1[25]", "CFG_IOMUX1[26]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[28]", "CFG_IOMUX1[29]", "CFG_IOMUX1[2]",
                "CFG_IOMUX1[30]", "CFG_IOMUX1[31]", "CFG_IOMUX1[32]", "CFG_IOMUX1[33]",
                "CFG_IOMUX1[34]", "CFG_IOMUX1[35]", "CFG_IOMUX1[36]", "CFG_IOMUX1[37]",
                "CFG_IOMUX1[38]", "CFG_IOMUX1[39]", "CFG_IOMUX1[3]", "CFG_IOMUX1[40]",
                "CFG_IOMUX1[41]", "CFG_IOMUX1[4]", "CFG_IOMUX1[5]", "CFG_IOMUX1[6]",
                "CFG_IOMUX1[7]", "CFG_IOMUX1[8]", "CFG_IOMUX1[9]", "CFG_IOMUX2[0]",
                "CFG_IOMUX2[10]", "CFG_IOMUX2[11]", "CFG_IOMUX2[12]", "CFG_IOMUX2[13]",
                "CFG_IOMUX2[14]", "CFG_IOMUX2[15]", "CFG_IOMUX2[16]", "CFG_IOMUX2[17]",
                "CFG_IOMUX2[18]", "CFG_IOMUX2[19]", "CFG_IOMUX2[1]", "CFG_IOMUX2[20]",
                "CFG_IOMUX2[21]", "CFG_IOMUX2[22]", "CFG_IOMUX2[23]", "CFG_IOMUX2[24]",
                "CFG_IOMUX2[25]", "CFG_IOMUX2[26]", "CFG_IOMUX2[27]", "CFG_IOMUX2[28]",
                "CFG_IOMUX2[29]", "CFG_IOMUX2[2]", "CFG_IOMUX2[30]", "CFG_IOMUX2[31]",
                "CFG_IOMUX2[32]", "CFG_IOMUX2[33]", "CFG_IOMUX2[34]", "CFG_IOMUX2[35]",
                "CFG_IOMUX2[36]", "CFG_IOMUX2[37]", "CFG_IOMUX2[38]", "CFG_IOMUX2[39]",
                "CFG_IOMUX2[3]", "CFG_IOMUX2[40]", "CFG_IOMUX2[41]", "CFG_IOMUX2[4]",
                "CFG_IOMUX2[5]", "CFG_IOMUX2[6]", "CFG_IOMUX2[7]", "CFG_IOMUX2[8]",
                "CFG_IOMUX2[9]", "CFG_IOMUX3[0]", "CFG_IOMUX3[10]", "CFG_IOMUX3[11]",
                "CFG_IOMUX3[12]", "CFG_IOMUX3[13]", "CFG_IOMUX3[14]", "CFG_IOMUX3[15]",
                "CFG_IOMUX3[16]", "CFG_IOMUX3[17]", "CFG_IOMUX3[18]", "CFG_IOMUX3[19]",
                "CFG_IOMUX3[1]", "CFG_IOMUX3[20]", "CFG_IOMUX3[21]", "CFG_IOMUX3[22]",
                "CFG_IOMUX3[23]", "CFG_IOMUX3[24]", "CFG_IOMUX3[25]", "CFG_IOMUX3[26]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[28]", "CFG_IOMUX3[29]", "CFG_IOMUX3[2]",
                "CFG_IOMUX3[30]", "CFG_IOMUX3[31]", "CFG_IOMUX3[32]", "CFG_IOMUX3[33]",
                "CFG_IOMUX3[34]", "CFG_IOMUX3[35]", "CFG_IOMUX3[36]", "CFG_IOMUX3[37]",
                "CFG_IOMUX3[38]", "CFG_IOMUX3[39]", "CFG_IOMUX3[3]", "CFG_IOMUX3[40]",
                "CFG_IOMUX3[41]", "CFG_IOMUX3[4]", "CFG_IOMUX3[5]", "CFG_IOMUX3[6]",
                "CFG_IOMUX3[7]", "CFG_IOMUX3[8]", "CFG_IOMUX3[9]", "CFG_OE_ASYNC_MODE[0]",
                "CFG_OE_ASYNC_MODE[1]", "CFG_OE_ASYNC_MODE[2]", "CFG_OE_ASYNC_MODE[3]",
                "CFG_OE_POWERUP[0]", "CFG_OE_POWERUP[1]", "CFG_OE_POWERUP[2]",
                "CFG_OE_POWERUP[3]", "CFG_OE_REG_MODE[0]", "CFG_OE_REG_MODE[1]",
                "CFG_OE_REG_MODE[2]", "CFG_OE_REG_MODE[3]", "CFG_OE_SYNC_MODE[0]",
                "CFG_OE_SYNC_MODE[1]", "CFG_OE_SYNC_MODE[2]", "CFG_OE_SYNC_MODE[3]",
                "CFG_OUTDELAY[0]", "CFG_OUTDELAY[1]", "CFG_OUTDELAY[2]", "CFG_OUTDELAY[3]",
                "CFG_OUT_ASYNC_MODE[0]", "CFG_OUT_ASYNC_MODE[1]", "CFG_OUT_ASYNC_MODE[2]",
                "CFG_OUT_ASYNC_MODE[3]", "CFG_OUT_POWERUP[0]", "CFG_OUT_POWERUP[1]",
                "CFG_OUT_POWERUP[2]", "CFG_OUT_POWERUP[3]", "CFG_OUT_REG_MODE[0]",
                "CFG_OUT_REG_MODE[1]", "CFG_OUT_REG_MODE[2]", "CFG_OUT_REG_MODE[3]",
                "CFG_OUT_SYNC_MODE[0]", "CFG_OUT_SYNC_MODE[1]", "CFG_OUT_SYNC_MODE[2]",
                "CFG_OUT_SYNC_MODE[3]", "CFG_RMUX0[0]", "CFG_RMUX0[10]", "CFG_RMUX0[11]",
                "CFG_RMUX0[12]", "CFG_RMUX0[13]", "CFG_RMUX0[14]", "CFG_RMUX0[15]",
                "CFG_RMUX0[16]", "CFG_RMUX0[17]", "CFG_RMUX0[18]", "CFG_RMUX0[19]",
                "CFG_RMUX0[1]", "CFG_RMUX0[20]", "CFG_RMUX0[21]", "CFG_RMUX0[22]",
                "CFG_RMUX0[23]", "CFG_RMUX0[24]", "CFG_RMUX0[25]", "CFG_RMUX0[26]",
                "CFG_RMUX0[27]", "CFG_RMUX0[28]", "CFG_RMUX0[29]", "CFG_RMUX0[2]",
                "CFG_RMUX0[30]", "CFG_RMUX0[31]", "CFG_RMUX0[32]", "CFG_RMUX0[33]",
                "CFG_RMUX0[34]", "CFG_RMUX0[35]", "CFG_RMUX0[36]", "CFG_RMUX0[37]",
                "CFG_RMUX0[38]", "CFG_RMUX0[39]", "CFG_RMUX0[3]", "CFG_RMUX0[40]",
                "CFG_RMUX0[41]", "CFG_RMUX0[42]", "CFG_RMUX0[43]", "CFG_RMUX0[44]",
                "CFG_RMUX0[45]", "CFG_RMUX0[46]", "CFG_RMUX0[47]", "CFG_RMUX0[4]",
                "CFG_RMUX0[5]", "CFG_RMUX0[6]", "CFG_RMUX0[7]", "CFG_RMUX0[8]",
                "CFG_RMUX0[9]", "CFG_RMUX1[0]", "CFG_RMUX1[10]", "CFG_RMUX1[11]",
                "CFG_RMUX1[12]", "CFG_RMUX1[13]", "CFG_RMUX1[14]", "CFG_RMUX1[15]",
                "CFG_RMUX1[16]", "CFG_RMUX1[17]", "CFG_RMUX1[18]", "CFG_RMUX1[19]",
                "CFG_RMUX1[1]", "CFG_RMUX1[20]", "CFG_RMUX1[21]", "CFG_RMUX1[22]",
                "CFG_RMUX1[23]", "CFG_RMUX1[24]", "CFG_RMUX1[25]", "CFG_RMUX1[26]",
                "CFG_RMUX1[27]", "CFG_RMUX1[28]", "CFG_RMUX1[29]", "CFG_RMUX1[2]",
                "CFG_RMUX1[30]", "CFG_RMUX1[31]", "CFG_RMUX1[32]", "CFG_RMUX1[33]",
                "CFG_RMUX1[34]", "CFG_RMUX1[35]", "CFG_RMUX1[36]", "CFG_RMUX1[37]",
                "CFG_RMUX1[38]", "CFG_RMUX1[39]", "CFG_RMUX1[3]", "CFG_RMUX1[40]",
                "CFG_RMUX1[41]", "CFG_RMUX1[42]", "CFG_RMUX1[43]", "CFG_RMUX1[44]",
                "CFG_RMUX1[45]", "CFG_RMUX1[46]", "CFG_RMUX1[47]", "CFG_RMUX1[4]",
                "CFG_RMUX1[5]", "CFG_RMUX1[6]", "CFG_RMUX1[7]", "CFG_RMUX1[8]",
                "CFG_RMUX1[9]", "CFG_RMUX2[0]", "CFG_RMUX2[10]", "CFG_RMUX2[11]",
                "CFG_RMUX2[12]", "CFG_RMUX2[13]", "CFG_RMUX2[14]", "CFG_RMUX2[15]",
                "CFG_RMUX2[16]", "CFG_RMUX2[17]", "CFG_RMUX2[18]", "CFG_RMUX2[19]",
                "CFG_RMUX2[1]", "CFG_RMUX2[20]", "CFG_RMUX2[21]", "CFG_RMUX2[22]",
                "CFG_RMUX2[23]", "CFG_RMUX2[24]", "CFG_RMUX2[25]", "CFG_RMUX2[26]",
                "CFG_RMUX2[27]", "CFG_RMUX2[28]", "CFG_RMUX2[29]", "CFG_RMUX2[2]",
                "CFG_RMUX2[30]", "CFG_RMUX2[31]", "CFG_RMUX2[32]", "CFG_RMUX2[33]",
                "CFG_RMUX2[34]", "CFG_RMUX2[35]", "CFG_RMUX2[36]", "CFG_RMUX2[37]",
                "CFG_RMUX2[38]", "CFG_RMUX2[39]", "CFG_RMUX2[3]", "CFG_RMUX2[40]",
                "CFG_RMUX2[41]", "CFG_RMUX2[42]", "CFG_RMUX2[43]", "CFG_RMUX2[44]",
                "CFG_RMUX2[45]", "CFG_RMUX2[46]", "CFG_RMUX2[47]", "CFG_RMUX2[4]",
                "CFG_RMUX2[5]", "CFG_RMUX2[6]", "CFG_RMUX2[7]", "CFG_RMUX2[8]",
                "CFG_RMUX2[9]", "CFG_RMUX3[0]", "CFG_RMUX3[10]", "CFG_RMUX3[11]",
                "CFG_RMUX3[12]", "CFG_RMUX3[13]", "CFG_RMUX3[14]", "CFG_RMUX3[15]",
                "CFG_RMUX3[16]", "CFG_RMUX3[17]", "CFG_RMUX3[18]", "CFG_RMUX3[19]",
                "CFG_RMUX3[1]", "CFG_RMUX3[20]", "CFG_RMUX3[21]", "CFG_RMUX3[22]",
                "CFG_RMUX3[23]", "CFG_RMUX3[24]", "CFG_RMUX3[25]", "CFG_RMUX3[26]",
                "CFG_RMUX3[27]", "CFG_RMUX3[28]", "CFG_RMUX3[29]", "CFG_RMUX3[2]",
                "CFG_RMUX3[30]", "CFG_RMUX3[31]", "CFG_RMUX3[32]", "CFG_RMUX3[33]",
                "CFG_RMUX3[34]", "CFG_RMUX3[35]", "CFG_RMUX3[36]", "CFG_RMUX3[37]",
                "CFG_RMUX3[38]", "CFG_RMUX3[39]", "CFG_RMUX3[3]", "CFG_RMUX3[40]",
                "CFG_RMUX3[41]", "CFG_RMUX3[42]", "CFG_RMUX3[43]", "CFG_RMUX3[44]",
                "CFG_RMUX3[45]", "CFG_RMUX3[46]", "CFG_RMUX3[47]", "CFG_RMUX3[4]",
                "CFG_RMUX3[5]", "CFG_RMUX3[6]", "CFG_RMUX3[7]", "CFG_RMUX3[8]",
                "CFG_RMUX3[9]", "CFG_SEAMMUX[0]", "CFG_SEAMMUX[10]", "CFG_SEAMMUX[11]",
                "CFG_SEAMMUX[12]", "CFG_SEAMMUX[13]", "CFG_SEAMMUX[14]", "CFG_SEAMMUX[15]",
                "CFG_SEAMMUX[16]", "CFG_SEAMMUX[17]", "CFG_SEAMMUX[18]", "CFG_SEAMMUX[19]",
                "CFG_SEAMMUX[1]", "CFG_SEAMMUX[20]", "CFG_SEAMMUX[21]", "CFG_SEAMMUX[22]",
                "CFG_SEAMMUX[23]", "CFG_SEAMMUX[24]", "CFG_SEAMMUX[25]", "CFG_SEAMMUX[26]",
                "CFG_SEAMMUX[27]", "CFG_SEAMMUX[28]", "CFG_SEAMMUX[29]", "CFG_SEAMMUX[2]",
                "CFG_SEAMMUX[30]", "CFG_SEAMMUX[31]", "CFG_SEAMMUX[32]", "CFG_SEAMMUX[33]",
                "CFG_SEAMMUX[34]", "CFG_SEAMMUX[35]", "CFG_SEAMMUX[36]", "CFG_SEAMMUX[37]",
                "CFG_SEAMMUX[38]", "CFG_SEAMMUX[39]", "CFG_SEAMMUX[3]", "CFG_SEAMMUX[40]",
                "CFG_SEAMMUX[41]", "CFG_SEAMMUX[42]", "CFG_SEAMMUX[43]", "CFG_SEAMMUX[44]",
                "CFG_SEAMMUX[45]", "CFG_SEAMMUX[46]", "CFG_SEAMMUX[47]", "CFG_SEAMMUX[4]",
                "CFG_SEAMMUX[5]", "CFG_SEAMMUX[6]", "CFG_SEAMMUX[7]", "CFG_SEAMMUX[8]",
                "CFG_SEAMMUX[9]"
    ),
    (20, 11): (
        "CFG_LUTCMUX[11]", "CFG_LUTCMUX[13]", "CFG_LUTCMUX[15]", "CFG_LUTCMUX[17]",
                "CFG_LUTCMUX[1]", "CFG_LUTCMUX[3]", "CFG_LUTCMUX[5]", "CFG_LUTCMUX[7]",
                "CFG_LUTCMUX[9]", "CFG_OMUX0[1]", "CFG_OMUX1[1]", "CFG_OMUX2[1]",
                "CFG_OMUX3[1]", "CFG_OMUX4[1]", "CFG_OMUX5[1]", "CFG_OMUX5[2]",
                "CFG_OMUX6[1]", "CFG_OMUX7[1]", "CFG_OMUX8[1]", "CFG_OMUX8[2]",
                "CFG_SEAMMUX[0]"
    ),
    (20, 12): (
        "CFG_LUTCMUX[11]", "CFG_LUTCMUX[13]", "CFG_LUTCMUX[15]", "CFG_LUTCMUX[17]",
                "CFG_LUTCMUX[19]", "CFG_LUTCMUX[1]", "CFG_LUTCMUX[21]", "CFG_LUTCMUX[23]",
                "CFG_LUTCMUX[25]", "CFG_LUTCMUX[27]", "CFG_LUTCMUX[29]", "CFG_LUTCMUX[31]",
                "CFG_LUTCMUX[3]", "CFG_LUTCMUX[5]", "CFG_LUTCMUX[7]", "CFG_LUTCMUX[9]",
                "CFG_OMUX10[1]", "CFG_OMUX11[1]", "CFG_OMUX12[1]", "CFG_OMUX13[1]",
                "CFG_OMUX14[1]", "CFG_OMUX15[1]", "CFG_OMUX1[1]", "CFG_OMUX2[1]",
                "CFG_OMUX3[1]", "CFG_OMUX4[1]", "CFG_OMUX5[1]", "CFG_OMUX6[1]",
                "CFG_OMUX7[1]", "CFG_OMUX8[1]", "CFG_OMUX9[1]", "CFG_SEAMMUX[0]"
    ),
    (20, 13): (
        "CFG_CTRLMUX0[0]", "CFG_CTRLMUX0[10]", "CFG_CTRLMUX0[11]", "CFG_CTRLMUX0[1]",
                "CFG_CTRLMUX0[2]", "CFG_CTRLMUX0[3]", "CFG_CTRLMUX0[4]", "CFG_CTRLMUX0[5]",
                "CFG_CTRLMUX0[6]", "CFG_CTRLMUX0[7]", "CFG_CTRLMUX0[8]", "CFG_CTRLMUX0[9]",
                "CFG_CTRLMUX1[0]", "CFG_CTRLMUX1[10]", "CFG_CTRLMUX1[11]", "CFG_CTRLMUX1[1]",
                "CFG_CTRLMUX1[2]", "CFG_CTRLMUX1[3]", "CFG_CTRLMUX1[4]", "CFG_CTRLMUX1[5]",
                "CFG_CTRLMUX1[6]", "CFG_CTRLMUX1[7]", "CFG_CTRLMUX1[8]", "CFG_CTRLMUX1[9]",
                "CFG_CTRLMUX2[0]", "CFG_CTRLMUX2[10]", "CFG_CTRLMUX2[11]", "CFG_CTRLMUX2[1]",
                "CFG_CTRLMUX2[2]", "CFG_CTRLMUX2[3]", "CFG_CTRLMUX2[4]", "CFG_CTRLMUX2[5]",
                "CFG_CTRLMUX2[6]", "CFG_CTRLMUX2[7]", "CFG_CTRLMUX2[8]", "CFG_CTRLMUX2[9]",
                "CFG_CTRLMUX3[0]", "CFG_CTRLMUX3[10]", "CFG_CTRLMUX3[11]", "CFG_CTRLMUX3[1]",
                "CFG_CTRLMUX3[2]", "CFG_CTRLMUX3[3]", "CFG_CTRLMUX3[4]", "CFG_CTRLMUX3[5]",
                "CFG_CTRLMUX3[6]", "CFG_CTRLMUX3[7]", "CFG_CTRLMUX3[8]", "CFG_CTRLMUX3[9]",
                "CFG_INDA_DELAY[0]", "CFG_INDA_DELAY[10]", "CFG_INDA_DELAY[11]",
                "CFG_INDA_DELAY[1]", "CFG_INDA_DELAY[2]", "CFG_INDA_DELAY[3]",
                "CFG_INDA_DELAY[4]", "CFG_INDA_DELAY[5]", "CFG_INDA_DELAY[6]",
                "CFG_INDA_DELAY[7]", "CFG_INDA_DELAY[8]", "CFG_INDA_DELAY[9]",
                "CFG_INPUTMUX0[0]", "CFG_INPUTMUX0[1]", "CFG_INPUTMUX1[0]",
                "CFG_INPUTMUX1[1]", "CFG_INPUTMUX2[0]", "CFG_INPUTMUX2[1]",
                "CFG_INPUTMUX3[0]", "CFG_INPUTMUX3[1]", "CFG_INREG_DELAY[0]",
                "CFG_INREG_DELAY[10]", "CFG_INREG_DELAY[11]", "CFG_INREG_DELAY[1]",
                "CFG_INREG_DELAY[2]", "CFG_INREG_DELAY[3]", "CFG_INREG_DELAY[4]",
                "CFG_INREG_DELAY[5]", "CFG_INREG_DELAY[6]", "CFG_INREG_DELAY[7]",
                "CFG_INREG_DELAY[8]", "CFG_INREG_DELAY[9]", "CFG_IN_ASYNC_MODE[0]",
                "CFG_IN_ASYNC_MODE[1]", "CFG_IN_ASYNC_MODE[2]", "CFG_IN_ASYNC_MODE[3]",
                "CFG_IN_POWERUP[0]", "CFG_IN_POWERUP[1]", "CFG_IN_POWERUP[2]",
                "CFG_IN_POWERUP[3]", "CFG_IN_SYNC_MODE[0]", "CFG_IN_SYNC_MODE[1]",
                "CFG_IN_SYNC_MODE[2]", "CFG_IN_SYNC_MODE[3]", "CFG_IOMUX0[0]",
                "CFG_IOMUX0[10]", "CFG_IOMUX0[11]", "CFG_IOMUX0[12]", "CFG_IOMUX0[13]",
                "CFG_IOMUX0[14]", "CFG_IOMUX0[15]", "CFG_IOMUX0[16]", "CFG_IOMUX0[17]",
                "CFG_IOMUX0[18]", "CFG_IOMUX0[19]", "CFG_IOMUX0[1]", "CFG_IOMUX0[20]",
                "CFG_IOMUX0[21]", "CFG_IOMUX0[22]", "CFG_IOMUX0[23]", "CFG_IOMUX0[24]",
                "CFG_IOMUX0[25]", "CFG_IOMUX0[26]", "CFG_IOMUX0[27]", "CFG_IOMUX0[28]",
                "CFG_IOMUX0[29]", "CFG_IOMUX0[2]", "CFG_IOMUX0[30]", "CFG_IOMUX0[31]",
                "CFG_IOMUX0[32]", "CFG_IOMUX0[33]", "CFG_IOMUX0[34]", "CFG_IOMUX0[35]",
                "CFG_IOMUX0[36]", "CFG_IOMUX0[37]", "CFG_IOMUX0[38]", "CFG_IOMUX0[39]",
                "CFG_IOMUX0[3]", "CFG_IOMUX0[40]", "CFG_IOMUX0[41]", "CFG_IOMUX0[4]",
                "CFG_IOMUX0[5]", "CFG_IOMUX0[6]", "CFG_IOMUX0[7]", "CFG_IOMUX0[8]",
                "CFG_IOMUX0[9]", "CFG_IOMUX1[0]", "CFG_IOMUX1[10]", "CFG_IOMUX1[11]",
                "CFG_IOMUX1[12]", "CFG_IOMUX1[13]", "CFG_IOMUX1[14]", "CFG_IOMUX1[15]",
                "CFG_IOMUX1[16]", "CFG_IOMUX1[17]", "CFG_IOMUX1[18]", "CFG_IOMUX1[19]",
                "CFG_IOMUX1[1]", "CFG_IOMUX1[20]", "CFG_IOMUX1[21]", "CFG_IOMUX1[22]",
                "CFG_IOMUX1[23]", "CFG_IOMUX1[24]", "CFG_IOMUX1[25]", "CFG_IOMUX1[26]",
                "CFG_IOMUX1[27]", "CFG_IOMUX1[28]", "CFG_IOMUX1[29]", "CFG_IOMUX1[2]",
                "CFG_IOMUX1[30]", "CFG_IOMUX1[31]", "CFG_IOMUX1[32]", "CFG_IOMUX1[33]",
                "CFG_IOMUX1[34]", "CFG_IOMUX1[35]", "CFG_IOMUX1[36]", "CFG_IOMUX1[37]",
                "CFG_IOMUX1[38]", "CFG_IOMUX1[39]", "CFG_IOMUX1[3]", "CFG_IOMUX1[40]",
                "CFG_IOMUX1[41]", "CFG_IOMUX1[4]", "CFG_IOMUX1[5]", "CFG_IOMUX1[6]",
                "CFG_IOMUX1[7]", "CFG_IOMUX1[8]", "CFG_IOMUX1[9]", "CFG_IOMUX2[0]",
                "CFG_IOMUX2[10]", "CFG_IOMUX2[11]", "CFG_IOMUX2[12]", "CFG_IOMUX2[13]",
                "CFG_IOMUX2[14]", "CFG_IOMUX2[15]", "CFG_IOMUX2[16]", "CFG_IOMUX2[17]",
                "CFG_IOMUX2[18]", "CFG_IOMUX2[19]", "CFG_IOMUX2[1]", "CFG_IOMUX2[20]",
                "CFG_IOMUX2[21]", "CFG_IOMUX2[22]", "CFG_IOMUX2[23]", "CFG_IOMUX2[24]",
                "CFG_IOMUX2[25]", "CFG_IOMUX2[26]", "CFG_IOMUX2[27]", "CFG_IOMUX2[28]",
                "CFG_IOMUX2[29]", "CFG_IOMUX2[2]", "CFG_IOMUX2[30]", "CFG_IOMUX2[31]",
                "CFG_IOMUX2[32]", "CFG_IOMUX2[33]", "CFG_IOMUX2[34]", "CFG_IOMUX2[35]",
                "CFG_IOMUX2[36]", "CFG_IOMUX2[37]", "CFG_IOMUX2[38]", "CFG_IOMUX2[39]",
                "CFG_IOMUX2[3]", "CFG_IOMUX2[40]", "CFG_IOMUX2[41]", "CFG_IOMUX2[4]",
                "CFG_IOMUX2[5]", "CFG_IOMUX2[6]", "CFG_IOMUX2[7]", "CFG_IOMUX2[8]",
                "CFG_IOMUX2[9]", "CFG_IOMUX3[0]", "CFG_IOMUX3[10]", "CFG_IOMUX3[11]",
                "CFG_IOMUX3[12]", "CFG_IOMUX3[13]", "CFG_IOMUX3[14]", "CFG_IOMUX3[15]",
                "CFG_IOMUX3[16]", "CFG_IOMUX3[17]", "CFG_IOMUX3[18]", "CFG_IOMUX3[19]",
                "CFG_IOMUX3[1]", "CFG_IOMUX3[20]", "CFG_IOMUX3[21]", "CFG_IOMUX3[22]",
                "CFG_IOMUX3[23]", "CFG_IOMUX3[24]", "CFG_IOMUX3[25]", "CFG_IOMUX3[26]",
                "CFG_IOMUX3[27]", "CFG_IOMUX3[28]", "CFG_IOMUX3[29]", "CFG_IOMUX3[2]",
                "CFG_IOMUX3[30]", "CFG_IOMUX3[31]", "CFG_IOMUX3[32]", "CFG_IOMUX3[33]",
                "CFG_IOMUX3[34]", "CFG_IOMUX3[35]", "CFG_IOMUX3[36]", "CFG_IOMUX3[37]",
                "CFG_IOMUX3[38]", "CFG_IOMUX3[39]", "CFG_IOMUX3[3]", "CFG_IOMUX3[40]",
                "CFG_IOMUX3[41]", "CFG_IOMUX3[4]", "CFG_IOMUX3[5]", "CFG_IOMUX3[6]",
                "CFG_IOMUX3[7]", "CFG_IOMUX3[8]", "CFG_IOMUX3[9]", "CFG_OE_ASYNC_MODE[0]",
                "CFG_OE_ASYNC_MODE[1]", "CFG_OE_ASYNC_MODE[2]", "CFG_OE_ASYNC_MODE[3]",
                "CFG_OE_POWERUP[0]", "CFG_OE_POWERUP[1]", "CFG_OE_POWERUP[2]",
                "CFG_OE_POWERUP[3]", "CFG_OE_REG_MODE[0]", "CFG_OE_REG_MODE[1]",
                "CFG_OE_REG_MODE[2]", "CFG_OE_REG_MODE[3]", "CFG_OE_SYNC_MODE[0]",
                "CFG_OE_SYNC_MODE[1]", "CFG_OE_SYNC_MODE[2]", "CFG_OE_SYNC_MODE[3]",
                "CFG_OUTDELAY[0]", "CFG_OUTDELAY[1]", "CFG_OUTDELAY[2]", "CFG_OUTDELAY[3]",
                "CFG_OUT_ASYNC_MODE[0]", "CFG_OUT_ASYNC_MODE[1]", "CFG_OUT_ASYNC_MODE[2]",
                "CFG_OUT_ASYNC_MODE[3]", "CFG_OUT_POWERUP[0]", "CFG_OUT_POWERUP[1]",
                "CFG_OUT_POWERUP[2]", "CFG_OUT_POWERUP[3]", "CFG_OUT_REG_MODE[0]",
                "CFG_OUT_REG_MODE[1]", "CFG_OUT_REG_MODE[2]", "CFG_OUT_REG_MODE[3]",
                "CFG_OUT_SYNC_MODE[0]", "CFG_OUT_SYNC_MODE[1]", "CFG_OUT_SYNC_MODE[2]",
                "CFG_OUT_SYNC_MODE[3]", "CFG_RMUX0[0]", "CFG_RMUX0[10]", "CFG_RMUX0[11]",
                "CFG_RMUX0[12]", "CFG_RMUX0[13]", "CFG_RMUX0[14]", "CFG_RMUX0[15]",
                "CFG_RMUX0[16]", "CFG_RMUX0[17]", "CFG_RMUX0[18]", "CFG_RMUX0[19]",
                "CFG_RMUX0[1]", "CFG_RMUX0[20]", "CFG_RMUX0[21]", "CFG_RMUX0[22]",
                "CFG_RMUX0[23]", "CFG_RMUX0[24]", "CFG_RMUX0[25]", "CFG_RMUX0[26]",
                "CFG_RMUX0[27]", "CFG_RMUX0[28]", "CFG_RMUX0[29]", "CFG_RMUX0[2]",
                "CFG_RMUX0[30]", "CFG_RMUX0[31]", "CFG_RMUX0[32]", "CFG_RMUX0[33]",
                "CFG_RMUX0[34]", "CFG_RMUX0[35]", "CFG_RMUX0[36]", "CFG_RMUX0[37]",
                "CFG_RMUX0[38]", "CFG_RMUX0[39]", "CFG_RMUX0[3]", "CFG_RMUX0[40]",
                "CFG_RMUX0[41]", "CFG_RMUX0[42]", "CFG_RMUX0[43]", "CFG_RMUX0[44]",
                "CFG_RMUX0[45]", "CFG_RMUX0[46]", "CFG_RMUX0[47]", "CFG_RMUX0[4]",
                "CFG_RMUX0[5]", "CFG_RMUX0[6]", "CFG_RMUX0[7]", "CFG_RMUX0[8]",
                "CFG_RMUX0[9]", "CFG_RMUX1[0]", "CFG_RMUX1[10]", "CFG_RMUX1[11]",
                "CFG_RMUX1[12]", "CFG_RMUX1[13]", "CFG_RMUX1[14]", "CFG_RMUX1[15]",
                "CFG_RMUX1[16]", "CFG_RMUX1[17]", "CFG_RMUX1[18]", "CFG_RMUX1[19]",
                "CFG_RMUX1[1]", "CFG_RMUX1[20]", "CFG_RMUX1[21]", "CFG_RMUX1[22]",
                "CFG_RMUX1[23]", "CFG_RMUX1[24]", "CFG_RMUX1[25]", "CFG_RMUX1[26]",
                "CFG_RMUX1[27]", "CFG_RMUX1[28]", "CFG_RMUX1[29]", "CFG_RMUX1[2]",
                "CFG_RMUX1[30]", "CFG_RMUX1[31]", "CFG_RMUX1[32]", "CFG_RMUX1[33]",
                "CFG_RMUX1[34]", "CFG_RMUX1[35]", "CFG_RMUX1[36]", "CFG_RMUX1[37]",
                "CFG_RMUX1[38]", "CFG_RMUX1[39]", "CFG_RMUX1[3]", "CFG_RMUX1[40]",
                "CFG_RMUX1[41]", "CFG_RMUX1[42]", "CFG_RMUX1[43]", "CFG_RMUX1[44]",
                "CFG_RMUX1[45]", "CFG_RMUX1[46]", "CFG_RMUX1[47]", "CFG_RMUX1[4]",
                "CFG_RMUX1[5]", "CFG_RMUX1[6]", "CFG_RMUX1[7]", "CFG_RMUX1[8]",
                "CFG_RMUX1[9]", "CFG_RMUX2[0]", "CFG_RMUX2[10]", "CFG_RMUX2[11]",
                "CFG_RMUX2[12]", "CFG_RMUX2[13]", "CFG_RMUX2[14]", "CFG_RMUX2[15]",
                "CFG_RMUX2[16]", "CFG_RMUX2[17]", "CFG_RMUX2[18]", "CFG_RMUX2[19]",
                "CFG_RMUX2[1]", "CFG_RMUX2[20]", "CFG_RMUX2[21]", "CFG_RMUX2[22]",
                "CFG_RMUX2[23]", "CFG_RMUX2[24]", "CFG_RMUX2[25]", "CFG_RMUX2[26]",
                "CFG_RMUX2[27]", "CFG_RMUX2[28]", "CFG_RMUX2[29]", "CFG_RMUX2[2]",
                "CFG_RMUX2[30]", "CFG_RMUX2[31]", "CFG_RMUX2[32]", "CFG_RMUX2[33]",
                "CFG_RMUX2[34]", "CFG_RMUX2[35]", "CFG_RMUX2[36]", "CFG_RMUX2[37]",
                "CFG_RMUX2[38]", "CFG_RMUX2[39]", "CFG_RMUX2[3]", "CFG_RMUX2[40]",
                "CFG_RMUX2[41]", "CFG_RMUX2[42]", "CFG_RMUX2[43]", "CFG_RMUX2[44]",
                "CFG_RMUX2[45]", "CFG_RMUX2[46]", "CFG_RMUX2[47]", "CFG_RMUX2[4]",
                "CFG_RMUX2[5]", "CFG_RMUX2[6]", "CFG_RMUX2[7]", "CFG_RMUX2[8]",
                "CFG_RMUX2[9]", "CFG_RMUX3[0]", "CFG_RMUX3[10]", "CFG_RMUX3[11]",
                "CFG_RMUX3[12]", "CFG_RMUX3[13]", "CFG_RMUX3[14]", "CFG_RMUX3[15]",
                "CFG_RMUX3[16]", "CFG_RMUX3[17]", "CFG_RMUX3[18]", "CFG_RMUX3[19]",
                "CFG_RMUX3[1]", "CFG_RMUX3[20]", "CFG_RMUX3[21]", "CFG_RMUX3[22]",
                "CFG_RMUX3[23]", "CFG_RMUX3[24]", "CFG_RMUX3[25]", "CFG_RMUX3[26]",
                "CFG_RMUX3[27]", "CFG_RMUX3[28]", "CFG_RMUX3[29]", "CFG_RMUX3[2]",
                "CFG_RMUX3[30]", "CFG_RMUX3[31]", "CFG_RMUX3[32]", "CFG_RMUX3[33]",
                "CFG_RMUX3[34]", "CFG_RMUX3[35]", "CFG_RMUX3[36]", "CFG_RMUX3[37]",
                "CFG_RMUX3[38]", "CFG_RMUX3[39]", "CFG_RMUX3[3]", "CFG_RMUX3[40]",
                "CFG_RMUX3[41]", "CFG_RMUX3[42]", "CFG_RMUX3[43]", "CFG_RMUX3[44]",
                "CFG_RMUX3[45]", "CFG_RMUX3[46]", "CFG_RMUX3[47]", "CFG_RMUX3[4]",
                "CFG_RMUX3[5]", "CFG_RMUX3[6]", "CFG_RMUX3[7]", "CFG_RMUX3[8]",
                "CFG_RMUX3[9]", "CFG_SEAMMUX[0]", "CFG_SEAMMUX[10]", "CFG_SEAMMUX[11]",
                "CFG_SEAMMUX[12]", "CFG_SEAMMUX[13]", "CFG_SEAMMUX[14]", "CFG_SEAMMUX[15]",
                "CFG_SEAMMUX[16]", "CFG_SEAMMUX[17]", "CFG_SEAMMUX[18]", "CFG_SEAMMUX[19]",
                "CFG_SEAMMUX[1]", "CFG_SEAMMUX[20]", "CFG_SEAMMUX[21]", "CFG_SEAMMUX[22]",
                "CFG_SEAMMUX[23]", "CFG_SEAMMUX[24]", "CFG_SEAMMUX[25]", "CFG_SEAMMUX[26]",
                "CFG_SEAMMUX[27]", "CFG_SEAMMUX[28]", "CFG_SEAMMUX[29]", "CFG_SEAMMUX[2]",
                "CFG_SEAMMUX[30]", "CFG_SEAMMUX[31]", "CFG_SEAMMUX[32]", "CFG_SEAMMUX[33]",
                "CFG_SEAMMUX[34]", "CFG_SEAMMUX[35]", "CFG_SEAMMUX[36]", "CFG_SEAMMUX[37]",
                "CFG_SEAMMUX[38]", "CFG_SEAMMUX[39]", "CFG_SEAMMUX[3]", "CFG_SEAMMUX[40]",
                "CFG_SEAMMUX[41]", "CFG_SEAMMUX[42]", "CFG_SEAMMUX[43]", "CFG_SEAMMUX[44]",
                "CFG_SEAMMUX[45]", "CFG_SEAMMUX[46]", "CFG_SEAMMUX[47]", "CFG_SEAMMUX[4]",
                "CFG_SEAMMUX[5]", "CFG_SEAMMUX[6]", "CFG_SEAMMUX[7]", "CFG_SEAMMUX[8]",
                "CFG_SEAMMUX[9]"
    ),
    (22, 1): (
        "CFG_IOMUX0[6]", "CFG_IOMUX1[6]", "CFG_IOMUX2[6]", "CFG_IOMUX3[6]", "CFG_IOMUX4[6]",
                "CFG_IOMUX5[6]"
    ),
    (22, 3): (
        "CFG_IOMUX0[13]", "CFG_IOMUX0[20]", "CFG_IOMUX0[27]", "CFG_IOMUX0[6]",
                "CFG_IOMUX1[13]", "CFG_IOMUX1[20]", "CFG_IOMUX1[27]", "CFG_IOMUX1[6]",
                "CFG_IOMUX2[13]", "CFG_IOMUX2[20]", "CFG_IOMUX2[27]", "CFG_IOMUX2[6]",
                "CFG_IOMUX3[13]", "CFG_IOMUX3[20]", "CFG_IOMUX3[27]", "CFG_IOMUX3[6]",
                "CFG_IOMUX4[13]", "CFG_IOMUX4[20]", "CFG_IOMUX4[27]", "CFG_IOMUX4[6]",
                "CFG_IOMUX5[13]", "CFG_IOMUX5[20]", "CFG_IOMUX5[27]", "CFG_IOMUX5[6]"
    ),
    (22, 4): ("CFG_IOMUX0[2]", "CFG_IOMUX0[7]", "CFG_IOMUX1[9]"),
}


def header() -> bytes:
    """Return the canonical 8-byte image header (constants only)."""
    return HEADER


def _feature_map(chipdb_root=CHIPDB_ROOT):
    return agasc.load_feature_map(str(chipdb_root))


def load_logictile_template(chipdb_root=CHIPDB_ROOT):
    """Parse the promoted per-LogicTile bit-line template.

    Returns ``(cells, families)`` where ``cells[(word_row, bank_col)] = name``
    for every decoded config cell (``XXXX`` padding omitted) and ``families`` is
    the set of ``CFG_<MUX>`` family prefixes present.  This is the decoded vendor
    DATA that identifies the reserved region's bit-lines as routing/seam crossbar
    selectors (see ``docs/FABRIC_DEFAULT_CANVAS.md``).
    """
    import csv

    path = Path(chipdb_root) / LOGICTILE_TEMPLATE
    cells = {}
    families = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = {name: i for i, name in enumerate(header)}
        for row in reader:
            if not row or not row[0].startswith("W"):
                continue
            word_row = int(row[0][1:])
            for bank_col in range(36):
                col = index.get("B%d" % bank_col)
                if col is None or col >= len(row):
                    continue
                cell = row[col].strip()
                if not cell or cell == "XXXX":
                    continue
                name = cell.replace("<", "[").replace(">", "]")
                cells[(word_row, bank_col)] = name
                families.add(name.split("[", 1)[0].rstrip("0123456789"))
    return cells, families


def _reserved_offsets():
    """Return the frozenset of body byte offsets in the reserved rectangles."""
    offsets = set()
    for word_lines, columns in RESERVED_RECTANGLES:
        for word_line in word_lines:
            base = BODY_START + WORD_LINE_BYTES * word_line
            for column in columns:
                offset = base + column
                if offset < CRC_OFFSET:
                    offsets.add(offset)
    return frozenset(offsets)


def reserved_reset_fill(raw, *, chipdb_root=CHIPDB_ROOT):
    """Paint the reserved routing/seam SRAM region at its all-ones reset polarity.

    The bit-line *resource identity* comes from the promoted
    ``logictile_config_template.csv`` (the reserved region is the LogicTile
    CFG_RMUX/IMUX/SEAM/CTRL crossbar selectors); the *reset value* is all-ones
    (``RESERVED_RESET_BYTE``) and the config-body *footprint* is
    ``RESERVED_RECTANGLES``.  Fails closed if the promoted table does not decode
    the expected selector families, so the fill can never emit an unbacked
    region.  Reads no canvas byte.
    """
    _, families = load_logictile_template(chipdb_root)
    missing = [f for f in RESERVED_SELECTOR_FAMILIES if f not in families]
    if missing:
        raise agasc.AgascError(
            "logictile template does not decode reserved selector families: %r"
            % (missing,)
        )
    for offset in _reserved_offsets():
        raw[offset] = RESERVED_RESET_BYTE
    return raw


def build(*, clocked=False, sysclk=100, hse=8, named=True, framing=True,
          reserved=True, chipdb_root=CHIPDB_ROOT):
    """Return a 99,936-byte design-neutral raw image built from scratch.

    Starts from zeros, applies the declarative preamble, overlays the named
    border/edge configuration and the col-58 framing nibble, paints the reserved
    routing/seam SRAM region at its all-ones reset polarity from the promoted
    LogicTile template, and recomputes the CRC.  No byte is ever copied from the
    vendor canvas (``fabric_default.bin`` is never read here).
    """
    raw = bytearray(RAW_LEN)
    preamble.apply(raw, clocked=clocked, sysclk=sysclk, hse=hse)
    if named:
        _, by_feature = _feature_map(chipdb_root)
        for (x, y), features in BORDER_NAMED_CONFIG.items():
            for feature in features:
                byte, mask = by_feature[(x, y, feature)]
                raw[byte] |= mask
    if framing:
        for word_line in FRAMING_WORD_LINES:
            offset = BODY_START + WORD_LINE_BYTES * word_line + FRAMING_COLUMN
            raw[offset] = FRAMING_NIBBLE
    if reserved:
        reserved_reset_fill(raw, chipdb_root=chipdb_root)
    raw[CRC_OFFSET:] = struct.pack(
        ">I", agasc.crc32_bzip2(HEADER + bytes(raw[:CRC_OFFSET]))
    )
    return bytes(raw)


def _decode_canvas(chipdb_root=CHIPDB_ROOT):
    from agamemnon.engine import lzw_codec
    blob = (Path(chipdb_root) / "fabric_default.bin").read_bytes()
    payload = blob[8:]
    if len(payload) == RAW_LEN:
        return bytes(payload)
    return lzw_codec.decode(payload)


def _column(offset):
    return (offset - BODY_START) % WORD_LINE_BYTES


def _word_line(offset):
    return (offset - BODY_START) // WORD_LINE_BYTES


def diff_against_canvas(canvas_raw=None, *, chipdb_root=CHIPDB_ROOT, **build_kwargs):
    """Audit the from-scratch image against the decoded canvas.

    Returns byte-exact fractions and a per-family byte-value classifier over the
    body region [164:99932].  The canvas is read only for comparison; it never
    contributes a byte to the generated image.  ``reserved_sram_gap`` is the
    single unpromoted table's footprint and must show zero bytes emitted.
    """
    scratch = build(chipdb_root=chipdb_root, **build_kwargs)
    if canvas_raw is None:
        canvas_raw = _decode_canvas(chipdb_root)
    if len(canvas_raw) != RAW_LEN or len(scratch) != RAW_LEN:
        raise agasc.AgascError("diff requires two 99936-byte raw images")

    by_bit, _ = _feature_map(chipdb_root)
    named_mask = bytearray(RAW_LEN)
    for (byte, mask), (_x, _y, _feat) in by_bit.items():
        if byte < CRC_OFFSET and (canvas_raw[byte] & mask):
            named_mask[byte] |= mask

    reserved = _reserved_offsets()

    families = {}
    ff_outside_reserved = 0
    for offset in range(BODY_START, CRC_OFFSET):
        canvas = canvas_raw[offset]
        got = scratch[offset]
        column = _column(offset)
        if offset in reserved:
            family = "reserved_sram_fill"
        elif canvas == 0:
            family = "zero_default"
        elif named_mask[offset] and canvas == named_mask[offset]:
            family = "border_named"
        elif named_mask[offset]:
            family = "border_named_partial"
        elif column == FRAMING_COLUMN and _word_line(offset) in FRAMING_WORD_LINES:
            family = "framing_col58"
        elif canvas == 0xFF:
            family = "reserved_edge_gap"
        else:
            family = "region_edge_partial"
        # Invariant: the only all-ones body bytes the scratch image emits are the
        # declared reserved rectangles (and fully-named 0xFF bytes) -- never a
        # stray copy.
        if got == RESERVED_RESET_BYTE and offset not in reserved and got != named_mask[offset]:
            ff_outside_reserved += 1
        row = families.setdefault(family, {"total": 0, "matched": 0})
        row["total"] += 1
        row["matched"] += (canvas == got)

    body_total = CRC_OFFSET - BODY_START
    body_matched = sum(f["matched"] for f in families.values())
    for family in families.values():
        family["gap"] = family["total"] - family["matched"]
    return {
        "body_total": body_total,
        "body_matched": body_matched,
        "body_exact_fraction": body_matched / body_total,
        "preamble_exact": bytes(scratch[:BODY_START]) == bytes(canvas_raw[:BODY_START]),
        "reserved_fill_bytes": len(reserved),
        "ff_outside_reserved": ff_outside_reserved,
        "scratch_ff_body_bytes": sum(
            1 for i in range(BODY_START, CRC_OFFSET) if scratch[i] == 0xFF
        ),
        "families": families,
    }
