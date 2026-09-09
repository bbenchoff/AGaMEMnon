"""Mixed registers require an idle clock line, preserving ordinary input mode."""
import pytest
from agamemnon.engine import control_encode
from agamemnon.engine.features import shared_control_graph as shared

FEATURE=shared.SHARED_CONTROL_GRAPH_FEATURE

def module(line=0):
    return {'cells':{
        'control':{'type':'AGRV2K_TILE_CONTROL','attributes':{'NEXTPNR_BEL':f'X16Y10_CLKEN{line}','AGRV2K_CLOCK_ENABLE_NET':'enable'}},
        'native':{'type':'GENERIC_SLICE','parameters':{'FF_USED':'1'},'attributes':{'NEXTPNR_BEL':'X16Y10_SLICE0','AGRV2K_CLOCK_ENABLE_NET':'enable'}},
        'ordinary':{'type':'GENERIC_SLICE','parameters':{'FF_USED':'1'},'attributes':{'NEXTPNR_BEL':'X16Y10_SLICE15'}}}}

@pytest.mark.parametrize('line',[0,1])
def test_ordinary_register_uses_only_the_other_line(monkeypatch,line):
    monkeypatch.setenv(shared.MIXED_NATIVE_CONTROL_OPTION,'1')
    monkeypatch.setenv(shared.DUAL_NATIVE_CONTROL_OPTION,'1')
    m=module(line)
    assert FEATURE.slice_lines_from_module(m)=={(16,10,0):line,(16,10,15):1-line}

def test_mixed_requires_opt_in_and_idle_line(monkeypatch):
    monkeypatch.delenv(shared.MIXED_NATIVE_CONTROL_OPTION,raising=False)
    with pytest.raises(shared.SharedControlEmitError,match='mixed sequential'):
        FEATURE.slice_lines_from_module(module())
    monkeypatch.setenv(shared.MIXED_NATIVE_CONTROL_OPTION,'1')
    monkeypatch.setenv(shared.DUAL_NATIVE_CONTROL_OPTION,'1')
    m=module()
    m['cells']['second']={'type':'AGRV2K_TILE_CONTROL','attributes':{'NEXTPNR_BEL':'X16Y10_CLKEN1','AGRV2K_CLOCK_ENABLE_NET':'other'}}
    with pytest.raises(shared.SharedControlEmitError,match='one idle local clock line'):
        FEATURE.slice_lines_from_module(m)

def test_ordinary_bypass_mode_is_preserved(monkeypatch):
    monkeypatch.setenv(shared.MIXED_NATIVE_CONTROL_OPTION,'1')
    m=module();lines=FEATURE.slice_lines_from_module(m)
    state=FEATURE.prepare([],{},slice_lines=lines,ordinary_slices=FEATURE.ordinary_slice_sites_from_module(m))
    assert control_encode.slice_bypass_bit(16,10,15) not in state.clears
    assert control_encode.slice_bypass_bit(16,10,0) in state.clears
    assert control_encode.slice_line_bit(16,10,15,'clock_enable') in state.sets

def test_actual_routed_enable_on_idle_line_is_refused():
    with pytest.raises(shared.SharedControlEmitError,match='selects driven'):
        FEATURE.prepare(['X16Y10_CtrlMUX00.X16Y10_TileClkEnMUX01'],{},
                        slice_lines={(16,10,15):1},ordinary_slices={(16,10,15)})

@pytest.mark.parametrize('value',['yes','2','-1'])
def test_mixed_option_is_strict(monkeypatch,value):
    monkeypatch.setenv(shared.MIXED_NATIVE_CONTROL_OPTION,value)
    with pytest.raises(shared.SharedControlEmitError,match='must be 0 or 1'):
        FEATURE.slice_lines_from_module(module())
