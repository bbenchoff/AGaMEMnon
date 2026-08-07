#!/usr/bin/env python3
"""routed.json -> uncompressed 99944-byte AGRV2K config image, fully open (no vendor binary).

Wraps the open back-end (bitgen_seq.py -> compressed .bin) and decompresses to the fixed
99944-byte image the FCB config engine consumes (hdr[8] + raw[99936]). This is the artifact the
SRAM silicon tests load. Compressed .bin (for flash) is left alongside as <out>.comp.

Usage: python to_bin.py <routed.json> <out_uncomp.bin>
"""
import hashlib, json, os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(HERE))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
from agamemnon.engine import lzw_codec as L

def main():
    routed, out = sys.argv[1], sys.argv[2]
    comp = out + ".comp"
    comp_sidecar = os.environ.get("AGAMEMNON_POLICY_SIDECAR", comp + ".policy.json")
    final_sidecar = os.environ.get("AGAMEMNON_POLICY_SIDECAR", out + ".policy.json")
    # A failed bitgen must never leave a stale image at the requested path.
    for path in (out, comp, comp_sidecar, final_sidecar):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    r = subprocess.run([sys.executable, "-m", "agamemnon.engine.bitgen_seq", routed, comp],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr); sys.exit(r.returncode)
    d = open(comp, "rb").read()
    full = d[:8] + L.decode(d[8:])
    assert len(full) == 99944, f"decompressed to {len(full)}B, expected 99944"
    open(out, "wb").write(full)
    if os.path.exists(comp_sidecar):
        with open(comp_sidecar, encoding="utf-8") as stream:
            policy = json.load(stream)
        policy["bindings"]["raw_output_sha256"] = hashlib.sha256(full).hexdigest()
        policy["bindings"]["raw_output_bytes"] = len(full)
        with open(final_sidecar, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(policy, stream, indent=2, sort_keys=True)
            stream.write("\n")
        if comp_sidecar != final_sidecar:
            os.remove(comp_sidecar)
        print("wrote claim-policy sidecar %s" % final_sidecar)
    print("wrote %s (%d B uncompressed) + %s (%d B compressed)" % (out, len(full), comp, len(d)))

if __name__ == "__main__":
    main()
