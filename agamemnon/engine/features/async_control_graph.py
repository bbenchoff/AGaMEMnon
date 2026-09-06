"""Explicit asynchronous controller primitives and their routed terminals.

The graph does not admit active controls in packing or bitstream generation.
Controller Din and Dout remain separate nets; no pip crosses the primitive.
"""
import json

from .ctrlmux_encoding import ctrlmux_source_bits


def add_async_control_architecture(context):
    ctx, Loc = context.ctx, context.loc
    shared = context.shared
    wires, W = shared['wires'], shared['wire_name']
    slices = shared['slice_bels']
    anchors = json.loads((context.chipdb_root / 'logictile_asyncmux3.json').read_text())
    tiles = {tile for tile in slices if '%d,%d' % tile in anchors}
    counts = dict(controllers=0,inputs=0,selections=0,leaves=0,reset_pins=0)
    # Provisional routing costs, not characterized asynchronous timing limits.
    delay = ctx.getDelayFromNS(0.3)

    def wire(x, y, resource):
        name = W(x, y, resource)
        if name not in wires:
            ctx.addWire(name=name, type=resource.rstrip('0123456789'), x=x, y=y)
            wires.add(name)
        return name

    def pip(source, destination, kind, x, y):
        ctx.addPip(name=source+'.'+destination, type=kind,
                   srcWire=source, dstWire=destination, delay=delay, loc=Loc(x,y,0))

    for x,y in sorted(tiles):
        for z,bel in sorted(slices[x,y].items()):
            reset=wire(x,y,'AsyncMUX%02d'%z)
            ctx.addBelInput(bel=bel,name='ARST',wire=reset)
            counts['reset_pins']+=1
        for controller in range(2):
            incoming=wire(x,y,'TileAsyncMUX%02d'%controller)
            outgoing=wire(x,y,'alta_asyncctrl%02d'%controller)
            bel=W(x,y,'ASYNCCTRL%d'%controller)
            ctx.addBel(name=bel,type='AGRV2K_ASYNCCTRL',loc=Loc(x,y,16+controller),
                       gb=False,hidden=False)
            ctx.addBelInput(bel=bel,name='DIN',wire=incoming)
            ctx.addBelOutput(bel=bel,name='DOUT',wire=outgoing)
            counts['controllers']+=1
            for mux in (2*controller,2*controller+1):
                selected=wire(x,y,'CtrlMUX%02d'%mux)
                pip(selected,incoming,'ASYNC_CONTROL_SELECT',x,y)
                counts['selections']+=1
            for z in sorted(slices[x,y]):
                pip(outgoing,W(x,y,'AsyncMUX%02d'%z),'ASYNC_CONTROL_LEAF',x,y)
                counts['leaves']+=1
        for mux in range(4):
            destination=W(x,y,'CtrlMUX%02d'%mux)
            for dx in (0,1):
                if (x+dx,y) not in tiles:
                    continue
                for index in range(96):
                    try:
                        ctrlmux_source_bits(mux,index,dx)
                    except ValueError:
                        continue
                    source=W(x+dx,y,'RMUX%02d'%index)
                    if source not in wires:
                        continue
                    pip(source,destination,'ASYNC_CONTROL_INPUT',x,y)
                    counts['inputs']+=1
    shared['async_control_graph']=counts
    print('AGRV2K arch: asynchronous controller graph %s (admission unchanged)'%counts)
    return counts
