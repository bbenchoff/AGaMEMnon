def gp(cell,key):
    try: return cell.params[key]
    except Exception:
        try:
            for k in cell.params:
                if str(k)==key: return cell.params[k]
        except Exception: pass
    return None
nslice=nio=0; placements=[]
for cn,cell in ctx.cells:
    t=str(cell.type)
    if t=="GENERIC_SLICE":
        nslice+=1
        loc=ctx.getBelLocation(cell.bel)
        placements.append((cn, loc.x, loc.y, loc.z, str(gp(cell,"INIT"))))
    elif t=="GENERIC_IOB": nio+=1
print("PLACED: %d slices, %d IOBs" % (nslice,nio))
for cn,x,y,z,init in placements[:8]:
    print("  SLICE @ X%dY%dZ%d  INIT=%s  (%s)" % (x,y,z,init,cn))
used=0
for nn,net in ctx.nets:
    try:
        for w in net.wires:
            pm=net.wires[w]
            if str(pm.pip): used+=1
    except Exception: pass
print("USED PIPS (routing config to emit): %d" % used)
