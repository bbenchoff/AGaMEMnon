"""Bound the experimental composition and retain the default refusal."""
import pytest
from agamemnon.engine import bram_emit


ENABLES = {f"PORT{port}_{signal}_EN": 1 for port in "AB" for signal in ("CLKIN", "CLKOUT")}


def emit(*, x=13, y=4, width=0, width_b=0, clkmode=1, enables=None, modes=None, allowed=True):
    return bram_emit.emit(x, y, width, clkmode, 0, ENABLES if enables is None else enables,
                          width_b=width_b, experimental=modes or {"PORTA_OUTREG":1,"PORTA_WRITETHRU":1,"PORTB_WRITETHRU":1},
                          allow_experimental=allowed)


@pytest.mark.parametrize("outreg,writhru", [(0,0),(0,1),(1,0),(1,1)])
def test_observed_combinations_emit_only_requested_mode_bits(outreg,writhru):
    bits=emit(modes={"PORTA_OUTREG":outreg,"PORTA_WRITETHRU":writhru,"PORTB_WRITETHRU":1})
    # Exact payload positions independently exercised by the retained matrix.
    assert ((69238,64) in bits) == bool(outreg)
    assert ((66918,128) in bits) == bool(writhru)
    assert (72718,64) in bits
    assert bits <= bram_emit.owned_surface(13,4,experimental=True)
    observed_modes={bm for (x,y,mux),cells in bram_emit.CELLS.items()
                    if (x,y)==(13,4) and mux in bram_emit.EXPERIMENTAL_OWNED_MUXES
                    for bm in cells.values() if bm in bits}
    expected={(72718,64)} | ({(69238,64)} if outreg else set()) | ({(66918,128)} if writhru else set())
    assert observed_modes==expected


def test_default_still_refuses_the_composition():
    with pytest.raises(ValueError,match="requires AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG"):
        emit(allowed=False)


@pytest.mark.parametrize("change", [
    {"y":1},{"width":8},{"width_b":8},{"clkmode":0},
    {"enables":{**ENABLES,"PORTA_CLKIN_EN":0}},
    {"enables":{**ENABLES,"PORTB_CLKOUT_EN":0}},
    {"enables":{**ENABLES,"PORTA_RSTIN_EN":1}},
    {"modes":{"PORTA_OUTREG":1,"PORTA_WRITETHRU":1}},
    {"modes":{"PORTA_OUTREG":1,"PORTB_WRITETHRU":1,"PACKEDMODE":1}},
    {"modes":{"PORTA_OUTREG":1,"PORTB_WRITETHRU":1,"PORTB_OUTREG":1}},
])
def test_unobserved_compositions_remain_refused(change):
    with pytest.raises(ValueError,match="at most one B4"):
        emit(**change)


def test_composition_still_requires_every_requested_cell(monkeypatch):
    monkeypatch.delitem(bram_emit.CELLS,(13,4,"CFG_SEL_WRITHU_A"))
    with pytest.raises(ValueError,match="no decoded cell"):
        emit()
