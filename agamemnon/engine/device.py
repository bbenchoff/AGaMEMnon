#!/usr/bin/env python3
"""device.py -- PACKAGE / DEVICE awareness for the AGRV2K open toolchain (Project AGaMEMnon).

There is one AGRV2K fabric, offered in four package variants that differ in
which perimeter IO pins are bonded out (the core LUT/FF/RMUX mesh is identical
across all four). The vendor enumerates
the legal user pins per package in framework-agrv_sdk/etc/gen_vlog as CHIP_INFO[...], and consumes
that set purely as a FRONT-END pin-legality gate (check_device() -> DeviceInfo.DEVICE_PINS ->
isDevicePin()). This module mirrors that model for the open flow.

The four CHIP_INFO pin sets below are transcribed VERBATIM from the vendor gen_vlog (regenerate with
`python device.py --regen <path-to-gen_vlog>`), so this module is self-contained (no vendor path at
runtime). PIN_n numbers are PACKAGE pin numbers, NOT subsets of one another. Each set also carries 4
dedicated clock/oscillator function pins (CLKLOCAL_RTC, PIN_HSE, PIN_HSI, PIN_OSC) which are not
general user IO; user_pins excludes them.

Front-end user-pin counts (confirmed against `gen_vlog`) are L100=79, L64=49,
L48=34, and Q32=26. The recovered L100 physical map has 78 entries because
decoded package metadata marks `PIN_73` as `NC_73`.

Package ``PIN_LIST`` records in the decoded architecture provide pin -> fabric
I/O pad coordinates for all four packages.  L48 is independently
silicon-qualified; the other three maps are structurally recovered and remain
explicitly unqualified until exercised on their corresponding hardware.
"""
import os, re, sys, csv

# ---- CHIP_INFO: legal pins per package (verbatim from vendor gen_vlog) ----
_CHIP_INFO = {}
_CHIP_INFO['AGRV2KL100'] = """
  PIN_1
  PIN_2
  PIN_3
  PIN_4
  PIN_5
  PIN_7
  PIN_15
  PIN_16
  PIN_17
  PIN_18
  PIN_25
  PIN_24
  PIN_23
  PIN_26
  PIN_29
  PIN_30
  PIN_31
  PIN_32
  PIN_33
  PIN_34
  PIN_35
  PIN_36
  PIN_37
  PIN_38
  PIN_39
  PIN_40
  PIN_41
  PIN_42
  PIN_43
  PIN_44
  PIN_45
  PIN_46
  PIN_47
  PIN_48
  PIN_51
  PIN_52
  PIN_53
  PIN_54
  PIN_55
  PIN_56
  PIN_57
  PIN_58
  PIN_59
  PIN_60
  PIN_61
  PIN_62
  PIN_63
  PIN_64
  PIN_65
  PIN_66
  PIN_67
  PIN_68
  PIN_69
  PIN_70
  PIN_71
  PIN_72
  PIN_73
  PIN_76
  PIN_77
  PIN_78
  PIN_79
  PIN_80
  PIN_81
  PIN_82
  PIN_83
  PIN_84
  PIN_85
  PIN_86
  PIN_87
  PIN_88
  PIN_89
  PIN_90
  PIN_91
  PIN_92
  PIN_93
  PIN_95
  PIN_96
  PIN_97
  PIN_98
  CLKLOCAL_RTC
  PIN_HSE
  PIN_HSI
  PIN_OSC
"""

_CHIP_INFO['AGRV2KL64'] = """
  PIN_2
  PIN_8
  PIN_9
  PIN_10
  PIN_11
  PIN_14
  PIN_15
  PIN_16
  PIN_17
  PIN_20
  PIN_21
  PIN_22
  PIN_23
  PIN_24
  PIN_25
  PIN_26
  PIN_27
  PIN_28
  PIN_29
  PIN_30
  PIN_31
  PIN_33
  PIN_34
  PIN_35
  PIN_36
  PIN_37
  PIN_38
  PIN_39
  PIN_40
  PIN_41
  PIN_42
  PIN_43
  PIN_44
  PIN_45
  PIN_46
  PIN_47
  PIN_49
  PIN_50
  PIN_51
  PIN_52
  PIN_53
  PIN_54
  PIN_55
  PIN_56
  PIN_57
  PIN_58
  PIN_59
  PIN_61
  PIN_62
  CLKLOCAL_RTC
  PIN_HSE
  PIN_HSI
  PIN_OSC
"""

