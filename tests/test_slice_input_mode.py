"""Used ordinary slices must not inherit dedicated Cin from the base image."""
from pathlib import Path

import pytest

from agamemnon.engine import default_frame
from agamemnon.engine.features.carry import FEATURE
from agamemnon.engine.features.protocol import BitstreamContext


CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon/chipdb"


@pytest.fixture(scope="module")
def fields():
    return FEATURE.load_slice_config(CHIPDB)


def ordinary_module(x, y, z, registered):
    return {"ports": {}, "netnames": {}, "cells": {"ordinary": {
        "type": "GENERIC_SLICE",
        "attributes": {"NEXTPNR_BEL": f"X{x}Y{y}_SLICE{z}"},
        "parameters": {"K": "100", "INIT": "1111000011110000",
                       "FF_USED": str(int(registered))},
        "connections": {"I": ["0", "0", 10, "0"],
                        "Q" if registered else "F": [11]},
    }}}


@pytest.mark.parametrize("site", [(20, 12, 6), (20, 11, 6), (19, 12, 6)])
@pytest.mark.parametrize("registered", [False, True])
def test_ordinary_input_c_overrides_base_carry_mode(fields, site, registered):
    module = ordinary_module(*site, registered)
    state = FEATURE.prepare(module, fields)
    image = bytearray(default_frame.build())
    x, y, z = site
    # Model the Qin bit already selected by routing; disabling Cin must retain it.
    qbyte, qmask = fields[x, y, f"CFG_LUTCMUX[{2*z}]"]
    image[qbyte] |= qmask
    before = bytes(image)
    context = BitstreamContext(image, module, CHIPDB, None, state=state)
    FEATURE.clear_bitstream(context)
    FEATURE.emit_bitstream(context)
    byte, mask = fields[x, y, f"CFG_LUTCMUX[{2*z+1}]"]
    assert not image[byte] & mask, "ordinary C still selects dedicated carry input"
    expected = bytearray(before)
    expected[byte] &= ~mask
    assert image == expected, "changed unrelated slice configuration or an unused slice"


def test_ordinary_slice_missing_carry_mode_field_refuses(fields):
    broken = dict(fields)
    del broken[20, 12, "CFG_LUTCMUX[13]"]
    with pytest.raises(SystemExit, match=r"CFG_LUTCMUX\[13\]"):
        FEATURE.prepare(ordinary_module(20, 12, 6, True), broken)


def test_final_audit_rejects_reintroduced_carry_mode(fields):
    module = ordinary_module(20, 12, 6, True)
    state = FEATURE.prepare(module, fields)
    image = bytearray(default_frame.build())
    context = BitstreamContext(image, module, CHIPDB, None, state=state)
    FEATURE.clear_bitstream(context)
    FEATURE.emit_bitstream(context)
    FEATURE.audit_bitstream(context)
    byte, mask = fields[20, 12, "CFG_LUTCMUX[13]"]
    image[byte] |= mask
    with pytest.raises(SystemExit, match="ordinary slice.*carry input"):
        FEATURE.audit_bitstream(context)


@pytest.mark.parametrize("init", [0, 0xffff, 0xaaaa, 0xcccc, 0xff00, 0x6666])
def test_lut_independent_of_c_preserves_all_configuration(fields, init):
    module = ordinary_module(20, 12, 6, False)
    module["cells"]["ordinary"]["parameters"]["INIT"] = f"{init:016b}"
    state = FEATURE.prepare(module, fields)
    image = bytearray(default_frame.build())
    before = bytes(image)
    context = BitstreamContext(image, module, CHIPDB, None, state=state)
    FEATURE.clear_bitstream(context)
    FEATURE.emit_bitstream(context)
    FEATURE.audit_bitstream(context)
    assert image == before
