#!/usr/bin/env python3
"""Project Agamemnon — decode af.exe's alta_db/*.tx intermediates (route/place/pack).

They are obfuscated with the SAME cc::AsciiEncrypt codec as the arch DB (recovered in Step 1),
so codec_validate.decode (MODE 8) turns them into readable text: route.tx = the routing graph
(nets -> paths of named routing nodes per tile), place.tx = placement, pack.tx = packing.
This gives the routing-graph data nextpnr-agrv needs -- no working dump_route_table required.
"""
import os, sys
from agamemnon.engine import codec_validate as C

def decode_tx(path):
    return C.decode(open(path, "rb").read(), C.build_banks())

if __name__ == "__main__":
    # self-test only: decode a vendor .tx you supply. Pass the path as argv[1], or set
    # $AGAMEMNON_ROUTE_TX; the trailing relative path is just a dev fallback (not shipped).
    p = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AGAMEMNON_ROUTE_TX")) or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "lab", "reload", "alta_db", "route.tx")
    out = decode_tx(p)
    if len(sys.argv) > 2:
        open(sys.argv[2], "wb").write(out); print(f"wrote {len(out)}B -> {sys.argv[2]}")
    else:
        sys.stdout.buffer.write(out[:2000])