_CHIP_INFO['AGRV2KL48'] = """
  PIN_2
  PIN_10
  PIN_11
  PIN_12
  PIN_13
  PIN_14
  PIN_15
  PIN_16
  PIN_17
  PIN_18
  PIN_19
  PIN_20
  PIN_21
  PIN_22
  PIN_25
  PIN_26
  PIN_27
  PIN_28
  PIN_29
  PIN_30
  PIN_31
  PIN_32
  PIN_33
  PIN_34
  PIN_35
  PIN_37
  PIN_38
  PIN_39
  PIN_40
  PIN_41
  PIN_42
  PIN_43
  PIN_45
  PIN_46
  CLKLOCAL_RTC
  PIN_HSE
  PIN_HSI
  PIN_OSC
"""

_CHIP_INFO['AGRV2KQ32'] = """
  PIN_1
  PIN_2
  PIN_3
  PIN_5
  PIN_7
  PIN_8
  PIN_9
  PIN_10
  PIN_11
  PIN_12
  PIN_13
  PIN_14
  PIN_15
  PIN_18
  PIN_19
  PIN_20
  PIN_21
  PIN_22
  PIN_23
  PIN_24
  PIN_25
  PIN_26
  PIN_27
  PIN_28
  PIN_29
  PIN_31
  CLKLOCAL_RTC
  PIN_HSE
  PIN_HSI
  PIN_OSC
"""

# Dedicated clock / oscillator function pins present in every package set; NOT general user IO.
FUNC_PINS = frozenset(["CLKLOCAL_RTC", "PIN_HSE", "PIN_HSI", "PIN_OSC"])

# Package pin counts (the number in the part name).
_PKG_PIN_COUNT = {"AGRV2KL100": 100, "AGRV2KL64": 64, "AGRV2KL48": 48, "AGRV2KQ32": 32}

PACKAGES = ["AGRV2KL100", "AGRV2KL64", "AGRV2KL48", "AGRV2KQ32"]

# The dev board is the 48-pin part; the ThinkinMachine node will be the 32-pin part.
DEFAULT_DEVICE = "AGRV2KL48"

# L48 was independently recovered and exercised with the Pico GPIO rig.  The
# remaining package maps are decoded from alta-agr.ar and carry a distinct
# qualification state in bondmaps.json.
_DATA = os.environ.get("AGAMEMNON_DATA", os.path.join(os.path.dirname(__file__), "..", "chipdb"))
BOND_MAP_FILES = {
    "AGRV2KL100": "bondmap_L100.csv",
    "AGRV2KL64": "bondmap_L64.csv",
    "AGRV2KL48": "bondmap_L48.csv",
    "AGRV2KQ32": "bondmap_Q32.csv",
}
BOND_MAP_QUALIFICATION = {
    "AGRV2KL100": "recovered-unqualified",
    "AGRV2KL64": "recovered-unqualified",
    "AGRV2KL48": "silicon-qualified",
    "AGRV2KQ32": "recovered-unqualified",
}


def _load_bond_map(name):
    result = {}
    path = os.path.join(_DATA, BOND_MAP_FILES[name])
    if os.path.exists(path):
        with open(path, newline="") as stream:
            for row in csv.DictReader(stream):
                result[row["pin"]] = (
                    int(row["x"]), int(row["y"]), int(row["z"]), row["edge"]
                )
    return result


BOND_MAPS = {name: _load_bond_map(name) for name in PACKAGES}
# Backward-compatible default-package aliases.  New code should use
# ``Device.bond_map`` so AGAMEMNON_DEVICE is respected.
PIN_TO_PAD = BOND_MAPS[DEFAULT_DEVICE]
MISSING_BOND_MAP = not bool(PIN_TO_PAD)


