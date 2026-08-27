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


def _aliases(first, second):
    if os.path.normcase(os.path.realpath(os.path.abspath(first))) == \
            os.path.normcase(os.path.realpath(os.path.abspath(second))):
        return True
    try:
        return os.path.exists(first) and os.path.exists(second) and \
            os.path.samefile(first, second)
    except OSError:
        return False


def _cleanup(paths, strict=False):
    for path in set(paths):
        if not path:
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            if strict:
                raise SystemExit("cannot clear stale emission product %s: %s" %
                                 (path, exc))

def main():
    routed, out = sys.argv[1], sys.argv[2]
    comp = out + ".comp"
    comp_sidecar = os.environ.get("AGAMEMNON_POLICY_SIDECAR", comp + ".policy.json")
    final_sidecar = os.environ.get("AGAMEMNON_POLICY_SIDECAR", out + ".policy.json")
    default_sidecars = (comp + ".policy.json", out + ".policy.json")
    trace = os.environ.get("AGAMEMNON_OWNERSHIP_TRACE")
    active_products = (out, comp, comp_sidecar, trace)
    stale_products = (*active_products, final_sidecar, *default_sidecars)
    for product in stale_products:
        if product and _aliases(product, routed):
            raise SystemExit("to_bin emission product aliases routed input: %s" % product)
    distinct = [path for path in active_products if path]
    for index, first in enumerate(distinct):
        for second in distinct[index + 1:]:
            if first != second and _aliases(first, second):
                raise SystemExit("to_bin emission products alias one another")
    # A failed bitgen must never leave a stale image at the requested path.
    _cleanup(stale_products, strict=True)
    r = subprocess.run([sys.executable, "-m", "agamemnon.engine.bitgen_seq", routed, comp],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        _cleanup(stale_products)
        sys.exit(r.returncode)
    try:
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
        print("wrote %s (%d B uncompressed) + %s (%d B compressed)" %
              (out, len(full), comp, len(d)))
    except BaseException:
        _cleanup(stale_products)
        raise

if __name__ == "__main__":
    main()
