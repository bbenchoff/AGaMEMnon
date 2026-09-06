from pathlib import Path
from types import SimpleNamespace

from agamemnon.engine.features.async_control_graph import add_async_control_architecture


class Graph:
    def __init__(self):
        self.wires=set();self.pips={};self.bels={};self.inputs={};self.outputs={}
    def addWire(self, **row):
        assert row['name'] not in self.wires
        self.wires.add(row['name'])
    def addBel(self, **row):
        assert row['name'] not in self.bels
        self.bels[row['name']]=row
    def addBelInput(self, **row):
        assert row['wire'] in self.wires
        self.inputs[row['bel'],row['name']]=row['wire']
    def addBelOutput(self, **row):
        assert row['wire'] in self.wires
        self.outputs[row['bel'],row['name']]=row['wire']
    def addPip(self, **row):
        assert row['name'] not in self.pips
        assert row['srcWire'] in self.wires and row['dstWire'] in self.wires
        self.pips[row['name']]=row
    def getDelayFromNS(self, value):return value


def test_two_tile_graph_has_separate_primitive_nets_and_local_reset_sinks():
    ctx=Graph();W=lambda x,y,r:'X%dY%d_%s'%(x,y,r)
    tiles={(14,10):{z:W(14,10,'SLICE%d'%z) for z in range(16)},
           (15,10):{z:W(15,10,'SLICE%d'%z) for z in range(16)}}
    for x,y in tiles:
        for i in range(96):ctx.addWire(name=W(x,y,'RMUX%02d'%i))
    context=SimpleNamespace(ctx=ctx,loc=lambda x,y,z:(x,y,z),
        chipdb_root=Path(__file__).resolve().parents[1]/'agamemnon/chipdb',
        shared=dict(wires=set(ctx.wires),wire_name=W,slice_bels=tiles))
    counts=add_async_control_architecture(context)
    assert counts==dict(controllers=4,inputs=160,selections=8,leaves=64,reset_pins=32)
    edges={}
    for pip in ctx.pips.values():edges.setdefault(pip['srcWire'],set()).add(pip['dstWire'])
    for x,y in tiles:
        for controller in range(2):
            bel=W(x,y,'ASYNCCTRL%d'%controller)
            incoming=ctx.inputs[bel,'DIN'];outgoing=ctx.outputs[bel,'DOUT']
            assert incoming!=outgoing and incoming not in edges
            assert edges[outgoing]=={ctx.inputs[tiles[x,y][z],'ARST'] for z in range(16)}
        for z in range(16):assert ctx.inputs[tiles[x,y][z],'ARST'] not in edges
    assert all(p['srcWire'] in ctx.wires for p in ctx.pips.values())
    assert not any(p['srcWire'].startswith('X16Y10_') for p in ctx.pips.values())