class Device:
    """One AGRV2K package: name (-type), package pin count, bonded pin set."""
    def __init__(self, name):
        if name not in _CHIP_INFO:
            raise KeyError("Unknown device %r (known: %s)" % (name, ", ".join(PACKAGES)))
        self.name = name
        self.package_pin_count = _PKG_PIN_COUNT[name]
        pins = set(p.strip() for p in _CHIP_INFO[name].split() if p.strip())
        self.pins = frozenset(pins)                       # all legal pins (user + func)
        self.func_pins = frozenset(pins & FUNC_PINS)      # dedicated clock/osc pins
        self.user_pins = frozenset(pins - FUNC_PINS)      # general user IO pins
        self.user_pin_count = len(self.user_pins)
        self.bond_map = BOND_MAPS[name]
        self.bond_map_qualification = BOND_MAP_QUALIFICATION[name]
        self.bond_map_qualified = self.bond_map_qualification == "silicon-qualified"

    def pin_to_pad(self, pin):
        """Return the recovered ``PIN_n`` -> IOTILE ``(x,y,z,edge)`` entry."""
        return self.bond_map.get(pin)

    def __repr__(self):
        return ("Device(%s, %d-pin, %d user IO, %d func pins)"
                % (self.name, self.package_pin_count, self.user_pin_count, len(self.func_pins)))


_CACHE = {}
def get_device(name=None):
    """Return the Device for `name` (or DEFAULT_DEVICE)."""
    name = name or DEFAULT_DEVICE
    if name not in _CACHE:
        _CACHE[name] = Device(name)
    return _CACHE[name]


def device_from_env():
    """Return the Device selected by env AGAMEMNON_DEVICE (default DEFAULT_DEVICE)."""
    return get_device(os.environ.get("AGAMEMNON_DEVICE", DEFAULT_DEVICE))


def check_pin(device, pin, include_func=True):
    """Front-end legality gate (mirrors the vendor's DeviceInfo.isDevicePin).

    True iff `pin` is bonded on `device`. Accepts a Device or a device-name string.
    include_func=False restricts to general user IO (excludes clock/osc func pins)."""
    if isinstance(device, str):
        device = get_device(device)
    legal = device.pins if include_func else device.user_pins
    return pin in legal


def check_design_pins(device, pins, on_error="warn"):
    """Gate a design's declared IO pins against the selected package. Returns the illegal pins.

    on_error: 'warn' (print to stderr, continue), 'error' (raise ValueError), or 'silent'."""
    if isinstance(device, str):
        device = get_device(device)
    bad = [p for p in pins if not check_pin(device, p)]
    if bad:
        msg = ("device %s: %d design pin(s) NOT bonded on this package: %s"
               % (device.name, len(bad), ", ".join(sorted(bad))))
        if on_error == "error":
            raise ValueError(msg)
        elif on_error == "warn":
            print("WARN: " + msg, file=sys.stderr)
    return bad


def _regen(gen_vlog_path):
    """Re-transcribe _CHIP_INFO from a vendor gen_vlog and rewrite this file's block. Dev helper."""
    src = open(gen_vlog_path).read()
    q = chr(34) * 3
    out = {}
    for dev in PACKAGES:
        m = re.search(r"CHIP_INFO\['" + dev + r"'\] = set\(pin.strip\(\) for pin in " + q + r"(.*?)" + q, src, re.S)
        out[dev] = [p.strip() for p in m.group(1).split() if p.strip()]
    for dev in PACKAGES:
        print(dev, len(out[dev]), "pins")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AGRV2K device/package info (mirrors gen_vlog).")
    ap.add_argument("-d", "--device", default=os.environ.get("AGAMEMNON_DEVICE", DEFAULT_DEVICE))
    ap.add_argument("-l", "--list", action="store_true", help="List supported packages")
    ap.add_argument("-p", "--pins", action="store_true", help="List device user pins")
    ap.add_argument("--check", nargs="+", metavar="PIN", help="Check pin legality on -d device")
    ap.add_argument("--regen", metavar="GEN_VLOG", help="Re-transcribe CHIP_INFO from a gen_vlog")
    a = ap.parse_args()
    if a.regen:
        _regen(a.regen); sys.exit(0)
    if a.list:
        for d in PACKAGES:
            dev = get_device(d)
            print("  %-12s %3d-pin  %2d user IO  %d func" % (dev.name, dev.package_pin_count,
                                                             dev.user_pin_count, len(dev.func_pins)))
        sys.exit(0)
    dev = get_device(a.device)
    if a.check:
        for p in a.check:
            print("%-14s %s" % (p, "OK (bonded)" if check_pin(dev, p) else "ILLEGAL (not bonded)"))
        sys.exit(0)
    print(dev)
    if a.pins:
        def _k(p):
            m = re.match(r"PIN_(\d+)$", p); return (0, int(m.group(1))) if m else (1, p)
        print("  user IO :", ", ".join(sorted(dev.user_pins, key=_k)))
        print("  func    :", ", ".join(sorted(dev.func_pins)))
