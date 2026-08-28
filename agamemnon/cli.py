#!/usr/bin/env python3
"""AGaMEMnon: open synthesis, place-and-route, bitstream, and programming for AG32 / AGRV2K.

The release fabric path uses Yosys, nextpnr with the `agrv2k` backend, and strict AGaMEMnon bitgen.
Bitstream conversion, named `.agasc` editing, and main-flash controller operations are also open.
Hardware access requires a CMSIS-DAP probe and an OpenOCD binary with AGM's `riscv -dap` target
extension; see docs/PROGRAMMING.md.

  SDK workflow:
    agamemnon doctor
    agamemnon new hello --board ag32vf303-l48 --template mcu-blink
    agamemnon build                         # inside the generated project
    agamemnon run --transport dap           # volatile SRAM run

  FPGA fabric:
    agamemnon build foo.v -o foo.bin         # Verilog -> synth -> place&route -> .bin (open flow)
    agamemnon build foo.v -o foo.bin --uarch --verify   # agrv2k uarch flow + offline behavioural check
    agamemnon verify foo_routed.json         # cycle-sim a routed design: the AHB read-values it produces
    agamemnon pack foo_routed.json foo.bin   # routed nextpnr JSON -> .bin  (icepack)
    agamemnon status-overlay app_routed.json app_public32.json  # bind scalar status_set to W1C
    agamemnon unpack foo.bin -o raw.img      # .bin -> 99936-byte raw image (iceunpack)
    agamemnon decode fabric.bin -o raw.img   # .bin -> 99936-byte raw config image
    agamemnon encode raw.img   -o fabric.bin # raw image -> compressed .bin
    agamemnon to-agasc fabric.bin -o fabric.agasc    # .bin -> named per-tile ASCII
    agamemnon from-agasc fabric.agasc -o fabric.bin  # edited ASCII -> CRC-correct .bin
    agamemnon edit-lut in.bin --le 17,4,1 --init 0x96e9 -o out.bin
  chip (SWD via a CMSIS-DAP probe + an OpenOCD built with `riscv -dap`):
    agamemnon probe                          # read DEVICE_ID over SWD (expect 0x40200001)
    agamemnon sram fw.bin -b fabric.bin      # SRAM-inject a bitstream + firmware and run it (volatile)
    agamemnon backup full.bin                # dump the whole 256 KB flash
    agamemnon flash foo.bin --addr 0x80008100 --backup full.bin   # open flasher: erase+program+verify
    agamemnon image -b fabric.bin -m fw.bin --flash --backup f.bin  # assemble+flash a boot image
  chip (UART0 mask ROM via the Raspberry Pi Pico 2 bridge):
    agamemnon uart-probe --port COM6
    agamemnon uart-backup full.bin --port COM6
    agamemnon uart-flash fw.bin --addr 0x80000000 --backup full.bin --port COM6
  chip (flash-resident USB CDC uploader):
    agamemnon probe --transport usb
    agamemnon backup full.bin --transport usb
    agamemnon flash app.bin --addr 0x80010000 --backup full.bin --transport usb
    agamemnon go 0x80010000 --transport usb
"""
import os, sys, argparse, subprocess, tempfile, json, hashlib, shutil, time, re, csv

from .tool_shim import stage_windows_directory, stage_windows_executable

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine")        # the self-contained engine (single source of truth)
CHIPDB = os.path.join(HERE, "chipdb")        # the shipped device database
SYNTH = os.path.join(HERE, "synth")          # yosys synth scripts (prims/cells_map + tcl)
from .engine import lzw_codec as L             # noqa: E402
from .engine import physmap                     # noqa: E402
from .engine import pll_emit as PLL             # noqa: E402
from . import __version__                      # noqa: E402
from . import program as P                     # noqa: E402  (the SWD programmer / open flasher)
from . import fcb_restream as FCBR              # noqa: E402  (desk-first SRAM restream protocol)
from . import hil_campaign as HILC               # noqa: E402  (hash-bound HIL work lists)
from . import uart_program as U                # noqa: E402  (Pico + mask-ROM UART programmer)
from . import usb_program as USB               # noqa: E402  (flash-resident USB CDC uploader)
from . import diagnostics as D                 # noqa: E402


def _paths_alias(first, second):
    if os.path.normcase(os.path.realpath(os.path.abspath(first))) == \
            os.path.normcase(os.path.realpath(os.path.abspath(second))):
        return True
    try:
        return os.path.exists(first) and os.path.exists(second) and \
            os.path.samefile(first, second)
    except OSError:
        return False


def _validate_emission_product_paths(inputs, products):
    """Reject product/input and cross-product aliases before deleting anything.

    ``products`` rows are ``(role, path, alias_group)``.  Paths in one explicit
    non-empty alias group are equivalent stale names for the same logical
    product (for example the selected/default policy sidecar); all other
    product identities must remain distinct.
    """
    inputs = [(role, path) for role, path in inputs if path]
    products = [(role, path, group) for role, path, group in products if path]
    for role, path, _group in products:
        for input_role, input_path in inputs:
            if _paths_alias(path, input_path):
                raise ValueError("%s aliases %s: %s" % (role, input_role, path))
    for index, (first_role, first_path, first_group) in enumerate(products):
        for second_role, second_path, second_group in products[index + 1:]:
            if not _paths_alias(first_path, second_path):
                continue
            if first_group and first_group == second_group:
                continue
            raise ValueError("%s aliases %s: %s" %
                             (first_role, second_role, first_path))


def _remove_emission_products(products):
    for _role, path, _group in products:
        if not path:
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ValueError("cannot clear stale emission product %s: %s" %
                             (path, exc)) from exc
from . import project as PJ                    # noqa: E402
from . import tool_install as TI               # noqa: E402
from . import qualification_report as Q         # noqa: E402
from .engine.registry import OPTIONS as ENGINE_OPTIONS  # noqa: E402
from .engine.registry import manifest as engine_manifest  # noqa: E402
from .engine.registry import options_from as engine_options_from  # noqa: E402
from .engine.claim_policy import ClaimPolicyError, evaluate_policy  # noqa: E402
from .engine import qualified_bram_tmux9 as QBW                 # noqa: E402
from .engine import device as _device                          # noqa: E402
from .engine import family as _family                           # noqa: E402
from .engine import router2_diagnostics as _router2_diag        # noqa: E402
from .engine import router2_probe as _router2_probe             # noqa: E402
from .engine import attempt_ladder as _attempt_ladder            # noqa: E402
from .engine import routing_tiers                            # noqa: E402

RAW_LEN = 99936
HDR = bytes.fromhex("40200001") + bytes.fromhex("0000ffff")   # DEVICE_ID | max_index
DEFAULT_FABRIC_FREQUENCY_MHZ = int(ENGINE_OPTIONS["AGAMEMNON_SYSCLK"].default)
QUALIFICATION = os.path.abspath(os.path.join(HERE, os.pardir, "qualification"))


def _write_portable_routed_json(source, destination, document=None):
    """Write a deterministic routed checkpoint without workstation paths."""
    design = (json.loads(open(source, encoding="utf-8").read())
              if document is None else document)
    package = HERE.replace("\\", "/").rstrip("/")
    working = os.getcwd().replace("\\", "/").rstrip("/")

    def clean(value):
        if isinstance(value, str):
            value = value.replace("\\", "/")
            value = value.replace(package + "/", "agamemnon/")
            value = value.replace(working + "/", "")
            return value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    with open(destination, "w", encoding="utf-8", newline="\n") as output:
        json.dump(clean(design), output, indent=2)
        output.write("\n")


def _stage_validated_routed_json(snapshot, directory, name="validated-routed.json"):
    """Create one private byte-exact child input without reopening its source."""
    destination = os.path.join(directory, name)
    with open(destination, "xb") as output:
        output.write(snapshot.raw)
        output.flush()
        os.fsync(output.fileno())
    return destination


def _write_validated_routed_copy(snapshot, destination):
    """Publish exactly the validated bytes without consulting the source path."""
    with open(destination, "wb") as output:
        output.write(snapshot.raw)


def _pin_uarch_single_slice(path, bel):
    """Apply ``--pin`` to the one user slice before the C++ uarch packer."""
    if re.fullmatch(r"X\d+Y\d+_SLICE\d+", bel) is None:
        raise ValueError("--pin must be X<n>Y<n>_SLICE<n>, got %s" % bel)
    with open(path, encoding="utf-8") as stream:
        document = json.load(stream)
    candidates = []
    for module in document.get("modules", {}).values():
        for name, cell in module.get("cells", {}).items():
            if cell.get("type") in ("LUT", "GENERIC_SLICE") and "PACKER_GND" not in name:
                candidates.append((name, cell))
    if len(candidates) != 1:
        raise ValueError(
            "--pin requires exactly one non-ground LUT/slice before uarch packing; found %d"
            % len(candidates)
        )
    name, cell = candidates[0]
    attributes = cell.setdefault("attributes", {})
    prior = attributes.get("BEL")
    if prior and prior != bel:
        raise ValueError("--pin %s conflicts with existing %s placement %s" % (bel, name, prior))
    attributes["BEL"] = bel
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream)
    return name

# Exact replay is a qualification registry, not arbitrary routed-JSON input.
# Each profile binds the only accepted source/checkpoint pair to the only image
# hashes the CLI may release.  Additions require source, route, pack and silicon
# review; a caller-provided path with merely similar structure is rejected.
QUALIFIED_ROUTE_PROFILES = {
    "mcu-ahb-bank16-read-word0": {
        "source": "mcu_ahb_register_bank16_read_word0_structural.v",
        "source_sha256": "5abe28ddc4231905b445bd8faefd85765f12fa652f554f0ed7e4e97db36cabee",
        "checkpoint": "mcu_ahb_register_bank16_read_word0_gated_routed.json",
        "checkpoint_sha256": "1daa7de2d8a5297182b35c21d745900e93bb540bd4ca3320449108dccd3fbef2",
        "bitstream_sha256": "301edbab67a42edcfb958d4dda7f3ffba786d425123a7c27826fccfba6765160",
        "compressed_sha256": "5b90b852722c2e78b1d417ca804b42cbadd13e303aa75914f9a51358232f9bae",
        "hse": 8,
        "sysclk": 10,
    },
    "mcu-ahb-bank16-public-scratch4": {
        "source": "mcu_ahb_register_bank16_public_scratch4_structural.v",
        "source_sha256": "703a3bf07e9f8162800b27349597bf48bd1b2646ca58861cf03f1770e7ef93ee",
        "checkpoint": "mcu_ahb_register_bank16_public_scratch4_routed.json",
        "checkpoint_sha256": "97f164a72b22ea2f076f889ee771b577f482384469266dc489e0b2f243590610",
        "bitstream_sha256": "2aa4d1d65c57c1ae28612f5743b08a7683179786e2d467c20166add1fba60882",
        "compressed_sha256": "dd20ea9549bf0d5f0c4dc09988a2696aeab57cb4f299ac12c136e4842e04e516",
        "hse": 8,
        "sysclk": 10,
    },
    # Individually qualified x18, fixed-address same-Port-A BRAM matrix. These
    # four profiles are intentionally separate and hash-bound: they establish
    # only the measured low-holds-INIT / TMUX09-high-reaches-DataIn result in
    # both polarities, not arbitrary inferred writes or general TMUX routing.
    "bram-tmux9-i0-d1-we0": {
        "pack_only": True,
        "package_root": "sdk/qualified_bram_tmux9",
        "source": "bram_tmux9_i0_d1_we0.v",
        "source_sha256": "bee9870469f1fbdb3f59743e6c17092f357ace605a6959bb873521f8bcdf5b13",
        "checkpoint": "bram_tmux9_i0_d1_we0_routed.json",
        "checkpoint_sha256": "8fbcb35c76d2d1a97b6d00b7b59bc9c2e9f50f6a76fa12228e25ad4f45444449",
        "bitstream_sha256": "33282bc95813a9bf7c31e7a30a85a7705e89adec38edd356e2f06e8a9afcd759",
        "compressed_sha256": "925332c9c8cfe6ba73c7eee9b9cd3b9cbb79f29efbbde4f45d3dc46519bc706d",
        "hse": 8,
        "sysclk": 10,
    },
    "bram-tmux9-i0-d1-we1": {
        "pack_only": True,
        "package_root": "sdk/qualified_bram_tmux9",
        "source": "bram_tmux9_i0_d1_we1.v",
        "source_sha256": "fc7e866359ed86ae6f9d8c799d37a3b7a9c4cb649d5bd1ca8e729486ab93cc65",
        "checkpoint": "bram_tmux9_i0_d1_we1_routed.json",
        "checkpoint_sha256": "66f67c03d71b512c7ccdf2ee5b73e7cbac3ee10d7ba253d4c40d585fd3c3865a",
        "bitstream_sha256": "3bd2c82a2a18e2c66721de5687c940e915bc7a933f5ea88dbca45394901782df",
        "compressed_sha256": "221cdf15ccd9ef4d2220181861e724136a69387bb3647c4db550c1891a421ce5",
        "hse": 8,
        "sysclk": 10,
    },
    "bram-tmux9-i1-d0-we0": {
        "pack_only": True,
        "package_root": "sdk/qualified_bram_tmux9",
        "source": "bram_tmux9_i1_d0_we0.v",
        "source_sha256": "49e55b6d9f48ec6c6afaa5b3bfbe4504107cac7b35f979e7ddef873a0228381b",
        "source_build": "bram_tmux9_i1_d0_we0_source.v",
        "source_build_sha256": "16afd9adee4016d47595a5b85cad94aaa6a9fbbd5c5ee8d3f3c273c37f379b64",
        "checkpoint": "bram_tmux9_i1_d0_we0_routed.json",
        "checkpoint_sha256": "69911e8674b97ca359685730e9eee3e22abeb5f787be8e829ffea042f5194854",
        "bitstream_sha256": "8ca212a39317b24148a63873d408f194cc4ae64ed2c9b0919e3fd30da54aac54",
        "compressed_sha256": "65b3f6e7e77a315ccc12016579797dc3a0a10525c7c73430ac4aca1e3c91bbc0",
        "hse": 8,
        "sysclk": 10,
    },
    "bram-tmux9-i1-d0-we1": {
        "pack_only": True,
        "package_root": "sdk/qualified_bram_tmux9",
        "source": "bram_tmux9_i1_d0_we1.v",
        "source_sha256": "4448254e09bdf280ecf1f557860b6284e269d8e9caf399cfa52ef63570c9fc6f",
        "source_build": "bram_tmux9_i1_d0_we1_source.v",
        "source_build_sha256": "7420293a0b11cd0e9f54a5d41a79e96d9ed93ee698c372ce4c5063d1a83d7010",
        "checkpoint": "bram_tmux9_i1_d0_we1_routed.json",
        "checkpoint_sha256": "e9b6d3a4acec861c28fa87eec32b2ff54b67b53362c8e5f65140f76f9657b89b",
        "bitstream_sha256": "3b8892052a726d0bbe93298ce70f0eb4149134620f4551b606ef0be24522b8ea",
        "compressed_sha256": "56ffb26756a02d9042e99485e1e28b212fcceb004487782c01cb279804918f19",
        "hse": 8,
        "sysclk": 10,
    },
}


def _sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _qualified_profile_root(profile):
    """Resolve checkout evidence or an artifact intentionally shipped in-package."""
    relative = profile.get("package_root")
    return os.path.join(HERE, *relative.split("/")) if relative else QUALIFICATION


def _qualified_route_profile(a, sources, engine, data, env, freq):
    """Resolve and validate the closed exact-route profile selected by name."""
    profile = QUALIFIED_ROUTE_PROFILES.get(a.qualified_checkpoint)
    if profile is None:
        raise ValueError(
            "unknown qualified route profile %r (choose %s)" %
            (a.qualified_checkpoint, ", ".join(sorted(QUALIFIED_ROUTE_PROFILES)))
        )
    if profile.get("pack_only"):
        raise ValueError(
            "qualified route profile %s is retained-checkpoint pack-only; use "
            "`agamemnon pack <packaged checkpoint> <output> --qualified-checkpoint %s`"
            % (a.qualified_checkpoint, a.qualified_checkpoint)
        )
    root = _qualified_profile_root(profile)
    expected_source = os.path.join(root, profile["source"])
    checkpoint = os.path.join(root, profile["checkpoint"])
    if len(sources) != 1 or os.path.normcase(os.path.realpath(sources[0])) != \
            os.path.normcase(os.path.realpath(expected_source)):
        raise ValueError("qualified route profile %s requires exact source %s" %
                         (a.qualified_checkpoint, expected_source))
    for path, expected, label in (
        (expected_source, profile["source_sha256"], "source"),
        (checkpoint, profile["checkpoint_sha256"], "checkpoint"),
    ):
        if _sha256_file(path) != expected:
            raise ValueError("qualified route profile %s %s hash drifted" %
                             (a.qualified_checkpoint, label))
    if os.path.normcase(os.path.realpath(engine)) != \
            os.path.normcase(os.path.realpath(ENGINE)):
        raise ValueError("qualified route replay forbids AGAMEMNON_ENGINE overrides")
    if os.path.normcase(os.path.realpath(data)) != \
            os.path.normcase(os.path.realpath(CHIPDB)):
        raise ValueError("qualified route replay forbids AGAMEMNON_DATA overrides")
    allowed_ambient = {"AGAMEMNON_OSS", "AGAMEMNON_HSE", "AGAMEMNON_SYSCLK"}
    forbidden = sorted(name for name in os.environ
                       if name.startswith("AGAMEMNON_") and
                       name not in allowed_ambient)
    if forbidden:
        raise ValueError("qualified route replay forbids ambient option(s): %s" %
                         ", ".join(forbidden))
    if int(env.get("AGAMEMNON_HSE", "8")) != profile["hse"] or \
            int(freq) != profile["sysclk"]:
        raise ValueError("qualified route profile %s requires HSE=%d SYSCLK=%d" %
                         (a.qualified_checkpoint, profile["hse"],
                          profile["sysclk"]))
    incompatible = [
        name for name in ("leds", "mcu", "true_topo", "no_intra_rmux",
                          "pin", "pin_hook", "baseline", "pcf", "hard_carry")
        if getattr(a, name, None)
    ]
    if incompatible:
        raise ValueError("qualified route replay forbids build option(s): %s" %
                         ", ".join("--" + name.replace("_", "-")
                                   for name in incompatible))
    result = dict(profile)
    result["id"] = a.qualified_checkpoint
    result["checkpoint_path"] = checkpoint
    return result


def _qualified_bram_source_profile(a, sources, engine, data, env, freq):
    """Validate a fresh source-to-route build of the bounded TMUX09 design."""
    profile_id = a.qualified_bram_write
    profile = QUALIFIED_ROUTE_PROFILES.get(profile_id)
    if profile_id not in QBW.PROFILES or profile is None:
        raise ValueError(
            "unknown qualified BRAM source profile %r (choose %s)" %
            (profile_id, ", ".join(sorted(QBW.PROFILES)))
        )
    source_sha256 = profile.get("source_build_sha256", profile["source_sha256"])
    if len(sources) != 1 or _sha256_file(sources[0]) != source_sha256:
        raise ValueError(
            "qualified BRAM source profile %s requires source SHA-256 %s" %
            (profile_id, source_sha256)
        )
    if os.path.normcase(os.path.realpath(engine)) != \
            os.path.normcase(os.path.realpath(ENGINE)):
        raise ValueError("qualified BRAM source build forbids AGAMEMNON_ENGINE overrides")
    if os.path.normcase(os.path.realpath(data)) != \
            os.path.normcase(os.path.realpath(CHIPDB)):
        raise ValueError("qualified BRAM source build forbids AGAMEMNON_DATA overrides")
    allowed_ambient = {
        "AGAMEMNON_OSS", "AGAMEMNON_HSE", "AGAMEMNON_SYSCLK",
        "AGAMEMNON_UARCH_NEXTPNR", "AGAMEMNON_UARCH_NEXTPNR_RUNTIME",
    }
    forbidden = sorted(name for name in os.environ
                       if name.startswith("AGAMEMNON_") and name not in allowed_ambient)
    if forbidden:
        raise ValueError("qualified BRAM source build forbids ambient option(s): %s" %
                         ", ".join(forbidden))
    if int(env.get("AGAMEMNON_HSE", "8")) != profile["hse"] or \
            int(freq) != profile["sysclk"]:
        raise ValueError("qualified BRAM source profile %s requires HSE=%d SYSCLK=%d" %
                         (profile_id, profile["hse"], profile["sysclk"]))
    incompatible = [
        name for name in ("leds", "mcu", "true_topo", "no_intra_rmux",
                          "pin", "pin_hook", "baseline", "pcf", "hard_carry",
                          "internal_ports")
        if getattr(a, name, None)
    ]
    if incompatible:
        raise ValueError("qualified BRAM source build forbids build option(s): %s" %
                         ", ".join("--" + name.replace("_", "-")
                                   for name in incompatible))
    result = dict(profile)
    result["id"] = profile_id
    return result


def _qualified_pack_profile(a, checkpoint_sha256=None):
    """Resolve a hash-bound retained checkpoint that may bypass no validation."""
    profile = QUALIFIED_ROUTE_PROFILES.get(a.qualified_checkpoint)
    if profile is None or not profile.get("pack_only"):
        raise ValueError(
            "unknown qualified pack profile %r (choose %s)" %
            (a.qualified_checkpoint, ", ".join(sorted(
                name for name, row in QUALIFIED_ROUTE_PROFILES.items()
                if row.get("pack_only")
            )))
        )
    root = _qualified_profile_root(profile)
    source = os.path.join(root, profile["source"])
    checkpoint = os.path.join(root, profile["checkpoint"])
    if os.path.normcase(os.path.realpath(a.input)) != \
            os.path.normcase(os.path.realpath(checkpoint)):
        raise ValueError(
            "qualified pack profile %s requires packaged checkpoint %s" %
            (a.qualified_checkpoint, checkpoint)
        )
    for path, expected, label, actual in (
        (source, profile["source_sha256"], "source", None),
        (checkpoint, profile["checkpoint_sha256"], "checkpoint", checkpoint_sha256),
    ):
        if (actual if actual is not None else _sha256_file(path)) != expected:
            raise ValueError("qualified pack profile %s %s hash drifted" %
                             (a.qualified_checkpoint, label))
    forbidden = sorted(name for name in os.environ if name.startswith("AGAMEMNON_"))
    if forbidden:
        raise ValueError("qualified pack profile forbids ambient option(s): %s" %
                         ", ".join(forbidden))
    result = dict(profile)
    result["id"] = a.qualified_checkpoint
    result["checkpoint_path"] = checkpoint
    result["source_path"] = source
    return result


def _synchronize_build_frequency(env, freq):
    """Use one qualified frequency for timing analysis and emitted hardware.

    ``nextpnr --freq`` without a matching ``AGAMEMNON_SYSCLK`` can produce an
    image that closes timing at one frequency but configures the PLL for
    another.  Resolve CLI/manifest input first, then the environment override,
    then the qualified registry default, and pass that value to both tools.
    """
    requested = env.get("AGAMEMNON_SYSCLK", DEFAULT_FABRIC_FREQUENCY_MHZ) if freq is None else freq
    try:
        numeric = float(requested)
    except (TypeError, ValueError) as exc:
        name = "AGAMEMNON_SYSCLK" if freq is None else "--freq"
        raise ValueError("%s must be an integer MHz value" % name) from exc
    if numeric <= 0:
        name = "AGAMEMNON_SYSCLK" if freq is None else "--freq"
        raise ValueError("%s must be greater than zero" % name)
    if not numeric.is_integer():
        name = "AGAMEMNON_SYSCLK" if freq is None else "--freq"
        raise ValueError(
            "%s must be an integer MHz value supported by the emitted PLL" % name
        )
    sysclk = int(numeric)
    try:
        hse = int(env.get("AGAMEMNON_HSE", "8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("AGAMEMNON_HSE must be an integer MHz value") from exc
    try:
        PLL.require_supported_ratio(sysclk, hse)
    except PLL.UnsupportedPLLConfiguration as exc:
        raise ValueError(str(exc)) from exc
    env["AGAMEMNON_SYSCLK"] = str(sysclk)
    return sysclk


def _run_child(command, **kwargs):
    """Run one tool and tie its lifetime to this CLI process on Windows.

    Windows does not normally terminate a child when its console parent is
    killed.  A cancelled build could therefore leave nextpnr consuming CPU and
    competing with the next invocation.  A kill-on-close Job Object gives the
    process tree Unix-like parent lifetime semantics; if jobs are unavailable,
    retain normal subprocess behaviour rather than making tools unstartable.
    """
    if os.name != "nt":
        return subprocess.run(command, **kwargs)

    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if job:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            job = None

    popen_kwargs = dict(kwargs)
    capture = popen_kwargs.pop("capture_output", False)
    if capture:
        if popen_kwargs.get("stdout") is not None or popen_kwargs.get("stderr") is not None:
            raise ValueError("stdout/stderr may not be used with capture_output")
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(command, **popen_kwargs)
    if job and not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
        kernel32.CloseHandle(job)
        job = None
    try:
        stdout, stderr = proc.communicate()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        if job:
            kernel32.CloseHandle(job)
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _read_pcf(path):
    """Read the useful subset of IceStorm-style PCF: `set_io <port> PIN_<n>`.

    ``n`` is the decimal physical package-lead number. Accept a bare decimal
    number as shorthand, and retain the separately named dedicated ``PIN_HSE``
    clock input, but reject hexadecimal-looking or otherwise non-canonical
    spellings before they can be mistaken for an internal tile, IOMUX, or RMUX
    index.
    """
    pins = {}
    for lineno, raw in enumerate(open(path), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        tok = line.split()
        if len(tok) != 3 or tok[0] != "set_io":
            raise ValueError("%s:%d: expected `set_io <port> PIN_<n>`" % (path, lineno))
        port, pin = tok[1], tok[2].upper()
        if pin.isdecimal():
            pin = "PIN_" + pin
        if pin != "PIN_HSE" and re.fullmatch(r"PIN_[1-9][0-9]*", pin) is None:
            raise ValueError(
                "%s:%d: invalid package pin %r; use a decimal physical lead "
                "such as PIN_10 or 10 (hex forms such as 0x10 are invalid)"
                % (path, lineno, tok[2])
            )
        if port in pins:
            raise ValueError("%s:%d: port %s is assigned twice" % (path, lineno, port))
        pins[port] = pin
    return pins


def _pcf_output_constraints(netlist_path, pcf):
    """Return only PCF constraints whose synthesized IOB can drive the pad.

    A PCF records package placement, not signal direction.  Direction is
    authoritative only after yosys has lowered each top-level port to a
    ``GENERIC_IOB``: an ``I`` input on that cell is the fabric-to-pad path,
    while an ``O`` output is the pad-to-fabric path.  Bidirectional cells have
    both (plus ``EN``) and therefore count as output-capable.

    Resolve names through the top-port PAD bit as well as the scalar cell-name
    spelling so vector constraints such as ``gpio[2]`` work.  Anything other
    than exactly one well-formed IOB per PCF signal is an error; silently
    guessing here can select an output-only architecture presentation for an
    input pad and unnecessarily move an otherwise release-strict build onto a
    research-only surface.
    """
    with open(netlist_path, encoding="utf-8") as fh:
        design = json.load(fh)
    modules = design.get("modules", {})
    if not modules:
        raise ValueError("synthesized design has no modules")
    topname = next((name for name, module in modules.items()
                    if str(module.get("attributes", {}).get("top", "0"))
                    in ("1", "00000000000000000000000000000001")), None)
    if topname is None:
        topname = max(modules, key=lambda name: len(modules[name].get("cells", {})))
    top = modules[topname]
    cells = top.get("cells", {})

    def matches(signal):
        exact = [(name, cell) for name, cell in cells.items()
                 if cell.get("type") == "GENERIC_IOB"
                 and name.endswith("." + signal)]
        if exact:
            return exact
        port = top.get("ports", {}).get(signal)
        if port is not None and len(port.get("bits", [])) == 1:
            pad_bit = port["bits"][0]
            return [(name, cell) for name, cell in cells.items()
                    if cell.get("type") == "GENERIC_IOB"
                    and cell.get("connections", {}).get("PAD") == [pad_bit]]
        match = re.fullmatch(r"(.+)\[(-?\d+)\]", signal)
        if match is None:
            return []
        base, index_text = match.groups()
        port = top.get("ports", {}).get(base)
        if port is None:
            return []
        position = int(index_text) - int(port.get("offset", 0))
        bits = port.get("bits", [])
        if position < 0 or position >= len(bits):
            return []
        pad_bit = bits[position]
        return [(name, cell) for name, cell in cells.items()
                if cell.get("type") == "GENERIC_IOB"
                and cell.get("connections", {}).get("PAD") == [pad_bit]]

    outputs = {}
    for signal, pin in pcf.items():
        resolved = matches(signal)
        if len(resolved) != 1:
            raise ValueError(
                "PCF signal %s matched %d synthesized GENERIC_IOB cells"
                % (signal, len(resolved))
            )
        _name, cell = resolved[0]
        ports = cell.get("port_directions", {})
        pad_input = ports.get("O") == "output"
        pad_output = ports.get("I") == "input"
        output_enable = ports.get("EN") == "input"
        # A tristate declared as an output has I+EN but deliberately no O:
        # it can drive or release the pad but cannot sample it.  Accept that
        # narrower dynamic-output shape alongside scalar I/O and full bidir.
        # EN without a drive path, or a two-way pad without EN, is malformed.
        if (output_enable and not pad_output) or \
                (pad_input and pad_output and not output_enable):
            raise ValueError("PCF signal %s has malformed bidirectional I/O directions" % signal)
        if not pad_input and not pad_output:
            raise ValueError("cannot determine synthesized I/O direction of PCF signal %s" % signal)
        if pad_output:
            outputs[signal] = pin
    return outputs


def _typed_hard_output_pins(netlist, output_pcf):
    """PCF pins owned by a complete typed hard-peripheral output profile.

    Ordinary fabric-driven pads need ``vendor_out_slice`` placement hints.
    Typed hard sources do not: their exact retained corridors begin at hard
    BufMUX roots, and the C++ packer validates every driver/terminal and locks
    every pip.  Require the complete profile here so a partial SPI exposure
    cannot bypass the ordinary fabric presentation and then miss the atomic
    six-lane lock.
    """
    with open(netlist, encoding="utf-8") as stream:
        design = json.load(stream)
    top = next((module for module in design["modules"].values()
                if str(module.get("attributes", {}).get("top", "0"))
                in ("1", "00000000000000000000000000000001")), None)
    if top is None:
        top = max(design["modules"].values(),
                  key=lambda module: len(module.get("cells", {})))
    cell_types = {cell.get("type") for cell in top.get("cells", {}).values()}
    selected_pins = set(output_pcf.values())
    profiles = (
        (
            {"PIN_10"},
            {"MCU_UART0_TXD_DATA", "MCU_UART0_TXD_OE"},
        ),
        (
            {"PIN_12", "PIN_13", "PIN_14"},
            {
                "MCU_SPI0_SCK_DATA", "MCU_SPI0_SCK_OE",
                "MCU_SPI0_CSN_DATA", "MCU_SPI0_CSN_OE",
                "MCU_SPI0_MOSI_DATA", "MCU_SPI0_MOSI_OE",
            },
        ),
        (
            {"PIN_12", "PIN_13", "PIN_14"},
            {
                "MCU_SPI1_SCK_DATA", "MCU_SPI1_SCK_OE",
                "MCU_SPI1_CSN_DATA", "MCU_SPI1_CSN_OE",
                "MCU_SPI1_MOSI_DATA", "MCU_SPI1_MOSI_OE",
            },
        ),
    )
    owned = set()
    for pins, types in profiles:
        if pins <= selected_pins and types <= cell_types:
            owned.update(pins)
    return owned


def _qualified_pad_vendor_out(output_pcf, chipdb=CHIPDB, hard_output_pins=()):
    """Return the one vendor-output slice required by output-capable PCF pads.

    Most qualified pads use the ordinary slice presentation.  A composition
    whose measured approach begins on the vendor F/Q split records the exact
    slice in pad_output_qualified_L48.csv.  The caller must first filter the PCF
    through :func:`_pcf_output_constraints`; package names alone carry no
    direction and must never activate an output-only presentation for an input.
    """
    path = os.path.join(chipdb, "pad_output_qualified_L48.csv")
    if not os.path.exists(path):
        return None
    hard_output_pins = set(hard_output_pins)
    selected = {
        row.get("vendor_out_slice", "").strip()
        for row in csv.DictReader(open(path, newline="", encoding="utf-8"))
        if row.get("pin") in set(output_pcf.values())
        and row.get("pin") not in hard_output_pins
        and row.get("vendor_out_slice", "").strip()
    }
    if len(selected) > 1:
        raise ValueError(
            "PCF selects qualified pads requiring multiple vendor-output slices: %s; "
            "the current architecture option admits one exact slice"
            % ", ".join(sorted(selected))
        )
    return next(iter(selected), None)


def _devdb_fingerprint(arch, emitter, data, emit_env):
    """Content fingerprint for generated uarch databases.

    Device databases are ignored build artifacts.  ``arch.py`` delegates graph
    construction to the Python modules under its engine directory, so hashing
    only the top-level script is insufficient: an upgrade which changes (for
    example) ``features/routing.py`` would otherwise silently reuse the old
    graph.  The default cache is valid only for an exact engine-source,
    generator, data, and environment fingerprint.
    """
    digest = hashlib.sha256()
    arch = os.path.abspath(arch)
    emitter = os.path.abspath(emitter)
    engine_root = os.path.dirname(arch)
    inputs = {arch, emitter}
    for root, dirs, files in os.walk(engine_root):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                inputs.add(os.path.abspath(os.path.join(root, name)))
    for root, dirs, files in os.walk(data):
        dirs.sort()
        for name in sorted(files):
            inputs.add(os.path.abspath(os.path.join(root, name)))
    for path in sorted(inputs):
        rel = os.path.relpath(path, os.path.dirname(arch)).replace("\\", "/")
        digest.update(rel.encode("utf-8") + b"\0")
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    digest.update(json.dumps(sorted(emit_env), separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def _json_has_live_bram_portb(path):
    """Return true when a synthesized BRAM DataOutB bit has a real consumer."""
    design = json.load(open(path, encoding="utf-8"))
    for module in design.get("modules", {}).values():
        refs = {}
        for cell in module.get("cells", {}).values():
            for bits in cell.get("connections", {}).values():
                for bit in bits:
                    if isinstance(bit, int):
                        refs[bit] = refs.get(bit, 0) + 1
        for cell in module.get("cells", {}).values():
            if str(cell.get("type", "")).upper() != "ALTA_BRAM9K":
                continue
            if any(refs.get(bit, 0) > 1 for bit in cell.get("connections", {}).get("DataOutB", [])
                   if isinstance(bit, int)):
                return True
    return False


def _direct_d_source_shape_error(module, cell_name, cell):
    """Return why a tagged source still exposes registered Q externally."""

    def references(bit):
        found = []
        for user_name, user in module.get("cells", {}).items():
            for port, bits in user.get("connections", {}).items():
                for index, value in enumerate(bits):
                    if value == bit:
                        found.append((user_name,
                                      "I[%d]" % index if port == "I" else port))
        for port_name, port in module.get("ports", {}).items():
            for index, value in enumerate(port.get("bits", [])):
                if value == bit:
                    found.append(("$port:%s" % port_name,
                                  "%s[%d]" % (port.get("direction", "unknown"), index)))
        return found

    connections = cell.get("connections", {})
    if cell.get("type") == "LUT":
        lut_q = connections.get("Q", [])
        if len(lut_q) != 1:
            return "tagged LUT requires one Q output"
        dffs = [(name, candidate) for name, candidate in module.get("cells", {}).items()
                if candidate.get("type") == "DFF" and
                candidate.get("connections", {}).get("D", []) == lut_q]
        if len(dffs) != 1:
            return "tagged LUT requires one attached DFF"
        dff_name, dff = dffs[0]
        registered_q = dff.get("connections", {}).get("Q", [])
        if len(registered_q) != 1:
            return "attached DFF requires one Q output"
        q_bit = registered_q[0]
    elif cell.get("type") == "GENERIC_SLICE":
        registered_q = connections.get("Q", [])
        if len(registered_q) != 1:
            return "tagged slice requires one Q output"
        q_bit = registered_q[0]
        dff_name = cell_name
    else:
        return None  # the existing wrong-cell-type diagnostic owns this case

    inputs = connections.get("I", [])
    if len(inputs) <= 3 or inputs[3] != q_bit:
        return "registered Q is not on the tagged cell's I[3]"
    if sorted(references(q_bit)) != sorted([
            (dff_name, "Q"), (cell_name, "I[3]"),
    ]):
        return "registered Q must be local-only on the tagged cell's I[3]"
    return None


def _json_physical_top_module(design, label="design"):
    """Return the one physical module used by admission and emission.

    Yosys JSON may retain parameterized/template modules beside the flattened
    physical top.  Counting every module can therefore inflate or duplicate a
    direct-D composition.  Conversely, picking the first ``top`` silently
    undercounts a malformed JSON with multiple physical tops.  Honor one exact
    top marker, reject multiplicity, and retain the largest-module fallback
    only for older artifacts with one strictly largest module. Current public
    flattened builds carry a unique top marker; an unmarked size tie has no
    safe physical interpretation and fails closed.
    """
    modules = design.get("modules", {})
    if not modules:
        raise ValueError("%s has no modules" % label)
    marked = [
        (name, module) for name, module in modules.items()
        if str(module.get("attributes", {}).get("top", "0"))
        in ("1", "00000000000000000000000000000001")
    ]
    if len(marked) > 1:
        raise ValueError(
            "%s marks multiple physical top modules: %s" %
            (label, ",".join(name for name, _ in marked))
        )
    if marked:
        return marked[0]
    sizes = {
        name: len(module.get("cells", {}))
        for name, module in modules.items()
    }
    largest_size = max(sizes.values())
    largest = [name for name in modules if sizes[name] == largest_size]
    if len(largest) != 1:
        raise ValueError(
            "%s has no unique physical top: largest-module tie at %d cells among %s" %
            (label, largest_size, ",".join(largest))
        )
    name = largest[0]
    return name, modules[name]


def _json_cell_placement_bel(cell, cell_name, label):
    """Return one normalized BEL metadata value, rejecting all ambiguity.

    Synthesized sources use ``BEL`` and routed checkpoints use
    ``NEXTPNR_BEL``. Current public artifacts never need both on one cell, so
    accepting duplicate surfaces provides no compatibility value and risks
    precedence-dependent admission. Case aliases and non-string values are
    malformed rather than silently ignored.
    """
    placements = []
    for raw_name, value in cell.get("attributes", {}).items():
        if not isinstance(raw_name, str):
            continue
        name = raw_name.upper()
        if name not in ("BEL", "NEXTPNR_BEL"):
            continue
        if raw_name != name:
            raise ValueError(
                "%s cell %s placement metadata key %r must use exact casing %s" %
                (label, cell_name, raw_name, name)
            )
        if not isinstance(value, str):
            raise ValueError(
                "%s cell %s placement metadata %s must be a string" %
                (label, cell_name, name)
            )
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError(
                "%s cell %s placement metadata %s is empty" %
                (label, cell_name, name)
            )
        placements.append((name, normalized))
    if len(placements) > 1:
        placements.sort()
        values = {value for _, value in placements}
        detail = ",".join("%s=%s" % item for item in placements)
        if len(values) == 1:
            raise ValueError(
                "%s cell %s uses multiple identical placement metadata surfaces (%s); "
                "duplicates are forbidden" % (label, cell_name, detail)
            )
        raise ValueError(
            "%s cell %s has conflicting placement metadata surfaces (%s)" %
            (label, cell_name, detail)
        )
    return placements[0][1] if placements else None


def _json_checkpoint_placement_bels(path):
    """Return the exact placement map from one selected checkpoint top."""
    if not path:
        return {}
    checkpoint = json.load(open(path, encoding="utf-8"))
    _checkpoint_name, checkpoint_top = _json_physical_top_module(
        checkpoint, "direct-D checkpoint JSON")
    placements = {}
    for name, cell in checkpoint_top.get("cells", {}).items():
        bel = _json_cell_placement_bel(
            cell, name, "direct-D checkpoint JSON")
        if bel is not None:
            placements[name] = bel
    return placements


def _json_resolve_explicit_direct_d_bel(cell_name, source_bel, checkpoint_bels):
    """Reconcile source and selected-checkpoint placement for an explicit cell.

    A checkpoint can supply a missing source placement.  If both surfaces name
    the cell, reject even identical normalized values: registered exact replay
    follows a different build branch, and retained direct-D helper workflows
    prove no compatibility need for cross-file duplication.  Accepting two
    surfaces would otherwise reintroduce precedence-dependent admission.
    """
    checkpoint_bel = checkpoint_bels.get(cell_name)
    if source_bel is not None and checkpoint_bel is not None:
        if source_bel == checkpoint_bel:
            raise ValueError(
                "direct-D cell %s uses multiple identical source/checkpoint "
                "placement metadata surfaces (%s); duplicates are forbidden" %
                (cell_name, source_bel)
            )
        raise ValueError(
            "direct-D cell %s has conflicting source/checkpoint placement "
            "metadata (source=%s, checkpoint=%s)" %
            (cell_name, source_bel, checkpoint_bel)
        )
    return source_bel if source_bel is not None else checkpoint_bel


def _json_admits_direct_d(path, env=None, qualified_checkpoint=None):
    """Admit only the bounded direct-D placements qualified by the release.

    ``qin_pack`` tags inferred own-Q feedback after synthesis.  The tag proves
    that a cell *needs* the direct-D presentation; it is not itself evidence
    that an arbitrary number of state cells may use it. Inferred one-, two-,
    and three-cell compositions carry the N5.4 native-pool capability and are
    left for HeAP to match over X14Y11_SLICE4..7. Explicit/legacy cells remain
    admitted only when every tagged cell carries a distinct qualified BEL.
    Everything else fails before emitting a device database or nextpnr.
    """
    design = json.load(open(path, encoding="utf-8"))
    _top_name, top = _json_physical_top_module(design, "direct-D source JSON")
    tagged = []
    source_shape_errors = []
    for name, cell in top.get("cells", {}).items():
        source_bel = _json_cell_placement_bel(
            cell, name, "direct-D source JSON")
        value = cell.get("attributes", {}).get("agamemnon_direct_d_feedback")
        if str(value).strip() in ("1", "00000000000000000000000000000001"):
            attributes = cell.get("attributes", {})
            tagged.append((name, cell.get("type"), source_bel, attributes))
            error = _direct_d_source_shape_error(top, name, cell)
            if error:
                source_shape_errors.append("%s=%s" % (name, error))
    if not tagged:
        return False

    qualified = {
        "X14Y11_SLICE4", "X14Y11_SLICE5",
        "X14Y11_SLICE6", "X14Y11_SLICE7",
    }
    env = env or {}
    if env.get("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT"):
        qualified.add("X15Y8_SLICE12")
    if env.get("AGAMEMNON_DIRECT_D_X14Y11_S8_EXPERIMENT"):
        qualified.add("X14Y11_SLICE8")
    # F6 direct-D site-broadening campaign (docs/TASK_QUEUE.md F6; see
    # AG32-Docs/tools/direct_d_site_campaign/PROPOSED_AGAMEMNON_PATCH.md):
    # an arbitrary-length, semicolon-separated EXPERIMENTAL site list, exactly
    # as unreleased as the two single-site flags above -- a parsing
    # generalization only, not a change to the shipped release-strict pool.
    # Promoting any site here into the hardcoded set above is a separate,
    # deliberate, evidence-gated step.
    extra = env.get("AGAMEMNON_DIRECT_D_EXTRA_SITES", "")
    qualified |= {s.strip() for s in extra.split(";") if s.strip()}

    checkpoint_bels = _json_checkpoint_placement_bels(qualified_checkpoint)
    tagged = [
        (name, cell_type,
         bel if ("AGRV2K_NATIVE_DIRECT_D_POOL" in attributes or
                 "AGRV2K_NATIVE_DIRECT_D_COUNT" in attributes)
         else _json_resolve_explicit_direct_d_bel(
             name, bel, checkpoint_bels), attributes)
        for name, cell_type, bel, attributes in tagged
    ]
    wrong_type = ["%s=%s" % (name, cell_type) for name, cell_type, _, _ in tagged
                  if cell_type not in ("LUT", "GENERIC_SLICE")]
    native = [item for item in tagged
              if ("AGRV2K_NATIVE_DIRECT_D_POOL" in item[3] or
                  "AGRV2K_NATIVE_DIRECT_D_COUNT" in item[3])]
    if native:
        native_qualified = {
            "X14Y11_SLICE4", "X14Y11_SLICE5",
            "X14Y11_SLICE6", "X14Y11_SLICE7",
        }
        native_errors = []
        expected = set()
        for name, _, original_bel, attributes in native:
            if attributes.get("AGRV2K_NATIVE_DIRECT_D_POOL") != "X14Y11_SLICE4_7_V1":
                native_errors.append("%s=unknown-pool" % name)
            count = str(attributes.get("AGRV2K_NATIVE_DIRECT_D_COUNT", ""))
            if count not in ("1", "2", "3"):
                native_errors.append("%s=bad-count" % name)
            else:
                expected.add(int(count))
            if attributes.get("agamemnon_direct_d_origin") != "qin-pack-inferred-own-q":
                native_errors.append("%s=bad-origin" % name)
            # A native capability and a source BEL are contradictory. A BEL
            # found only in an independently selected checkpoint is not part
            # of this pre-placement source protocol.
            if original_bel is not None:
                native_errors.append("%s=fixed-native" % name)
        fixed = [str(bel) for name, _, bel, attributes in tagged
                 if not ("AGRV2K_NATIVE_DIRECT_D_POOL" in attributes or
                         "AGRV2K_NATIVE_DIRECT_D_COUNT" in attributes)
                 and bel is not None]
        missing_fixed = [name for name, _, bel, attributes in tagged
                         if not ("AGRV2K_NATIVE_DIRECT_D_POOL" in attributes or
                                 "AGRV2K_NATIVE_DIRECT_D_COUNT" in attributes)
                         and bel is None]
        if (not wrong_type and not source_shape_errors and not native_errors and
                expected == {len(tagged)} and
                1 <= len(tagged) <= 3 and not missing_fixed and
                len(set(fixed)) == len(fixed) and set(fixed) <= native_qualified):
            return True
        detail = native_errors
        if expected != {len(tagged)}:
            detail.append("declared=%s actual=%d" %
                          (",".join(map(str, sorted(expected))) or "missing", len(tagged)))
        if missing_fixed:
            detail.append("unbound-explicit=" + ",".join(missing_fixed))
        outside_fixed = [bel for bel in fixed if bel not in native_qualified]
        if outside_fixed:
            detail.append("outside-pool=" + ",".join(outside_fixed))
        if len(set(fixed)) != len(fixed):
            detail.append("duplicate=" + ",".join(sorted({b for b in fixed if fixed.count(b) > 1})))
        if wrong_type:
            detail.append("wrong-cell-type=" + ",".join(wrong_type))
        if source_shape_errors:
            detail.append("wrong-shape=" + ",".join(source_shape_errors))
        raise ValueError(
            "design requests a malformed native direct-D composition (%s); only exact "
            "one-, two-, and three-cell allocations over X14Y11_SLICE4..7 are qualified" %
            ("; ".join(detail) or "not admitted")
        )

    bels = [str(bel) for _, _, bel, _ in tagged if bel is not None]
    if (not wrong_type and not source_shape_errors and len(bels) == len(tagged) and
            len(set(bels)) == len(bels) and set(bels) <= qualified):
        return True

    missing = [name for name, _, bel, _ in tagged if bel is None]
    outside = ["%s=%s" % (name, bel) for name, _, bel, _ in tagged
               if bel is not None and str(bel) not in qualified]
    duplicates = sorted({bel for bel in bels if bels.count(bel) > 1})
    detail = []
    if missing:
        detail.append("unbound=" + ",".join(missing[:8]) + ("..." if len(missing) > 8 else ""))
    if outside:
        detail.append("outside-pool=" + ",".join(outside[:4]) + ("..." if len(outside) > 4 else ""))
    if duplicates:
        detail.append("duplicate=" + ",".join(duplicates))
    if wrong_type:
        detail.append("wrong-cell-type=" + ",".join(wrong_type))
    if source_shape_errors:
        detail.append("wrong-shape=" + ",".join(source_shape_errors))
    raise ValueError(
        "design requires %d own-Q direct-D cell(s), but generic direct-D "
        "placement is outside the qualified release envelope (%s). Use an "
        "exact qualified profile or constrain every cell to a distinct one of "
        "X14Y11_SLICE4..7" % (len(tagged), "; ".join(detail) or "not admitted")
    )


def _json_direct_d_bels(path, qualified_checkpoint=None):
    """Return the emission site envelope after direct-D admission."""
    checkpoint_bels = _json_checkpoint_placement_bels(qualified_checkpoint)
    found = []
    native = False
    design = json.load(open(path, encoding="utf-8"))
    _top_name, top = _json_physical_top_module(design, "direct-D source JSON")
    for name, cell in top.get("cells", {}).items():
        source_bel = _json_cell_placement_bel(
            cell, name, "direct-D source JSON")
        attributes = cell.get("attributes", {})
        value = attributes.get("agamemnon_direct_d_feedback")
        if str(value).strip() not in ("1", "00000000000000000000000000000001"):
            continue
        if ("AGRV2K_NATIVE_DIRECT_D_POOL" in attributes or
                "AGRV2K_NATIVE_DIRECT_D_COUNT" in attributes):
            native = True
            continue
        bel = _json_resolve_explicit_direct_d_bel(
            name, source_bel, checkpoint_bels)
        if bel is None:
            raise ValueError("direct-D cell %s has no admitted BEL" % name)
        found.append(str(bel))
    if native:
        return ["X14Y11_SLICE4", "X14Y11_SLICE5",
                "X14Y11_SLICE6", "X14Y11_SLICE7"]
    return sorted(set(found))


def _wsl_path(path):
    """Translate an absolute Windows path for a nextpnr process launched by WSL.

    WSL is only launched from Windows, where ``os.path`` is ``ntpath``.  Using
    ``ntpath`` explicitly keeps the drive-letter split correct (``C:\\...`` ->
    ``/mnt/c/...``) even when this runs from a POSIX host -- on POSIX,
    ``os.path.splitdrive`` never sees a drive letter and ``os.path.abspath``
    would prepend the POSIX cwd, so the plain-``os.path`` version silently
    failed to translate anything off Windows.
    """
    import ntpath
    if not ntpath.isabs(path):
        path = ntpath.abspath(path)
    drive, tail = ntpath.splitdrive(path)
    if drive and len(drive) >= 2 and drive[1] == ":":
        return "/mnt/%s%s" % (drive[0].lower(), tail.replace("\\", "/"))
    return path.replace("\\", "/")


def _translate_wsl_nextpnr_args(command):
    """Translate only nextpnr's path-bearing arguments, preserving all options."""
    result = list(command)
    for pos, value in enumerate(result):
        if value in ("--json", "--write") and pos + 1 < len(result):
            result[pos + 1] = _wsl_path(result[pos + 1])
        elif value == "-o" and pos + 1 < len(result) and result[pos + 1].startswith("chipdb="):
            result[pos + 1] = "chipdb=" + _wsl_path(result[pos + 1][len("chipdb="):])
    return result


def _forward_wsl_uarch_environment(env):
    """Tell WSL to import uarch controls and its runtime evidence directory."""
    wanted = sorted(key for key in env
                    if key.startswith("AGRV2K_") or key.startswith("NEXTPNR_ROUTER2_"))
    if env.get("AGAMEMNON_DATA"):
        wanted.append("AGAMEMNON_DATA/p")
    existing = [item for item in env.get("WSLENV", "").split(":") if item]
    env["WSLENV"] = ":".join(dict.fromkeys(existing + wanted))


def _route_and_timing_succeeded(log, returncode, require_fmax=False):
    """Require both a routed design and a clean nextpnr timing exit.

    nextpnr prints ``Routing complete`` before checking the requested Fmax.  A
    timing failure must therefore not be mistaken for a successful routing
    attempt merely because that earlier marker is present in the captured log.
    """
    return (returncode == 0 and "Routing complete" in log
            and (not require_fmax or "No Fmax available" not in log))


def _nonretryable_uarch_failure(log):
    """Recognize pack errors that placement seeds and fanout cannot change."""
    return any(marker in log for marker in (
        "dedicated carry requires",
        "malformed or branched carry graph",
        "dedicated carry contains no chain head",
        "fabric AHB master request control",
        "fabric AHB HADDR[2]",
        "fabric AHB HADDR[29]",
        "fabric AHB request payload",
        "cannot be bound to bel",
    ))


def _without_path_entries(path, entries):
    """Remove exact path entries without disturbing the user's remaining PATH."""
    unwanted = {os.path.normcase(os.path.normpath(item)) for item in entries if item}
    return os.pathsep.join(
        item for item in (path or "").split(os.pathsep)
        if item and os.path.normcase(os.path.normpath(item)) not in unwanted
    )


def _build_tool_env(base, oss=None, use_oss=False, runtime=None):
    """Construct a child environment for one external tool family.

    oss-cad-suite ships a self-consistent MinGW runtime for its own programs,
    but those DLLs are not ABI-compatible with an independently built native
    nextpnr.  Never expose the OSS ``bin``/``lib`` directories to a custom
    uarch process; optionally prepend its matching runtime instead.
    """
    child = dict(base)
    oss_entries = [os.path.join(oss, "bin"), os.path.join(oss, "lib")] if oss else []
    path = _without_path_entries(child.get("PATH", ""), oss_entries)
    prepend = oss_entries if use_oss else ([runtime] if runtime else [])
    child["PATH"] = os.pathsep.join([*prepend, path]) if prepend else path
    return child


def _loader_failure_hint(returncode):
    """Translate common Windows/launcher failures into actionable diagnostics."""
    status = returncode & 0xffffffff
    windows = {
        0xC0000135: "a required DLL was not found",
        0xC0000139: "a loaded DLL is ABI-incompatible (entry point not found)",
        0xC000007B: "a DLL has the wrong architecture or image format",
    }
    if status in windows:
        return "%s (Windows status 0x%08X)" % (windows[status], status)
    if returncode == 127:
        return "the launcher or nextpnr executable was not found (exit 127)"
    return "startup exited with status %d" % returncode


def _preflight_nextpnr(command, env):
    """Prove nextpnr can enter ``main`` before classifying any route result."""
    if not command:
        raise RuntimeError("nextpnr command is empty")
    exe = shutil.which(command[0], path=env.get("PATH")) or command[0]
    probe = [exe, *command[1:], "--version"]
    try:
        result = _run_child(probe, env=env, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError("cannot start nextpnr: %s" % exc) from exc
    log = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        detail = _loader_failure_hint(result.returncode)
        tail = log.strip()[-1000:]
        runtime = os.environ.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
        advice = (" Set AGAMEMNON_UARCH_NEXTPNR_RUNTIME to the directory containing the "
                  "matching compiler/runtime DLLs.") if os.name == "nt" and not runtime else ""
        if tail:
            detail += ": " + tail
        raise RuntimeError("nextpnr startup preflight failed: %s.%s" % (detail, advice))
    return log


def _suppress_windows_crash_dialogs():
    """Make child assertion failures return to the CLI instead of opening WER UI."""
    if os.name != "nt":
        return
    import ctypes
    # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def _nextpnr_aborted(log, returncode):
    text = (log or "").lower()
    return ("terminate called after throwing" in text or "assertion failure:" in text
            or (returncode & 0xffffffff) in {0xC0000409, 0x40000015})


def _write_confidence_manifest(*, routed_json, devdb, output, sources, device,
                               admission, routed_sha256, routed_document=None):
    """Report which routed edges the build leaned on without a conduction witness.

    Only the tiered admission model produces tier-2 edges, so only it produces a
    manifest file; a release-strict build has nothing to disclose by
    construction and removes any stale report at that output identity. Failure to
    write the report is never allowed to fail an otherwise good build -- the
    bitstream is the product, this is the disclosure about it -- but it is
    reported rather than swallowed.
    """
    path = output + ".confidence.json"
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    if not devdb or admission in (None, "release-strict"):
        return None
    try:
        sidecar = routing_tiers.load_sidecar(devdb)
        if not sidecar:
            return None
        if routed_document is None:
            with open(routed_json, encoding="utf-8") as handle:
                routed = json.load(handle)
        else:
            routed = routed_document
        from .engine import special_routes
        physical_top = special_routes.physical_top_module(routed)
        routed_sha256 = str(routed_sha256).lower()
        if (len(routed_sha256) != 64 or
                any(char not in "0123456789abcdef" for char in routed_sha256)):
            raise ValueError("routed snapshot SHA-256 is malformed")
        output_sha256 = _sha256_file(output)
        manifest = routing_tiers.build_manifest(
            routed_module=physical_top,
            sidecar=sidecar,
            sidecar_meta=routing_tiers.load_sidecar_meta(devdb),
            design=", ".join(os.path.basename(name) for name in sources),
            output=os.path.abspath(output),
            device=device,
            devdb=devdb,
            admission_model=admission,
            extra={"bindings": {
                "routed_sha256": routed_sha256,
                "output_sha256": output_sha256,
            }},
        )
        routing_tiers.write_manifest(path, manifest)
    except (OSError, ValueError) as exc:
        print("warning: could not write the routing confidence manifest (%s)" % exc)
        return None
    for line in routing_tiers.render_summary(manifest, path):
        print(line)
    return path


def _validate_uarch_devdb(path):
    """Fail before nextpnr when a custom/generated database lacks required resources."""
    required = ["dev_meta.csv", "dev_wires.csv", "dev_bels.csv", "dev_belpins.csv", "dev_pips.csv"]
    missing = [name for name in required if not os.path.isfile(os.path.join(path, name))]
    if missing:
        raise RuntimeError("uarch device database is incomplete: missing %s" % ", ".join(missing))
    bels = open(os.path.join(path, "dev_bels.csv"), encoding="utf-8").read().splitlines()
    if not any(line.startswith("CLKIN,") for line in bels[1:]):
        raise RuntimeError("uarch device database has no CLKIN bel (emit with AGAMEMNON_LEDPADS=1)")
    from .engine import special_routes
    try:
        special_routes.validate_devdb(path)
    except special_routes.SpecialRouteError as exc:
        raise RuntimeError(str(exc)) from exc


def _uarch_prefers_heap(synth_json):
    """Select HeAP first for the boundary/dense shapes it is meant to spread.

    The source-level density threshold mirrors the existing >16-fabric-cell
    boundary used by the uarch's dense MCU handling.  This only selects an
    already-supported placer; it does not predict a route or relax legality.
    """
    with open(synth_json, encoding="utf-8") as stream:
        design = json.load(stream)
    cell_types = [
        cell.get("type", "")
        for module in design.get("modules", {}).values()
        for cell in module.get("cells", {}).values()
    ]
    has_mcu_boundary = any(
        cell_type in ("MCU_DIN", "MCU_DOUT") or
        cell_type.startswith("MCU_AHB_") or
        cell_type.startswith("MCU_SLAVE_AHB_")
        for cell_type in cell_types
    )
    fabric_types = {"LUT", "DFF", "GENERIC_SLICE", "AG32_FA"}
    dense_fabric = sum(cell_type in fabric_types for cell_type in cell_types) > 16
    return has_mcu_boundary or dense_fabric


def _uarch_attempts(requested_cap, maxfo, split_first=False, heap_first=False):
    """Return the deterministic placement/fanout escalation order.

    The requested density must remain a real candidate after fanout splitting;
    large designs such as SERV cannot route unsplit, and historically jumped
    straight to cap 8 despite an explicit ``--cap`` value.
    """
    caps = sorted({2, 4, 8, requested_cap})
    attempts = [(cap, 0) for cap in caps]
    # A fully locked conduction-aware placement can be less routable than
    # nextpnr's analytic placer on wide designs: the hard-block pin packers
    # already lock the physically constrained cells and corridors, while
    # CONDPLACE additionally locks every ordinary slice into a compact region.
    # Give the untouched netlist one analytic-placement attempt before changing
    # its logic with fanout splitting.  cap=0 is an internal sentinel; user
    # density values are positive.
    attempts.append((0, 0))
    fos = list(dict.fromkeys(fo for fo in (16, 8, 4, maxfo) if fo > 0))
    split_caps = sorted({requested_cap, caps[-1]})
    attempts.extend((cap, fo) for fo in fos for cap in split_caps)
    if heap_first:
        attempts = [(0, 0)] + [attempt for attempt in attempts if attempt != (0, 0)]
    if split_first:
        # Every qualified true-dual-port SERV route needs the cap-5/maxfo-16
        # netlist. Try the caller's requested cap at maxfo 16 first, while
        # retaining the complete unsplit/split fallback matrix afterward.
        preferred = (requested_cap, 16)
        attempts = [preferred] + [attempt for attempt in attempts if attempt != preferred]
    return attempts


def _decode_to_raw(bin_bytes):
    """Return the fixed 99936-byte raw image from either form `pack` produces: an already-
    uncompressed image (99944 B = 8-byte header + 99936 raw) is returned as-is; a compressed .bin
    (header + LZW) is LZW-decoded, stopping at the target so trailing flash padding is ignored."""
    if len(bin_bytes) - 8 == RAW_LEN:
        return bytes(bin_bytes[8:])
    payload = bin_bytes[8:]
    gen = L.bits_msb(payload)

    def rd(n):
        v = 0
        for _ in range(n):
            try:
                v = (v << 1) | next(gen)
            except StopIteration:
                return None
        return v
    dic = {i: bytes([i]) for i in range(L.CLEAR)}
    w, nxt, out, prev = 9, L.FIRST, bytearray(), None
    while len(out) < RAW_LEN:
        c = rd(w)
        if c is None or c == L.EOI:
            break
        if c == L.CLEAR:
            dic = {i: bytes([i]) for i in range(L.CLEAR)}; w, nxt, prev = 9, L.FIRST, None; continue
        e = dic[c] if c in dic else (prev + prev[:1] if c == nxt else None)
        if e is None:
            raise ValueError(f"bad code {c} (nxt={nxt})")
        out += e
        if prev is not None:
            dic[nxt] = prev + e[:1]; nxt += 1
            if nxt == (1 << w) and w < L.MAXW:
                w += 1
        prev = e
    if len(out) < RAW_LEN:
        raise ValueError(
            "LZW stream ended after %d byte(s); expected at least %d "
            "(truncated or corrupted input)" % (len(out), RAW_LEN)
        )
    # A code decoded right at the target boundary can be a multi-byte
    # dictionary entry that overshoots it; truncate to the contracted
    # length instead of silently returning the extra bytes (every fixed
    # absolute offset downstream, e.g. agasc.CRC_OFFSET, assumes exactly
    # RAW_LEN bytes).
    return bytes(out[:RAW_LEN])


def patch_lut(raw, x, y, z, new_mask):
    """Open LUT editor: set the LE at (x,y,z) to truth table `new_mask` (16 bits). SRAM stores
    the complement (validated byte-exact vs af.exe in lut_edit.py)."""
    raw = bytearray(raw)
    for b in range(16):
        byte, mask = physmap.init_bit_pos(x, y, z, b)
        if not ((new_mask >> b) & 1):
            raw[byte] |= mask
        else:
            raw[byte] &= ~mask & 0xFF
    return bytes(raw)


def cmd_decode(a):
    raw = _decode_to_raw(open(a.input, "rb").read())
    open(a.output, "wb").write(raw)
    print(f"decoded {a.input} -> {a.output} ({len(raw)} bytes raw)")


def cmd_encode(a):
    raw = open(a.input, "rb").read()
    out = HDR + L.encode(raw)
    open(a.output, "wb").write(out)
    print(f"encoded {a.input} -> {a.output} ({len(out)} byte .bin)")


def cmd_to_agasc(a):
    """Convert either compressed or raw-form .bin into lossless per-tile ASCII."""
    from .engine import agasc
    data = open(a.input, "rb").read()
    if len(data) < 8:
        raise agasc.AgascError("fabric image is shorter than its 8-byte header")
    raw = _decode_to_raw(data)
    text = agasc.dumps(raw, CHIPDB, header=data[:8])
    with open(a.output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    ntiles = sum(1 for line in text.splitlines() if line.startswith(".tile "))
    nfeatures = sum(1 for line in text.splitlines() if line.startswith("+"))
    print(f"to-agasc {a.input} -> {a.output}: {ntiles} tile(s), {nfeatures} asserted named feature(s)")


def cmd_from_agasc(a):
    """Assemble .agasc, regenerate its CRC, and LZW-compress a flashable .bin."""
    from .engine import agasc
    with open(a.input, encoding="utf-8") as handle:
        header, raw = agasc.loads(handle.read(), CHIPDB)
    out = header + (raw if a.uncompressed else L.encode(raw))
    with open(a.output, "wb") as handle:
        handle.write(out)
    form = "uncompressed" if a.uncompressed else "LZW-compressed"
    print(f"from-agasc {a.input} -> {a.output} ({len(out)} byte {form} .bin)")


def _read_fabric_image(path):
    data = open(path, "rb").read()
    if len(data) < 8:
        raise ValueError("fabric image %s is shorter than its 8-byte header" % path)
    header = data[:8]
    raw = _decode_to_raw(data)
    form = "uncompressed" if len(data) - 8 == RAW_LEN else "lzw-compressed"
    metadata = {
        "form": form,
        "source_bytes": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "decoded_raw_bytes": len(raw),
        "canonical_uncompressed_sha256": hashlib.sha256(header + raw).hexdigest(),
    }
    return header, raw, metadata


def cmd_explain(a):
    """Print a semantic description of a compressed or uncompressed image."""
    from .engine import bitstream_inspect as inspect
    header, raw, metadata = _read_fabric_image(a.input)
    tile = tuple(int(value, 0) for value in a.tile.split(",")) if a.tile else None
    if tile is not None and len(tile) != 2:
        raise ValueError("--tile must be X,Y")
    report = inspect.describe(header, raw, CHIPDB, include_raw=a.raw, tile=tile)
    report["image"] = metadata
    output = json.dumps(report, indent=2, sort_keys=True) + "\n" if a.json else inspect.format_description(report)
    if a.output:
        with open(a.output, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    else:
        sys.stdout.write(output)


def cmd_diff(a):
    """Compare two images by named feature and unmapped physical byte."""
    from .engine import bitstream_inspect as inspect
    old_header, old_raw, old_metadata = _read_fabric_image(a.old)
    new_header, new_raw, new_metadata = _read_fabric_image(a.new)
    report = inspect.compare(old_header, old_raw, new_header, new_raw, CHIPDB, include_crc=a.crc)
    report["images"] = {"old": old_metadata, "new": new_metadata}
    output = json.dumps(report, indent=2, sort_keys=True) + "\n" if a.json else inspect.format_diff(report)
    if a.output:
        with open(a.output, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    else:
        sys.stdout.write(output)


def cmd_edit_lut(a):
    from .engine import agasc
    data = open(a.input, "rb").read()
    raw = _decode_to_raw(data)
    x, y, z = (int(v) for v in a.le.split(","))
    raw2 = bytearray(patch_lut(raw, x, y, z, int(a.init, 0)))
    # patch_lut changes configuration payload bytes, so the stored fabric CRC
    # inherited from the input is stale.  Recompute it before compression;
    # otherwise FCB rejects an apparently well-formed edited image.
    header = data[:8]
    crc = agasc.crc32_bzip2(header + bytes(raw2[:agasc.CRC_OFFSET]))
    raw2[agasc.CRC_OFFSET:agasc.CRC_OFFSET + 4] = crc.to_bytes(4, "big")
    # Preserve the source representation.  SRAM injection consumes the
    # canonical 99,944-byte uncompressed form, while flash artifacts normally
    # use LZW.  Silently converting between them makes an otherwise valid edit
    # unusable by the caller's transport.
    out = header + (raw2 if len(data) - 8 == RAW_LEN else L.encode(raw2))
    open(a.output, "wb").write(out)
    nchg = sum(1 for i in range(agasc.CRC_OFFSET) if raw[i] != raw2[i])
    print(f"edit-lut LE({x},{y},{z}) INIT={a.init}: {nchg} raw byte(s) changed -> {a.output}")


def cmd_pack(a):
    """icepack-equivalent: routed nextpnr JSON -> flashable .bin, via the self-contained package
    engine (no vendor binary). Writes <out> (99944-byte uncompressed, for SRAM inject) + <out>.comp
    (LZW-compressed, for flash)."""
    from .engine import special_routes
    env = dict(os.environ)
    policy_sidecar = env.get("AGAMEMNON_POLICY_SIDECAR")
    ownership_trace = env.get("AGAMEMNON_OWNERSHIP_TRACE")
    emission_products = [
        ("pack output", a.output, None),
        ("compressed pack output", a.output + ".comp", None),
        ("default policy sidecar", a.output + ".policy.json", "policy"),
        ("intermediate policy sidecar", a.output + ".comp.policy.json", "policy"),
        ("selected policy sidecar", policy_sidecar, "policy"),
        ("confidence report", a.output + ".confidence.json", "confidence"),
        ("ownership trace", ownership_trace, None),
    ]
    pack_inputs = [("routed input", a.input)]
    if a.baseline:
        pack_inputs.append(("baseline input", a.baseline))
    try:
        _validate_emission_product_paths(pack_inputs, emission_products)
        _remove_emission_products(emission_products)
    except ValueError as exc:
        print("error: %s" % exc)
        sys.exit(2)
    try:
        snapshot = special_routes.load_validated_routed_json(
            a.input, "direct-pack",
            chipdb_root=env.get("AGAMEMNON_DATA"),
        )
    except special_routes.SpecialRouteError as exc:
        print("error: %s" % exc)
        sys.exit(2)
    to_bin = os.path.join(ENGINE, "to_bin.py")
    qualified_profile = None
    if getattr(a, "qualified_checkpoint", None):
        if getattr(a, "research_unsafe", False) or a.baseline:
            print("error: qualified checkpoint pack forbids --research-unsafe and --baseline")
            sys.exit(2)
        try:
            qualified_profile = _qualified_pack_profile(
                a, checkpoint_sha256=snapshot.sha256)
        except (OSError, ValueError) as exc:
            print("error: %s" % exc)
            sys.exit(2)
        env["AGAMEMNON_QUALIFIED_ROUTE_PROFILE"] = qualified_profile["id"]
    if getattr(a, "research_unsafe", False):
        for name in ("AGAMEMNON_CLEAN_SEL_GATE", "AGAMEMNON_ALLOW_UNMAPPED"):
            env.pop(name, None)
        env.update({
            "AGAMEMNON_RESEARCH_UNSAFE": "1",
            "AGAMEMNON_STRICT_POLICY": "research-unsafe",
            "AGAMEMNON_MESH_TEMPLATE": "1",
        })
    if getattr(a, "require_clean_selectors", False):
        env["AGAMEMNON_CLEAN_SEL_GATE"] = "1"
    if a.baseline:
        env["AGAMEMNON_BASELINE"] = a.baseline
    env["AGAMEMNON_VALIDATED_ROUTED_SHA256"] = snapshot.sha256
    try:
        with tempfile.TemporaryDirectory(prefix="agamemnon_pack_snapshot_") as staged_dir:
            staged_input = _stage_validated_routed_json(snapshot, staged_dir)
            r = _run_child([sys.executable, to_bin, staged_input, a.output], env=env,
                           capture_output=True, text=True)
    except OSError as exc:
        print("error: cannot stage validated routed snapshot: %s" % exc)
        sys.exit(2)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        print("error: pack failed"); sys.exit(r.returncode)
    if qualified_profile:
        produced = {
            a.output: qualified_profile["bitstream_sha256"],
            a.output + ".comp": qualified_profile["compressed_sha256"],
        }
        mismatches = [(path, _sha256_file(path), expected)
                      for path, expected in produced.items()
                      if _sha256_file(path) != expected]
        if mismatches:
            for path in produced:
                try:
                    os.remove(path)
                except OSError:
                    pass
            print("error: qualified checkpoint pack output hash mismatch")
            for path, actual, expected in mismatches:
                print("  %s: got %s expected %s" % (path, actual, expected))
            sys.exit(1)
        print("qualified checkpoint pack exact raw/compressed hashes verified: %s" %
              qualified_profile["id"])


def cmd_unpack(a):
    """iceunpack-equivalent: .bin -> the 99936-byte raw fabric config image."""
    cmd_decode(a)


def cmd_verify(a):
    """Offline, hardware-free behavioural check of a routed design: cycle-sim the routed netlist and report
    the AHB read-values it will produce. With --observed, compare a silicon-observed value set (SOUND/COVER
    + MCU_DOUT bind). See engine/verify_netlist.py."""
    from .engine import verify_netlist as V
    if a.observed is not None:
        obs = [int(x, 0) for x in a.observed.split(",") if x.strip() != ""]
        ok = V.verify(a.input, obs, a.cycles)
        sys.exit(0 if ok else 1)
    ok = V.summary(a.input, a.cycles)
    sys.exit(0 if ok else 1)


def cmd_status_overlay(a):
    """Attach one separately routed user event to the qualified public32 core."""
    from .engine import status_overlay as SO
    try:
        report = SO.compose_files(
            a.input, a.output,
            devdb=a.devdb if a.devdb else SO.DEFAULT_DEVDB,
        )
    except (OSError, json.JSONDecodeError, SO.StatusOverlayError) as exc:
        print("error: status overlay rejected: %s" % exc)
        sys.exit(1)
    print("status overlay -> %s" % a.output)
    print(json.dumps(report, sort_keys=True))


def _default_carry_fallback_allowed(a):
    """Whether an implicit hard-carry build may retry with LUT carry."""
    return (a.uarch and not getattr(a, "hard_carry", False) and
            not getattr(a, "no_hard_carry", False) and
            not a.qualified_checkpoint and
            not getattr(a, "qualified_bram_write", None))


def cmd_build(a):
    """Single-command open build: Verilog -> yosys synth -> nextpnr place&route -> our bitgen -> .bin,
    entirely from the self-contained package (engine/ + chipdb/ + synth/). No vendor binary. yosys and
    nextpnr-generic come from $AGAMEMNON_OSS/bin (or PATH). $AGAMEMNON_DATA overrides the shipped chip
    DB and $AGAMEMNON_ENGINE overrides the engine dir, but both default to the packaged copies."""
    from .engine import special_routes
    _suppress_windows_crash_dialogs()
    freq = getattr(a, "freq", None)
    if freq is not None and freq <= 0:
        print("error: --freq must be greater than zero")
        sys.exit(2)
    project = None
    if not getattr(a, "input", None):
        try:
            project = PJ.Project.load(getattr(a, "project", None))
        except (OSError, ValueError) as exc:
            print("error: %s" % exc)
            sys.exit(2)
        if project.external:
            PJ.build_external(project)
            return
        try:
            qualified_fabric = PJ.build_qualified_fabric(project)
            if qualified_fabric:
                PJ.check_qualified_profile_mcu_pairing(
                    project, project.fabric.get("qualified_profile")
                )
        except (OSError, ValueError, RuntimeError) as exc:
            print("error: %s" % exc)
            sys.exit(1)
        if qualified_fabric:
            mcu_output = PJ.build_mcu(project)
            PJ.write_flash_plan(
                project, mcu_output=mcu_output,
                fabric_output=qualified_fabric,
            )
            return
        if not PJ.apply_fabric_config(a, project):
            mcu_output = PJ.build_mcu(project)
            PJ.write_flash_plan(project, mcu_output=mcu_output)
            return
        freq = getattr(a, "freq", None)
        if freq is not None and freq <= 0:
            print("error: --freq must be greater than zero")
            sys.exit(2)
    sources = [a.input] + list(getattr(a, "sources", None) or [])
    top = getattr(a, "top", None)
    if top and not re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", top):
        print("error: --top must be a Verilog module identifier")
        sys.exit(2)
    engine = os.environ.get("AGAMEMNON_ENGINE", ENGINE)
    data = os.environ.get("AGAMEMNON_DATA", CHIPDB)
    if getattr(a, "hard_carry", False) and not a.uarch:
        print("error: --hard-carry requires --uarch")
        sys.exit(2)
    if getattr(a, "no_hard_carry", False) and not a.uarch:
        print("error: --no-hard-carry requires --uarch")
        sys.exit(2)
    compact_maxd = getattr(a, "compact_maxd", None)
    if compact_maxd is not None and not a.uarch:
        print("error: --compact-maxd requires --uarch")
        sys.exit(2)
    if compact_maxd is not None and compact_maxd < 1:
        print("error: --compact-maxd must be greater than zero")
        sys.exit(2)
    if a.qualified_checkpoint and not a.uarch:
        print("error: --qualified-checkpoint requires --uarch")
        sys.exit(2)
    if getattr(a, "qualified_bram_write", None) and not a.uarch:
        print("error: --qualified-bram-write requires --uarch")
        sys.exit(2)
    if a.qualified_checkpoint and getattr(a, "qualified_bram_write", None):
        print("error: --qualified-checkpoint and --qualified-bram-write are mutually exclusive")
        sys.exit(2)
    if a.qualified_checkpoint and getattr(a, "research_unsafe", False):
        print("error: --qualified-checkpoint cannot be combined with --research-unsafe")
        sys.exit(2)
    if getattr(a, "qualified_bram_write", None) and getattr(a, "research_unsafe", False):
        print("error: --qualified-bram-write cannot be combined with --research-unsafe")
        sys.exit(2)
    base = os.path.splitext(os.path.basename(a.input))[0]
    out = a.output or (base + ".bin")
    write_routed = getattr(a, "write_routed", None)
    policy_sidecar = os.environ.get("AGAMEMNON_POLICY_SIDECAR")
    ownership_trace = os.environ.get("AGAMEMNON_OWNERSHIP_TRACE")
    emission_products = [
        ("build output", out, None),
        ("compressed build output", out + ".comp", None),
        ("requested routed output", write_routed, None),
        ("default policy sidecar", out + ".policy.json", "policy"),
        ("intermediate policy sidecar", out + ".comp.policy.json", "policy"),
        ("selected policy sidecar", policy_sidecar, "policy"),
        ("build confidence report", out + ".confidence.json", "confidence"),
        ("routed confidence report",
         write_routed + ".confidence.json" if write_routed else None,
         "confidence"),
        ("ownership trace", ownership_trace, None),
    ]
    build_inputs = [("Verilog input", source) for source in sources]
    if a.pcf:
        build_inputs.append(("PCF input", a.pcf))
    if a.baseline:
        build_inputs.append(("baseline input", a.baseline))
    try:
        _validate_emission_product_paths(build_inputs, emission_products)
    except ValueError as exc:
        print("error: %s" % exc)
        sys.exit(2)
    # Set by the uarch flow so the post-route confidence manifest can find the
    # routing-tier sidecar that was emitted alongside this build's device graph.
    uarch_devdb = None
    tmp = tempfile.mkdtemp(prefix="agamemnon_build_")
    synth_json = os.path.join(tmp, base + ".json")
    routed_json = os.path.join(tmp, base + "_routed.json")

    env = dict(os.environ)
    env["AGAMEMNON_DATA"] = data
    # Never inherit an undocumented placement experiment accidentally. The
    # CLI option is the sole public selector and WSLENV forwards AGRV2K_*.
    if compact_maxd is None:
        env.pop("AGRV2K_COMPACT_MAXD", None)
    else:
        env["AGRV2K_COMPACT_MAXD"] = str(compact_maxd)
    # --device/--part are explicit CLI selectors over the family/package
    # registries (agamemnon/engine/{device,family}.py); AGAMEMNON_DEVICE
    # remains the sole architecture/legality selector, and --part is
    # descriptive surround metadata that claim_policy cross-checks against it.
    if getattr(a, "part", None):
        part = _family.get_part(a.part)
        if getattr(a, "device", None) and a.device != part.device_id:
            print("error: --part %s is package %s, which does not match --device %s"
                  % (a.part, part.device_id, a.device))
            sys.exit(2)
        env["AGAMEMNON_PART"] = a.part
        env["AGAMEMNON_DEVICE"] = part.device_id
    elif getattr(a, "device", None):
        env["AGAMEMNON_DEVICE"] = a.device
    research_unsafe = bool(getattr(a, "research_unsafe", False))
    release_strict = bool(getattr(a, "release_strict", False))
    require_clean_selectors = bool(
        getattr(a, "require_clean_selectors", False))
    # A hash-bound qualified profile was qualified against the release-strict
    # device graph, so it is built against that graph whatever the ambient
    # default is. Exact replay makes the graph irrelevant to the emitted bytes
    # in practice -- both profiles reproduce their pinned hashes either way --
    # but "the qualified artifact is produced by the qualified graph" should be
    # true by construction rather than by a coincidence someone has to re-check.
    if a.qualified_checkpoint or getattr(a, "qualified_bram_write", None):
        release_strict = True
    if release_strict and research_unsafe:
        print("error: --release-strict and --research-unsafe are opposite admission models")
        sys.exit(2)
    if release_strict and not a.uarch:
        print("error: --release-strict applies to the --uarch device graph")
        sys.exit(2)
    if require_clean_selectors and not a.uarch:
        print("error: --require-clean-selectors applies to the --uarch device graph")
        sys.exit(2)
    # The admission model is decided by this call's flags, never inherited: an
    # ambient value would silently change which edges a build may use and, worse,
    # which device-database cache it lands in.
    env.pop("AGAMEMNON_ROUTING_ADMISSION", None)
    if research_unsafe:
        for name in (
            "AGAMEMNON_CLEAN_SEL_GATE", "AGAMEMNON_STRICT_GATE",
            "AGAMEMNON_CONDUCTION_GATE", "AGAMEMNON_OBSERVED_ONLY",
            "AGAMEMNON_TRUSTED", "AGAMEMNON_TRUE_TOPO",
            "AGAMEMNON_ALLOW_UNMAPPED",
        ):
            env.pop(name, None)
        env.update({
            "AGAMEMNON_RESEARCH_UNSAFE": "1",
            "AGAMEMNON_STRICT_POLICY": "research-unsafe",
            "AGAMEMNON_XBAR_FULL": "1",
            "AGAMEMNON_XBAR_CONDUCT": "1",
            "AGAMEMNON_SOFT_PREFER": "1",
            "AGAMEMNON_CLEAN_SEL_PREFER": "1",
            "AGAMEMNON_MESH_TEMPLATE": "1",
        })
        if require_clean_selectors:
            env["AGAMEMNON_CLEAN_SEL_GATE"] = "1"
            env.pop("AGAMEMNON_CLEAN_SEL_PREFER", None)
    require_timing_path = freq is not None or "AGAMEMNON_SYSCLK" in env
    try:
        freq = _synchronize_build_frequency(env, freq)
    except ValueError as exc:
        print("error: %s" % exc)
        sys.exit(2)
    qualified_profile = None
    qualified_bram_source = None
    if a.qualified_checkpoint:
        try:
            qualified_profile = _qualified_route_profile(
                a, sources, engine, data, env, freq)
        except (OSError, ValueError) as exc:
            print("error: %s" % exc)
            sys.exit(2)
    if getattr(a, "qualified_bram_write", None):
        try:
            qualified_bram_source = _qualified_bram_source_profile(
                a, sources, engine, data, env, freq)
        except (OSError, ValueError) as exc:
            print("error: %s" % exc)
            sys.exit(2)
        env["AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE"] = qualified_bram_source["id"]
    print("[build] clock: timing target and emitted PLL = %d MHz" % freq)
    oss = os.environ.get("AGAMEMNON_OSS")
    env["PYTHONPATH"] = os.pathsep.join([engine, env.get("PYTHONPATH", "")])
    for flag, var in [(a.leds, "AGAMEMNON_LEDPADS"), (a.mcu, "AGAMEMNON_MCU_ENTRY"),
                      (a.true_topo, "AGAMEMNON_TRUE_TOPO"), (a.no_intra_rmux, "AGAMEMNON_NO_INTRA_RMUX")]:
        if flag: env[var] = "1"

    # Reject already-selected experimental/archival surfaces before invoking
    # Yosys or nextpnr. Bitgen remains the final authority because synthesis
    # can discover additional surfaces (for example direct-D or BRAM Port B),
    # but a manifest-known policy violation should not burn a cold user's
    # build time before failing closed.
    try:
        evaluate_policy(engine_options_from(env))
    except ClaimPolicyError as exc:
        print(str(exc))
        print("error: build claim-policy preflight failed before synthesis")
        sys.exit(1)
    # The uarch allocates its one qualified 33-site corridor to one eligible
    # arithmetic chain before generic lowering. Other and oversized chains now
    # degrade independently to LUT arithmetic, so carry can be the safe default
    # without one unsuitable chain refusing the whole build. --hard-carry is
    # retained as a compatibility spelling; --no-hard-carry is the explicit
    # byte-stream/regression escape hatch.
    if a.uarch and not getattr(a, "no_hard_carry", False):
        env["AGAMEMNON_HW_CARRY"] = "1"
    else:
        env.pop("AGAMEMNON_HW_CARRY", None)
    if a.pin: env["AGAMEMNON_PIN"] = a.pin
    if a.baseline: env["AGAMEMNON_BASELINE"] = a.baseline
    if a.pcf:
        try:
            _pcf = _read_pcf(a.pcf)
        except ValueError as e:
            print("error: %s" % e); sys.exit(2)
        env["AGAMEMNON_PCF_JSON"] = json.dumps(_pcf, sort_keys=True)
        env["AGAMEMNON_PHYSICAL_IO"] = "1"
        env["AGAMEMNON_LEDPADS"] = "1"       # exposes the physical OPAD bels for constrained outputs
        env["AGAMEMNON_PADFEED_TOP"] = "1"    # real top-row feeder + terminal pips
        env["AGAMEMNON_HARDEN_PADFEED"] = "1"
        # Keep the strict graph's feedback bridges.  Qin packing makes registered
        # self-feedback use the intended INTERNAL path, while large sequential
        # designs still need the remaining proven bridge resources; removing the
        # entire family makes a routed SERV image fail its reset/run behaviour.
        if not a.uarch:
            # The legacy Python architecture's physical-PCF placer relies on
            # this narrower graph; the C++ large-design uarch does not.
            env["AGAMEMNON_NO_FFBRIDGE"] = "1"
        # Re-run the claim-policy preflight now that --pcf has turned on the
        # physical/electrical surface (AGAMEMNON_PHYSICAL_IO and friends).
        # The first preflight above ran before these flags existed, so a
        # pad-free build on an unqualified package correctly passed it; a
        # pcf-driven build activating a physical/electrical claim on an
        # unqualified package must still fail before burning synth/PnR time,
        # not only later at bitgen's final-authority check.
        try:
            evaluate_policy(engine_options_from(env))
        except ClaimPolicyError as exc:
            print(str(exc))
            print("error: build claim-policy preflight failed before synthesis")
            sys.exit(1)
    if getattr(a, "internal_ports", False):
        if not a.uarch or a.pcf:
            print("error: --internal-ports requires --uarch and forbids --pcf")
            sys.exit(2)
        if not getattr(a, "write_routed", None):
            print("error: --internal-ports requires --write-routed")
            sys.exit(2)
        env["AGAMEMNON_INTERNAL_PORTS"] = "1"

    try:
        _remove_emission_products(emission_products)
    except ValueError as exc:
        print("error: %s" % exc)
        sys.exit(2)

    def run(step, cmd, check=True, child_env=None):
        child_env = child_env or env
        exe = shutil.which(cmd[0], path=child_env.get("PATH")) or cmd[0]   # Windows: find via child PATH
        cmd = [exe] + cmd[1:]
        print("[build] %s: %s" % (step, " ".join(os.path.basename(c) if os.sep in c else c for c in cmd)))
        try:
            r = _run_child(cmd, env=child_env, capture_output=True, text=True)
        except OSError as exc:
            # Fail closed with an actionable message instead of a raw
            # FileNotFoundError traceback (the nextpnr path has its own preflight;
            # this covers yosys and any other external build tool that is absent).
            print("error: %s: cannot start '%s' (%s). Install it -- yosys and "
                  "nextpnr-generic ship with oss-cad-suite -- or point AGAMEMNON_OSS "
                  "at your oss-cad-suite/bin directory." % (step, cmd[0], exc))
            sys.exit(1)
        run.returncode = r.returncode
        if r.returncode != 0 and check:
            print(r.stdout[-1500:]); print(r.stderr[-1500:]); print("error: %s failed" % step); sys.exit(1)
        return r.stdout + r.stderr

    # always wrap top-level ports as GENERIC_IOB (iopadmap) so nextpnr can bind them to IO bels
    synth_tcl = os.path.join(stage_windows_directory(SYNTH), "synth_pads.tcl")
    oss_env = _build_tool_env(env, oss=oss, use_oss=bool(oss))
    # Pass the Tcl file as its own process argument. Embedding it in a Yosys
    # ``-p`` command loses paths containing spaces before Tcl can parse them.
    synth_env = dict(oss_env)
    synth_env["AGAMEMNON_YOSYS_LUT_K"] = "4"
    synth_env["AGAMEMNON_YOSYS_JSON"] = synth_json
    synth_env["AGAMEMNON_YOSYS_TOP"] = top or ""
    run("synth", ["yosys", "-q", "-c", synth_tcl, *sources],
        child_env=synth_env)
    # SILENT-DEGRADATION GUARD: synth_pads.tcl writes a stable JSON sidecar
    # (<synth_json>.leftover_mem.json) naming every memory cell that
    # memory_libmap declined to map onto the hard ALTA_BRAM9K block RAM (see
    # the guard comment there for why: an unmapped memory is silently lowered
    # to one flip-flop per bit plus an address-decode LUT tree, an
    # order-of-magnitude resource cliff with zero visible signal under the
    # campaign's `-q` build -- `run()` above only prints captured output when
    # the step itself *fails*, so a passing build previously left no trace
    # anywhere). Surface it loudly. This is a WARNING by default, not a
    # failure: a pure read-only ROM (no write port) can never map to
    # ALTA_BRAM9K at any size -- that is an expected, size-independent
    # outcome, not a defect -- so treating every occurrence as fatal breaks
    # entire legitimate design families (e.g. the fuzz factory's bram_rom
    # generator). Pass --strict-memory-lowering to opt into failing instead;
    # --allow-memory-lowering remains accepted (a no-op unless
    # --strict-memory-lowering is also set, in which case it suppresses that
    # failure) so nothing that already passes it breaks.
    _mem_leftover_sidecar = synth_json + ".leftover_mem.json"
    if os.path.exists(_mem_leftover_sidecar):
        try:
            with open(_mem_leftover_sidecar) as _mem_leftover_fh:
                _mem_leftover_names = json.load(_mem_leftover_fh)
        except (OSError, ValueError) as exc:
            print("error: could not read memory-lowering sidecar %s: %s" % (_mem_leftover_sidecar, exc))
            sys.exit(1)
        if _mem_leftover_names:
            print("AGAMEMNON WARNING: %d memory cell(s) did NOT map to the ALTA_BRAM9K block RAM "
                  "and were lowered to individual flip-flops + LUT address decoding by memory_map: "
                  "%s -- this can silently balloon LUT/FF usage (a common cause: an "
                  "asynchronous/combinational read port, or a pure read-only ROM with no write port, "
                  "neither of which the block-RAM library's clocked read/write ports can express)."
                  % (len(_mem_leftover_names), ", ".join(_mem_leftover_names)))
            _mem_lowering_strict = (getattr(a, "strict_memory_lowering", False)
                                     or env.get("AGAMEMNON_STRICT_MEMORY_LOWERING"))
            _mem_lowering_allowed = (getattr(a, "allow_memory_lowering", False)
                                      or env.get("AGAMEMNON_ALLOW_MEMORY_LOWERING"))
            if _mem_lowering_strict and not _mem_lowering_allowed:
                print("error: memory cell(s) silently lowered off the ALTA_BRAM9K block RAM path -- "
                      "pass --allow-memory-lowering (or set AGAMEMNON_ALLOW_MEMORY_LOWERING) to "
                      "acknowledge and continue, or fix the source (add `(* ram_style = \"block\" *)` "
                      "or restructure the read to be clocked).")
                sys.exit(1)
    # Physical BEL names are exposed by the C++ uarch database.  Generic
    # nextpnr consumes the PCF through arch.py and does not have those BELs.
    if a.pcf and a.uarch:
        run("pcf-bind", [sys.executable, os.path.join(engine, "pcf_bind_json.py"), synth_json,
                         json.dumps(_pcf, sort_keys=True), data])
    if a.pcf:
        try:
            _output_pcf = _pcf_output_constraints(synth_json, _pcf)
            _hard_output_pins = _typed_hard_output_pins(synth_json, _output_pcf)
            _auto_vendor_out = _qualified_pad_vendor_out(
                _output_pcf, data, _hard_output_pins
            )
        except (OSError, ValueError) as exc:
            print("error: %s" % exc); sys.exit(2)
        if _auto_vendor_out:
            _selected_vendor_out = env.get("AGAMEMNON_VENDOR_OUT_SLICE")
            if _selected_vendor_out and _selected_vendor_out != _auto_vendor_out:
                print("error: output-capable PCF pad composition requires "
                      "AGAMEMNON_VENDOR_OUT_SLICE=%s, but the environment selected %s"
                      % (_auto_vendor_out, _selected_vendor_out))
                sys.exit(2)
            env["AGAMEMNON_VENDOR_OUT_SLICE"] = _auto_vendor_out
            print("[build] qualified output-pad presentation: vendor F/Q slice %s"
                  % _auto_vendor_out)
            try:
                evaluate_policy(engine_options_from(env))
            except ClaimPolicyError as exc:
                print(str(exc))
                print("error: build claim-policy preflight failed after output-pad composition")
                sys.exit(1)
    # Registered own-Q feedback is lowered to the silicon-characterized direct
    # D branch (OMUX[3z+1] -> IMUX[4z+3]); other single cell reads use input D
    # only when that slot is not reserved by self-feedback.
    run("qin", [sys.executable, os.path.join(engine, "qin_pack.py"), synth_json])
    if a.uarch and a.pin:
        try:
            pinned_cell = _pin_uarch_single_slice(synth_json, a.pin)
        except ValueError as exc:
            print("error: %s" % exc)
            sys.exit(2)
        print("[build] pinned %s -> %s" % (pinned_cell, a.pin))
    if qualified_profile:
        # Exact replay is intentionally not a router fallback.  It proves the
        # Qin-packed source has the same primitive parameters and complete
        # producer/consumer graph as the operator-selected qualification
        # hash-registered checkpoint, then transfers that checkpoint's BELs and
        # per-net routes.  Final raw and compressed hashes are mandatory.
        # Any functional or topology change fails before bitgen.
        log = run("exact-route-replay", [
            sys.executable, os.path.join(engine, "route_replay.py"),
            synth_json, qualified_profile["checkpoint_path"], routed_json,
        ])
        for line in log.splitlines():
            if line.startswith("exact route replay verified"):
                print("[build] " + line)
    elif getattr(a, "uarch", False):
        live_portb = _json_has_live_bram_portb(synth_json)
        try:
            live_direct_d = _json_admits_direct_d(
                synth_json, env, getattr(a, "qualified_checkpoint", None)
            )
        except ValueError as exc:
            print("error: %s" % exc)
            print("error: direct-D admission failed before device-database emission")
            sys.exit(1)
        if live_direct_d:
            env["AGAMEMNON_DIRECT_D"] = "1"
            env["AGAMEMNON_DIRECT_D_SITES"] = ";".join(
                _json_direct_d_bels(
                    synth_json, getattr(a, "qualified_checkpoint", None)
                )
            )
        if env.get("AGAMEMNON_DIRECT_D_X14Y11_S8_EXPERIMENT"):
            # WSL imports AGRV2K_* controls explicitly. Keep the public option
            # name in the Python emitters and pass this internal mirror only to
            # the uarch validity gate.
            env["AGRV2K_DIRECT_D_X14Y11_S8_EXPERIMENT"] = "1"
        # ---- agrv2k uarch flow (silicon-proven for multi-bit sequential; see examples/uarch_sequential.md).
        # The device is CONDUCTION-GATED (router can't pick electrically-dead pips) and placement is
        # conduction-aware (pack_condplace). Needs the uarch-built nextpnr-generic: $AGAMEMNON_UARCH_NEXTPNR
        # (a path/command), else `nextpnr-generic` on PATH must itself be the uarch build (built via
        # engine/uarch/agrv2k/build.sh). The gated devdb is auto-emitted+cached on first use.
        udir = os.path.join(engine, "uarch", "agrv2k")
        unpr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR", "nextpnr-generic")
        # A literal Windows executable path may contain spaces. Preserve it as
        # one argv element before applying the non-ASCII nextpnr shim.
        unpr_parts = [unpr] if os.name == "nt" and os.path.isfile(unpr) else unpr.split()
        unpr_parts = stage_windows_executable(unpr_parts)
        npr_runtime = os.environ.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
        npr_env = _build_tool_env(env, oss=oss, runtime=npr_runtime)
        try:
            version = _preflight_nextpnr(unpr_parts, npr_env)
        except RuntimeError as exc:
            print("error: %s" % exc)
            sys.exit(1)
        for line in version.splitlines():
            if "nextpnr" in line.lower():
                print("[build] nextpnr preflight: %s" % line.strip())
                break
        # G5 layer 1 -- capability probe: is this *specific configured* nextpnr known-good for
        # router2 (AG32-Docs/NEXTPNR_ROUTER2_BUG.md)? A --version string cannot answer this (the
        # fix was a local patch to a pinned commit, so git describe is identical either way); see
        # agamemnon/engine/router2_probe.py for the behavioural probe, its caching, and the
        # fail/warn reasoning. Cached per-binary, so this costs nothing on repeat builds.
        probe = _router2_probe.check_router2(unpr_parts, npr_env)
        if probe.verdict == "buggy":
            message = ("nextpnr failed the mandatory router2 reservation capability probe "
                       "(%s) -- see AG32-Docs/NEXTPNR_ROUTER2_BUG.md. This build is refused because "
                       "routing results from this binary are not qualified. Set "
                       "AGAMEMNON_ROUTER2_PROBE_MODE=warn to proceed anyway, or =off to skip this "
                       "check." % probe.detail)
            if npr_env.get("AGAMEMNON_ROUTER2_PROBE_MODE", "enforce").lower() == "warn":
                print("warning: %s" % message)
            else:
                print("error: %s" % message)
                sys.exit(1)
        elif probe.verdict == "inconclusive":
            print("warning: could not confirm this nextpnr is free of the known router2 reservation "
                  "defect (%s); see AG32-Docs/NEXTPNR_ROUTER2_BUG.md. Proceeding -- set "
                  "AGAMEMNON_ROUTER2_PROBE_MODE=off to silence this check." % probe.detail)
        elif probe.verdict == "ok" and not probe.cached:
            print("[build] nextpnr router2 capability probe: ok (%s)" % probe.detail)
        # Strict DBs contain only per-position silicon/vendor-proven edges.  Keep a distinct cache
        # name so an older permissive "conduction" database can never be reused accidentally.
        # The tiered graph is a DIFFERENT graph, so it gets a different cache name
        # as well as a different fingerprint. Sharing "devdb_strict" between the
        # two models would be a silent-wrong-result waiting to happen the first
        # time a fingerprint check was loosened.
        admission = "release-strict" if (research_unsafe or release_strict) else "tiered"
        if research_unsafe:
            default_devdb = "devdb_research_unsafe_pcf" if a.pcf else "devdb_research_unsafe"
            if require_clean_selectors:
                default_devdb += "_clean_selectors"
        elif release_strict:
            default_devdb = "devdb_strict_pcf" if a.pcf else "devdb_strict"
        else:
            env["AGAMEMNON_ROUTING_ADMISSION"] = admission
            default_devdb = "devdb_tiered_pcf" if a.pcf else "devdb_tiered"
        if live_portb:
            default_devdb += "_portb"
        if live_direct_d:
            default_devdb += "_directd"
        if qualified_bram_source:
            default_devdb += "_tmux9source"
        if env.get("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT"):
            default_devdb += "_x15y8s12exp"
        if env.get("AGAMEMNON_DIRECT_D_X14Y11_S8_EXPERIMENT"):
            default_devdb += "_x14y11s8exp"
        custom_devdb = os.environ.get("AGAMEMNON_DEVDB")
        devdb = custom_devdb or os.path.join(udir, default_devdb)
        uarch_devdb = devdb
        emitter = os.path.join(engine, "emit_uarch_db.py")
        arch_source = os.path.join(engine, "arch.py")
        if research_unsafe:
            emit_env = [
                "AGAMEMNON_HW_CARRY=1", "AGAMEMNON_LEDPADS=1",
                "AGAMEMNON_XBAR_FULL=1", "AGAMEMNON_XBAR_CONDUCT=1",
                "AGAMEMNON_SOFT_PREFER=1",
                "AGAMEMNON_RESEARCH_UNSAFE=1",
            ]
            emit_env.append(
                "AGAMEMNON_CLEAN_SEL_GATE=1" if require_clean_selectors
                else "AGAMEMNON_CLEAN_SEL_PREFER=1")
        else:
            emit_env = ["AGAMEMNON_CONDUCTION_GATE=1", "AGAMEMNON_HW_CARRY=1",
                        "AGAMEMNON_LEDPADS=1", "AGAMEMNON_STRICT_GATE=1",
                        "AGAMEMNON_XBAR_CONDUCT=1", "AGAMEMNON_CLEAN_SEL_GATE=1"]
            if admission != "release-strict":
                # Added only when it changes something. release-strict is the
                # registered default, so omitting it there keeps the existing
                # devdb_strict cache fingerprint -- and its contents -- untouched.
                emit_env.append("AGAMEMNON_ROUTING_ADMISSION=%s" % admission)
        if live_portb:
            emit_env.append("AGAMEMNON_BRAM_PORTB_EXIT=1")
        if live_direct_d:
            emit_env.append("AGAMEMNON_DIRECT_D=1")
        if qualified_bram_source:
            # The architecture only needs the presence of the bounded
            # zero-bit OMUX presentation; high/low selection remains a
            # runtime C++/bitgen property of the exact profile.
            emit_env.append("AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE=source")
        if env.get("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT"):
            emit_env.append("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT=1")
        if env.get("AGAMEMNON_DIRECT_D_X14Y11_S8_EXPERIMENT"):
            emit_env.append("AGAMEMNON_DIRECT_D_X14Y11_S8_EXPERIMENT=1")
        if env.get("AGAMEMNON_DUAL_LUT_CONST"):
            emit_env.append("AGAMEMNON_DUAL_LUT_CONST=%s" %
                            env["AGAMEMNON_DUAL_LUT_CONST"])
        if a.pcf:
            emit_env += ["AGAMEMNON_PHYSICAL_IO=1", "AGAMEMNON_PADFEED_TOP=1",
                         "AGAMEMNON_HARDEN_PADFEED=1", "AGAMEMNON_LEFT_PAD_OUT=1"]
            env["AGAMEMNON_LEFT_PAD_OUT"] = "1"
        ignored_cache_env = {"AGAMEMNON_DEVDB", "AGAMEMNON_OSS", "AGAMEMNON_UARCH_NEXTPNR",
                             "AGAMEMNON_UARCH_NEXTPNR_RUNTIME", "AGAMEMNON_BASELINE",
                             "AGAMEMNON_PCF_JSON", "AGAMEMNON_PIN", "AGAMEMNON_PIN_CELLS",
                             "AGAMEMNON_SYSCLK",
                             "AGAMEMNON_HSE", "AGAMEMNON_SRAM_STUB"}
        ignored_cache_env.add("AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE")
        runtime_assets = (
            "clock_reach_silicon_negative.csv",
            "master_conduction.csv", "mcu_ahb32_corridors.csv",
            "mcu_ahb32_addr_corridors.csv", "mcu_logic_consumer_footprints.csv",
            "mcu_slave_ahb_request_control_independent_paths.csv",
            "mcu_slave_ahb_request_payload_paths.csv",
            "mcu_slave_ahb_haddr2_dynamic_paths.csv",
            "mcu_slave_ahb_haddr29_sram_base_paths.csv",
            "mcu_region_witness.csv",
            "soft_ripple_region_witness.csv",
            "pad_oe_L48_left_corridors.csv", "pad_input_L48_left_corridors.csv",
            "bram_tmux9_source_paths.csv",
        )
        emit_context = emit_env + ["%s=%s" % item for item in env.items()
                                   if item[0].startswith("AGAMEMNON_")
                                   and item[0] not in ignored_cache_env]
        # Runtime-only path tables are consumed directly by the C++ packer and
        # do not appear in dev_*.csv. Their content must still invalidate the
        # cached device database; otherwise a newly qualified path can leave a
        # perfectly fingerprinted cache without the table that activates it.
        for runtime_asset in runtime_assets:
            runtime_path = os.path.join(data, runtime_asset)
            if os.path.exists(runtime_path):
                emit_context.append(
                    "%s_SHA256=%s" %
                    (runtime_asset, hashlib.sha256(open(runtime_path, "rb").read()).hexdigest())
                )
        # A blacklist file's PATH is in the context above, but its CONTENT is what
        # shapes the graph. Editing the file in place would otherwise reuse a
        # device database built from the previous cut -- a stale-cache failure that
        # presents as "my ban had no effect".
        _ban_file = env.get("AGAMEMNON_EDGE_BLACKLIST_FILE")
        if _ban_file:
            try:
                emit_context.append("AGAMEMNON_EDGE_BLACKLIST_FILE_SHA256=%s" %
                                    hashlib.sha256(open(_ban_file, "rb").read()).hexdigest())
            except OSError as exc:
                print("error: cannot read AGAMEMNON_EDGE_BLACKLIST_FILE %s (%s)"
                      % (_ban_file, exc))
                sys.exit(1)
        fingerprint = _devdb_fingerprint(arch_source, emitter, data, emit_context)
        manifest = os.path.join(devdb, ".source_sha256")

        def cache_matches():
            if not os.path.exists(os.path.join(devdb, "dev_pips.csv")):
                return False
            if custom_devdb:
                return True
            try:
                return open(manifest, encoding="ascii").read().strip() == fingerprint
            except OSError:
                return False

        cache_ok = cache_matches()
        lock_dir = devdb + ".emit-lock"
        have_lock = False
        if not cache_ok and not custom_devdb:
            deadline = time.monotonic() + 120.0
            while True:
                try:
                    os.mkdir(lock_dir)
                    have_lock = True
                    break
                except FileExistsError:
                    try:
                        if time.time() - os.path.getmtime(lock_dir) > 300:
                            os.rmdir(lock_dir)
                            continue
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for device-database cache lock: %s" % lock_dir)
                    time.sleep(0.1)
            # Another build may have completed the same cache while this one waited.
            cache_ok = cache_matches()
        try:
            if not cache_ok:
                if not custom_devdb and os.path.isdir(devdb):
                    shutil.rmtree(devdb)
                emit_cmd = [sys.executable, emitter, "--arch", arch_source, "--data", data,
                            "--out", devdb]
                for item in emit_env:
                    emit_cmd += ["--env", item]
                run("emit-devdb", emit_cmd)
                # Runtime-only placement/route evidence consumed directly by
                # the C++ packer (not represented by dev_*.csv rows).
                for runtime_asset in runtime_assets:
                    src_asset = os.path.join(data, runtime_asset)
                    if os.path.exists(src_asset):
                        shutil.copy(src_asset, devdb)
                if not custom_devdb:
                    with open(manifest, "w", encoding="ascii") as f:
                        f.write(fingerprint + "\n")
        finally:
            if have_lock:
                try:
                    os.rmdir(lock_dir)
                except OSError:
                    pass
        try:
            _validate_uarch_devdb(devdb)
        except RuntimeError as exc:
            print("error: %s" % exc)
            sys.exit(1)
        env["AGRV2K_CONDPLACE"] = "1"
        env["AGRV2K_BRAM_HARDCONST"] = "1"
        env["AGRV2K_BRAM_PINPACK"] = "1"
        env["AGRV2K_IO_PINPACK"] = "1"
        # Small handshake clusters are no-ops when these nets are absent. They keep common bus/RF
        # return cones on a silicon-proven local crossbar in large sequential designs such as SERV.
        env["AGRV2K_CLUSTER_MEM_ACK"] = "1"
        env["AGRV2K_CLUSTER_RF_READY"] = "1"
        # Seed 4 remains the first regional tie-break ordering because it is
        # qualified across independent large RTL structures.  Routing is not
        # monotonic in that ordering, however: the three-UART example closes
        # with seeds 2 and 7 while seed 4 reaches a resource conflict.  Unless
        # the caller locks one seed explicitly, try those two bounded fallback
        # orderings before changing the netlist with fanout splitting.
        seed_locked = "AGRV2K_CONDPLACE_SEED" in env
        env.setdefault("AGRV2K_CONDPLACE_SEED", "4")
        route_seeds = [env["AGRV2K_CONDPLACE_SEED"]] if seed_locked else ["4", "2", "7"]
        env["AGAMEMNON_LEDPADS"] = "1"
        # Route and pack only selector encodings recovered without conflicting
        # evidence.  This is deliberately fail-closed: an electrically
        # plausible edge is not usable until its independent RMUX/IMUX node
        # block has a clean physical or unanimous tile-relative encoding.
        if not research_unsafe or require_clean_selectors:
            env["AGAMEMNON_CLEAN_SEL_GATE"] = "1"
        npr = unpr_parts + ["--uarch", "agrv2k", "-o", "chipdb=" + devdb,
                            "--json", synth_json, "--write", routed_json, "--router", "router2"]
        # qin/fanout transforms preserve every module in a multi-source JSON.
        # nextpnr cannot infer a unique root once several of those modules own
        # cells, so carry the same explicit top selected for Yosys into every
        # unsplit and fanout-split P&R attempt.
        if top:
            npr += ["--top", top]
        if freq is not None:
            npr += ["--freq", str(freq)]
        if os.path.basename(unpr_parts[0]).lower() in ("wsl", "wsl.exe"):
            npr = _translate_wsl_nextpnr_args(npr)
            _forward_wsl_uarch_environment(env)
        # ROUTE-DRIVEN escalation over BOTH cells/tile (cap) and fanout. Neither knob dominates: a counter
        # routes SPREAD (low cap) while a shift register routes PACKED (high cap co-locates cells on one
        # tile's conducting crossbar, cutting inter-tile hops). And the conducting fanout limit is >2, so
        # splitting nets a design DOESN'T need corrupts it (fanout_split cascades on feedback loops and
        # explodes the netlist). So: PHASE A sweeps cap ascending, UNSPLIT, stopping at the first that
        # routes; PHASE B (only if A fails) adds fanout_split at the largest cap, escalating tighter
        # (16->8->4->--maxfo). fanout_split rewrites synth_json in place, so snapshot & restore each attempt.
        pristine = synth_json + ".prefo"
        shutil.copy(synth_json, pristine)
        heap_first = _uarch_prefers_heap(synth_json)
        attempts = _uarch_attempts(
            a.cap, a.maxfo, split_first=live_portb, heap_first=heap_first)
        if heap_first and not live_portb:
            print("[build] placer: placer_heap first for MCU-boundary/dense design")
        log = None
        routed_but_timing_failed = False
        no_fmax_available = False
        # G10 -- every rung of this ladder is preserved to disk (not just the last), and every
        # rung's classified outcome is kept so a failed ladder can be summarised across attempts
        # instead of reported from whichever attempt the ladder happened to bottom out on. See
        # agamemnon/engine/attempt_ladder.py for why this matters (three honest reproductions of
        # one design previously reported three different failing nets).
        attempts_dir = os.path.join(tmp, "attempts")
        attempt_records = []
        attempt_no = 0
        for attempt, (cap, fo) in enumerate(attempts):
            shutil.copy(pristine, synth_json)                 # always start from the un-split netlist
            if fo > 0:
                folog = run("fanout-split(maxfo=%d)" % fo,
                            [sys.executable, os.path.join(engine, "fanout_split.py"), synth_json, str(fo)])
                # a split that replicated nothing leaves the netlist == an attempt already tried -> skip.
                if "replicated 0 driver copies" in folog:
                    continue
            generic_place = cap == 0
            if generic_place:
                env.pop("AGRV2K_CONDPLACE", None)
                env.pop("AGRV2K_CONDPLACE_CAP", None)
                # Router2 can negotiate analytic-placement fabric inputs and
                # MCU exits jointly, but the placer itself has discrete legal
                # outcomes.  Four bounded nextpnr seeds cover that variance
                # before any netlist-changing fanout split.
                placement_seeds = ["1", "2", "3", "4"]
            else:
                env["AGRV2K_CONDPLACE"] = "1"
                env["AGRV2K_CONDPLACE_CAP"] = str(cap)
                placement_seeds = route_seeds
            for seed_index, seed in enumerate(placement_seeds):
                if not generic_place:
                    env["AGRV2K_CONDPLACE_SEED"] = seed
                attempt_npr = npr + (["--placer", "heap", "--seed", seed]
                                     if generic_place else [])
                # Cap and seed are chosen inside the attempt loop, after the base
                # WSLENV forwarding list was assembled. Refresh it so WSL imports
                # the controls that the Windows-side log advertises.
                if os.path.basename(unpr_parts[0]).lower() in ("wsl", "wsl.exe"):
                    _forward_wsl_uarch_environment(env)
                try:
                    special_routes.validate_routed_json(
                        synth_json, "pre-nextpnr", chipdb_root=data)
                except special_routes.SpecialRouteError as exc:
                    print("error: typed special-route pre-nextpnr validation failed: %s" % exc)
                    sys.exit(1)
                # Optional timeout forensics: snapshot the exact post-qin,
                # post-fanout JSON *before* starting nextpnr.  If the caller's
                # harness kills this CLI mid-route, tempfile cleanup otherwise
                # destroys the only input capable of reproducing that rung.
                # This is evidence-only and does not alter the command or env.
                trace_dir = env.get("AGAMEMNON_ATTEMPT_TRACE_DIR")
                if trace_dir:
                    os.makedirs(trace_dir, exist_ok=True)
                    trace_stem = "attempt_%02d_cap%d_seed%s_fo%d" % (
                        attempt_no + 1, cap, seed, fo)
                    shutil.copyfile(synth_json, os.path.join(trace_dir, trace_stem + ".json"))
                    with open(os.path.join(trace_dir, trace_stem + ".meta.json"), "w",
                              encoding="utf-8") as trace_meta:
                        json.dump({"cap": cap, "seed": seed, "fanout": fo,
                                   "placement": "placer_heap" if generic_place else "conduction",
                                   "devdb": os.path.abspath(devdb), "command": attempt_npr},
                                  trace_meta, indent=2, sort_keys=True)
                        trace_meta.write("\n")
                placement_label = ("placer_heap, seed=%s" % seed if generic_place
                                   else "cap=%d, seed=%s" % (cap, seed))
                rlog = run("place&route (%s, fanout %s)" %
                           (placement_label, "off" if fo == 0 else "maxfo=%d" % fo),
                           attempt_npr, check=False,
                           child_env=_build_tool_env(env, oss=oss, runtime=npr_runtime))
                attempt_no += 1
                # Classify this attempt's outcome ONCE and reuse it for both disk logging and the
                # branches below -- same conditions, same order, as before this change.
                if _nextpnr_aborted(rlog, run.returncode):
                    outcome = _attempt_ladder.ABORTED
                elif _nonretryable_uarch_failure(rlog):
                    outcome = _attempt_ladder.NONRETRYABLE
                elif _route_and_timing_succeeded(rlog, run.returncode, require_fmax=require_timing_path):
                    outcome = _attempt_ladder.SUCCESS
                elif "Routing complete" in rlog:
                    outcome = _attempt_ladder.TIMING_FAILED
                else:
                    outcome = _attempt_ladder.NOT_ROUTED
                record = _attempt_ladder.AttemptRecord(attempt_no, cap, seed, fo, outcome, rlog)
                attempt_records.append(record)
                _attempt_ladder.write_attempt_log(attempts_dir, record)
                if outcome == _attempt_ladder.ABORTED:
                    print(rlog[-4000:])
                    print("error: nextpnr aborted; placement/routing retries are unsafe for this failure")
                    sys.exit(1)
                if outcome == _attempt_ladder.NONRETRYABLE:
                    print(rlog[-4000:])
                    print("error: nextpnr rejected a deterministic hardware constraint; "
                          "placement/routing retries cannot make this image safe")
                    sys.exit(1)
                if outcome == _attempt_ladder.SUCCESS:
                    try:
                        special_routes.validate_routed_json(
                            routed_json, "post-nextpnr", chipdb_root=data)
                    except special_routes.SpecialRouteError as exc:
                        print("error: typed special-route post-nextpnr validation failed: %s" % exc)
                        sys.exit(1)
                    log = rlog
                    break
                if outcome == _attempt_ladder.TIMING_FAILED:
                    routed_but_timing_failed = True
                    no_fmax_available = no_fmax_available or "No Fmax available" in rlog
                    # Placement/fanout retries cannot create a sequential timing
                    # endpoint in a design that has none.
                    if no_fmax_available and require_timing_path:
                        break
                if seed_index + 1 < len(placement_seeds):
                    print("[build]   did not route; retrying deterministic seed")
            if log is not None or (no_fmax_available and require_timing_path):
                break
            if attempt + 1 < len(attempts):
                print("[build]   did not route; escalating")
        os.remove(pristine)
        if log is None:
            # Dedicated carry is an optimization, not a reason for a default
            # build to lose breadth.  A physically qualified chain can still
            # strand its terminal fanout on the strict graph (large lowered
            # ROMs expose this).  After exhausting the complete route ladder,
            # resynthesize once through Yosys's ordinary LUT carry path.  An
            # explicit --hard-carry request remains fail-closed and qualified
            # checkpoint builds remain byte-exact rather than silently
            # changing their synthesis contract.
            if _default_carry_fallback_allowed(a):
                print("[build] dedicated-carry route ladder exhausted; "
                      "resynthesizing once with LUT carry fallback")
                shutil.rmtree(tmp, ignore_errors=True)
                a.no_hard_carry = True
                return cmd_build(a)
            # G10 -- report across every attempt, not just the last: which failure signature
            # recurred (a far stronger signal than whichever rung the ladder ended on), and run
            # the G5 self-check against that recurring attempt rather than an arbitrary final one.
            ladder_summary = _attempt_ladder.summarize_ladder(attempt_records)
            representative = ladder_summary.representative if ladder_summary else None
            report_log = representative.log if representative is not None else rlog
            if report_log:
                print(report_log[-4000:])
                # G5 layer 2 -- the durable self-check. Do not assume a "Failed to route arc"
                # report means the design or device data is at fault: independently search the
                # exact device graph this build loaded for a legal directed path between the
                # failing arc's source and sink, and say plainly which side that implicates. See
                # agamemnon/engine/router2_diagnostics.py and AG32-Docs/NEXTPNR_ROUTER2_BUG.md.
                diagnostic = _router2_diag.diagnose_routing_failure(
                    report_log, _router2_diag.uarch_pip_edges_provider(devdb),
                    graph_source="%s (this build's device database)" % devdb,
                )
                if diagnostic:
                    print(diagnostic)
            summary_text = _attempt_ladder.format_ladder_summary(ladder_summary, attempts_dir=attempts_dir)
            if summary_text:
                print(summary_text)
            if no_fmax_available and require_timing_path:
                print("error: frequency target requested, but nextpnr found no interior clocked timing path")
                sys.exit(1)
            if routed_but_timing_failed and freq is not None:
                print("error: routing completed, but the %.3f MHz timing target was not met" % freq)
                sys.exit(1)
            print("error: routing did not complete after cap/fanout escalation (the design exceeds the "
                  "conducting graph — see examples/uarch_sequential.md limits)"); sys.exit(1)
    else:
        # Router1's path search fails on otherwise legal physical-I/O and MCU-exit routes once the
        # characterized multi-nanosecond wire delays are present. Router2 finds those routes and then
        # invokes router1's legality checker before accepting them, preserving the same final-route
        # invariant while allowing the real timing model to remain enabled.
        npr = ["nextpnr-generic", "--pre-pack", os.path.join(engine, "arch.py"),
               "--router", "router2"]
        # DEFAULT placement = conduction-aware auto-placer (place_auto): detects the design's I/O
        # (MCU_DOUT/MCU_DIN/MCU) + places logic on silicon-conducting tiles/links automatically -- no
        # per-design hook or env tuning. --leds keeps the LED-pad placer; --pin-hook overrides both.
        hook = a.pin_hook or ("pin_leds.py" if a.leds else "place_auto.py")
        if hook == "place_auto.py":
            # conduction-aware routing preference the auto-placer relies on (prefer proven-conducting pips).
            env.setdefault("AGAMEMNON_SOFT_PREFER", "1")
            env.setdefault("AGAMEMNON_SOFT_PENALTY", "1.5")
            env.setdefault("AGAMEMNON_EXIT_TILE", "14,12")
        npr += ["--pre-place", os.path.join(engine, hook)]
        npr += ["--json", synth_json, "--write", routed_json]
        if freq is not None:
            npr += ["--freq", str(freq)]
        try:
            version = _preflight_nextpnr(npr[:1], oss_env)
        except RuntimeError as exc:
            print("error: %s" % exc)
            sys.exit(1)
        for line in version.splitlines():
            if "nextpnr" in line.lower():
                print("[build] nextpnr preflight: %s" % line.strip())
                break
        legacy_route_env = _build_tool_env(env, oss=oss, use_oss=bool(oss))
        # check=False: a router2 "Failed to route arc" is a fatal nextpnr exit (non-zero return),
        # which `run()`'s default check=True would already have reported (and exited on) before
        # the G5 self-check below ever ran. Handle failure explicitly here instead, same as the
        # uarch flow's escalation loop already does.
        try:
            special_routes.validate_routed_json(
                synth_json, "pre-nextpnr", chipdb_root=data)
        except special_routes.SpecialRouteError as exc:
            print("error: typed special-route pre-nextpnr validation failed: %s" % exc)
            sys.exit(1)
        log = run("place&route", npr, check=False, child_env=legacy_route_env)
        if run.returncode != 0 or "Routing complete" not in log:
            print(log[-1500:])
            # G5 layer 2, legacy flow: this arch has no on-disk pip snapshot to read (unlike the
            # uarch flow's dev_pips.csv), so reproduce the same graph the way nextpnr itself built
            # it -- by calling archgen.build() again with the exact env this attempt used. See
            # agamemnon/engine/router2_diagnostics.py's legacy_pip_edges_provider docstring.
            diagnostic = _router2_diag.diagnose_routing_failure(
                log, _router2_diag.legacy_pip_edges_provider(
                    os.path.join(engine, "arch.py"), data, legacy_route_env),
                graph_source="a fresh archgen.build() rebuild of this build's device graph",
            )
            if diagnostic:
                print(diagnostic)
            print("error: routing did not complete"); sys.exit(1)
        try:
            special_routes.validate_routed_json(
                routed_json, "post-nextpnr", chipdb_root=data)
        except special_routes.SpecialRouteError as exc:
            print("error: typed special-route post-nextpnr validation failed: %s" % exc)
            sys.exit(1)
        if require_timing_path and "No Fmax available" in log:
            print("error: frequency target requested, but nextpnr found no interior clocked timing path")
            sys.exit(1)
    if freq is not None:
        for line in log.splitlines():
            if ("Max frequency" in line or "MHz (PASS" in line or "MHz (FAIL" in line
                    or "No Fmax available" in line):
                print("[timing] " + line.strip())
    if qualified_bram_source:
        try:
            QBW.canonicalize_routed_file(routed_json, qualified_bram_source["id"])
        except (OSError, ValueError) as exc:
            print("error: qualified BRAM source route canonicalization failed: %s" % exc)
            sys.exit(1)
        print("[build] qualified BRAM source profile %s: applied measured route trees" %
              qualified_bram_source["id"])
    # Canonicalization mutates the routed checkpoint after nextpnr's result was
    # first audited.  Reconstruct typed ownership from the exact bytes that
    # confidence, portable-artifact output, or bitgen will consume.
    try:
        final_snapshot = special_routes.load_validated_routed_json(
            routed_json, "pre-emission", chipdb_root=data)
    except special_routes.SpecialRouteError as exc:
        print("error: typed special-route pre-emission validation failed: %s" % exc)
        sys.exit(1)
    if getattr(a, "internal_ports", False):
        _write_portable_routed_json(
            routed_json, a.write_routed, document=final_snapshot.document)
        _write_confidence_manifest(
            routed_json=routed_json,
            devdb=uarch_devdb,
            output=a.write_routed,
            sources=sources,
            device=env.get("AGAMEMNON_DEVICE", "AGRV2KL48"),
            admission=env.get("AGAMEMNON_ROUTING_ADMISSION"),
            routed_sha256=final_snapshot.sha256,
            routed_document=final_snapshot.document,
        )
        print("routed internal overlay -> %s" % a.write_routed)
        return
    # bitgen via the engine's to_bin (writes the 99944-byte uncompressed .bin + <out>.comp)
    try:
        bitgen_input = _stage_validated_routed_json(
            final_snapshot, tmp, base + ".validated-routed.json")
    except OSError as exc:
        print("error: cannot stage validated routed snapshot: %s" % exc)
        sys.exit(1)
    bitgen_env = dict(env)
    bitgen_env["AGAMEMNON_VALIDATED_ROUTED_SHA256"] = final_snapshot.sha256
    log = run(
        "bitgen",
        [sys.executable, os.path.join(engine, "to_bin.py"), bitgen_input, out],
        child_env=bitgen_env,
    )
    for line in log.splitlines():
        # The warning/refusal lines are included deliberately. bitgen's
        # selector-injectivity guard withdraws an ambiguous codeword and says so
        # on a build that then SUCCEEDS, and run() only surfaces captured output
        # when the step fails -- so without this the notice existed and nobody
        # would ever see it, which is the same silent-degradation shape the
        # memory-lowering sidecar above exists to prevent.
        if ("unmapped" in line or "registered slices" in line or "IO LED" in line
                or "wrote" in line or "AGAMEMNON WARNING" in line
                or "refusing ambiguous" in line):
            print("        " + line.strip())
    exact_output_profile = qualified_profile or qualified_bram_source
    if exact_output_profile:
        produced = {
            out: exact_output_profile["bitstream_sha256"],
            out + ".comp": exact_output_profile["compressed_sha256"],
        }
        mismatches = [(path, _sha256_file(path), expected)
                      for path, expected in produced.items()
                      if _sha256_file(path) != expected]
        if mismatches:
            for path in produced:
                try:
                    os.remove(path)
                except OSError:
                    pass
            print("error: qualified build output hash mismatch")
            for path, actual, expected in mismatches:
                print("  %s: got %s expected %s" % (path, actual, expected))
            sys.exit(1)
        print("[build] qualified %s profile %s: exact raw/compressed hashes verified" %
              ("BRAM source" if qualified_bram_source else "route",
               exact_output_profile["id"]))
    _write_confidence_manifest(
        routed_json=routed_json,
        devdb=uarch_devdb,
        output=out,
        sources=sources,
        device=env.get("AGAMEMNON_DEVICE", "AGRV2KL48"),
        admission=env.get("AGAMEMNON_ROUTING_ADMISSION"),
        routed_sha256=final_snapshot.sha256,
        routed_document=final_snapshot.document,
    )
    print("built %s -> %s" % (", ".join(sources), out))
    if getattr(a, "write_routed", None):
        _write_validated_routed_copy(final_snapshot, a.write_routed)
        print("routed netlist -> %s" % a.write_routed)
    if getattr(a, "verify", False):
        # hardware-free behavioural check: cycle-sim the ACTUAL routed netlist and report the read-values
        # the design will produce on silicon over AHB 0x60000000, plus the MCU_DOUT bind soundness.
        from .engine import verify_netlist as V
        print("[build] verify:")
        if not V.summary(
                routed_json, cycles=a.verify_cycles,
                document=final_snapshot.document):
            print("error: MCU_DOUT readout bind is SCRAMBLED (h<k> not mapped to AHB bit k)"); sys.exit(1)
    if project is not None:
        mcu_output = PJ.build_mcu(project)
        PJ.write_flash_plan(project, mcu_output=mcu_output, fabric_output=out)


def cmd_transport_probe(a):
    if a.transport == "dap":
        return P.cmd_probe(a)
    if a.transport == "uart":
        return U.cmd_uart_probe(a)
    return USB.cmd_usb_probe(a)


def cmd_transport_backup(a):
    if a.transport == "dap":
        return P.cmd_backup(a)
    if a.transport == "uart":
        return U.cmd_uart_backup(a)
    return USB.cmd_usb_backup(a)


def cmd_transport_flash(a):
    # Every transport erases 4-KiB sectors before writing, so a full-flash backup
    # is the only recovery path -- require it uniformly (DAP included), not just
    # for UART/USB.
    if not a.backup:
        print("refusing: flash writes require a complete --backup path (erases are destructive)")
        raise SystemExit(2)
    if a.transport == "dap":
        return P.cmd_flash(a)
    if a.transport == "uart":
        return U.cmd_uart_flash(a)
    return USB.cmd_usb_flash(a)


def cmd_transport_go(a):
    if a.transport != "usb":
        print("error: GO is currently qualified only for the flash-resident USB uploader")
        raise SystemExit(2)
    return USB.cmd_usb_go(a)


def cmd_manifest(a):
    data = engine_manifest(a.scope)
    text = json.dumps(data, indent=2, sort_keys=True)
    if a.output:
        with open(a.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.write("\n")
    else:
        print(text)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agamemnon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="diagnose toolchain, transports, ports, probes, and connected AG32")
    doctor.add_argument("--json", action="store_true", help="machine-readable report")
    doctor.add_argument("--no-hardware", action="store_true", help="check host tools and enumeration without probing targets")
    doctor.add_argument("--probe-dap", action="store_true", help="probe DAP even when USB already identified the target (may reset/halt it briefly)")
    doctor.add_argument("--uart-port", help="also reset/probe the mask-ROM target through this Pico bridge")
    doctor.set_defaults(fn=D.cmd_doctor)

    manifest = sub.add_parser(
        "manifest",
        help="emit the registered engine options and constants as stable JSON",
    )
    manifest.add_argument(
        "--scope",
        choices=["both", "arch", "bitgen"],
        default="both",
        help="limit options to one engine half (constants are always included)",
    )
    manifest.add_argument("-o", "--output", help="write JSON here instead of stdout")
    manifest.set_defaults(fn=cmd_manifest)

    qualify = sub.add_parser(
        "qualify",
        help="create a read-only host/support/artifact report for qualification review",
    )
    qualify.add_argument(
        "--artifact", action="append", default=[],
        help="file to hash into the report (repeatable; file is never modified)",
    )
    qualify.add_argument("--notes", help="operator, fixture, wiring, or observation notes")
    qualify.add_argument("-o", "--output", help="write JSON here instead of stdout")
    qualify.set_defaults(fn=Q.cmd_qualify)

    install_openocd = sub.add_parser(
        "install-openocd", help="download, verify, and activate the qualified AG32 OpenOCD"
    )
    install_openocd.add_argument("--version", default=TI.DEFAULT_VERSION)
    install_openocd.add_argument("--prefix", help="installation directory (default ~/.agamemnon)")
    install_openocd.add_argument("--base-url", help="release directory override for mirrors/testing")
    install_openocd.set_defaults(fn=TI.cmd_install_openocd)

    new = sub.add_parser("new", help="create an AG32 project from a maintained template")
    new.add_argument("name", help="new project directory")
    new.add_argument("--board", default="ag32vf303-l48", choices=["ag32vf303-l48"])
    # Default to the fabric-free MCU-only starter: it builds with just RISC-V
    # GCC and needs no Yosys/nextpnr. Exact fabric profiles are separately
    # hash-bound; unsupported generic MCU/direct-D routes remain fail-closed.
    new.add_argument("--template", default="mcu-blink", choices=PJ.TEMPLATE_NAMES)
    new.set_defaults(fn=PJ.cmd_new)

    # ---- FPGA fabric ----
    b = sub.add_parser("build", help="Verilog -> synth -> place&route -> .bin (open flow)")
    b.add_argument("input", nargs="?", help="Verilog source (.v); omit inside a directory with agamemnon.toml")
    b.add_argument("--source", dest="sources", action="append", default=[], help="additional Verilog source (repeatable)")
    b.add_argument("--top", help="top-level Verilog module for a multi-source build")
    b.add_argument("--project", help="project manifest or directory (default ./agamemnon.toml)")
    b.add_argument("-o", "--output", help="output .bin (default <name>.bin)")
    b.add_argument("--leds", action="store_true", help="expose the (1,4) LED output pads + pin them")
    b.add_argument("--mcu", action="store_true", help="enable the MCU-edge (din/dout) interface")
    b.add_argument("--true-topo", action="store_true", help="route on harvested real edges only")
    b.add_argument("--no-intra-rmux", action="store_true", help="drop intra-tile RMUX hops (avoid un-encodable edges)")
    b.add_argument("--pin", help="pin the single GENERIC_SLICE to this bel, e.g. X10Y4_SLICE0")
    b.add_argument("--pin-hook", help="custom --pre-place hook filename in the engine dir")
    b.add_argument("--baseline", help="alternate tile-grid canvas; the preamble is always regenerated")
    b.add_argument("--pcf", help="package-pin constraints: `set_io <port> PIN_<n>` (active device map)")
    b.add_argument("--device", choices=list(_device.PACKAGES),
                   help="AGRV2K package/device (default AGRV2KL48, or AGAMEMNON_DEVICE); "
                        "release-strict admits any package for a pad-free, fabric-logic-only "
                        "build, but a physical/electrical surface (e.g. --pcf) stays qualified "
                        "on AGRV2KL48 only")
    b.add_argument("--part", choices=list(_family.PART_NAMES),
                   help="AG32 family part number (default AG32VF303CCT6, or AGAMEMNON_PART); "
                        "selects flash/PSRAM/ADC-DAC surround metadata and must name a package "
                        "consistent with --device")
    b.add_argument("--uarch", action="store_true",
                   help="use the supported agrv2k nextpnr release flow with the filtered device graph "
                        "and regional placer; requires $AGAMEMNON_UARCH_NEXTPNR")
    b.add_argument(
        "--research-unsafe", action="store_true",
        help="opt into recovered, vendor-derived, predicted, and conflicted chip knowledge; "
             "not release-qualified, always writes a provenance sidecar",
    )
    b.add_argument(
        "--require-clean-selectors", action="store_true",
        help="[--uarch] forbid every routed selector without a conflict-free physical "
             "or unanimous relative encoding; useful with --research-unsafe when an "
             "experimental primitive is required but predicted routing is not",
    )
    b.add_argument(
        "--release-strict", action="store_true",
        help="[--uarch] refuse every routing edge without conduction evidence at its exact "
             "position, exactly as builds behaved before tiered admission. The default "
             "additionally admits edges whose selector codeword is certain and reports each one "
             "it used in <output>.confidence.json; see docs/ROUTING_ADMISSION.md",
    )
    b.add_argument("--cap", type=int, default=5,
                   help="[--uarch] cells/tile hint used by the placer and split-net retry sweep "
                        "(default 5)")
    b.add_argument("--maxfo", type=int, default=2,
                   help="[--uarch] tightest fanout floor for the route-driven escalation (tries unsplit "
                        "first across the cap sweep, then splits progressively down to this if routing fails)")
    b.add_argument("--compact-maxd", type=int, metavar="TILES",
                   help="[--uarch, experimental] restrict regional placement to this Manhattan "
                        "radius around its root; no default until corpus A/B validation")
    carry = b.add_mutually_exclusive_group()
    carry.add_argument("--hard-carry", action="store_true",
                       help="[--uarch] compatibility spelling for the default per-chain dedicated-carry allocation")
    carry.add_argument("--no-hard-carry", action="store_true",
                       help="[--uarch] force all arithmetic through the ordinary LUT path")
    b.add_argument("--qualified-checkpoint", metavar="PROFILE",
                   help="[--uarch] fail-closed exact BEL/route replay from a registered "
                        "qualification profile; source, checkpoint, clocks and output hashes "
                        "must all match")
    b.add_argument("--qualified-bram-write", metavar="PROFILE",
                   help="[--uarch] fresh source-to-route build of one bounded, hash-bound "
                        "X13Y4 x18 TMUX09 write profile; no routed checkpoint is consumed")
    b.add_argument("--write-routed", help="retain the final placed+routed nextpnr JSON at this path")
    b.add_argument("--internal-ports", action="store_true",
                   help="leave top-level ports as internal netlist endpoints (overlay construction only)")
    b.add_argument(
        "--allow-memory-lowering", action="store_true",
        help="acknowledge a memory cell that missed the ALTA_BRAM9K block-RAM mapping and was "
             "silently lowered to flip-flops + LUT address decoding; a no-op unless "
             "--strict-memory-lowering is also set, in which case it suppresses that failure "
             "(default: warn only, see the AGAMEMNON WARNING; AGAMEMNON_ALLOW_MEMORY_LOWERING is "
             "equivalent)",
    )
    b.add_argument(
        "--strict-memory-lowering", action="store_true",
        help="fail the build when a memory cell missed the ALTA_BRAM9K block-RAM mapping and was "
             "silently lowered to flip-flops + LUT address decoding (default: warn only via the "
             "AGAMEMNON WARNING; pass --allow-memory-lowering to acknowledge and continue anyway; "
             "AGAMEMNON_STRICT_MEMORY_LOWERING is equivalent)",
    )
    b.add_argument(
        "--freq", type=float,
        help="qualified fabric frequency in MHz; set the emitted PLL and fail if timing does not close "
             "(default 10; AGAMEMNON_SYSCLK overrides the default)",
    )
    b.add_argument("--verify", action="store_true",
                   help="after building, cycle-sim the routed netlist and print the AHB read-values it will "
                        "produce + the MCU_DOUT bind check (hardware-free)")
    b.add_argument("--verify-cycles", type=int, default=96, help="cycles to simulate for --verify")
    b.set_defaults(fn=cmd_build)

    pk = sub.add_parser("pack", help="routed nextpnr JSON -> flashable .bin (uncompressed + .comp)")
    pk.add_argument("input", help="routed nextpnr 'generic' --write JSON")
    pk.add_argument("output", help="output .bin (99944-byte uncompressed; .comp written alongside)")
    pk.add_argument("--baseline", help="alternate tile-grid canvas; the preamble is always regenerated")
    pk.add_argument("--qualified-checkpoint", metavar="PROFILE",
                    help="fail-closed pack of one packaged, hash-bound retained checkpoint")
    pk.add_argument(
        "--research-unsafe", action="store_true",
        help="pack with recovered/predicted selector sources and write a provenance sidecar",
    )
    pk.add_argument(
        "--require-clean-selectors", action="store_true",
        help="require exact conflict-free selector encodings while directly packing the routed checkpoint",
    )
    pk.set_defaults(fn=cmd_pack)
    so = sub.add_parser(
        "status-overlay",
        help="compose one routed pure-fabric status_set net into the qualified public32 core",
    )
    so.add_argument("input", help="routed overlay JSON from build --internal-ports")
    so.add_argument("output", help="composed routed JSON; pass this to `agamemnon pack`")
    so.add_argument(
        "--devdb",
        help="strict uarch device database override (default bundled hash-checked snapshot)",
    )
    so.set_defaults(fn=cmd_status_overlay)
    up = sub.add_parser("unpack", help=".bin -> 99936-byte raw fabric config image")
    up.add_argument("input"); up.add_argument("-o", "--output", required=True); up.set_defaults(fn=cmd_unpack)
    d = sub.add_parser("decode"); d.add_argument("input"); d.add_argument("-o", "--output", required=True); d.set_defaults(fn=cmd_decode)
    e = sub.add_parser("encode"); e.add_argument("input"); e.add_argument("-o", "--output", required=True); e.set_defaults(fn=cmd_encode)
    ta = sub.add_parser("to-agasc", help=".bin -> lossless named per-tile .agasc ASCII")
    ta.add_argument("input"); ta.add_argument("-o", "--output", required=True); ta.set_defaults(fn=cmd_to_agasc)
    fa = sub.add_parser("from-agasc", help=".agasc ASCII -> CRC-correct flashable .bin")
    fa.add_argument("input"); fa.add_argument("-o", "--output", required=True)
    fa.add_argument("--uncompressed", action="store_true", help="write header + 99936 raw bytes instead of LZW")
    fa.set_defaults(fn=cmd_from_agasc)
    ex = sub.add_parser("explain", help="describe named features and residual bits in a fabric image")
    ex.add_argument("input")
    ex.add_argument("--tile", help="restrict named features to one X,Y tile")
    ex.add_argument("--raw", action="store_true", help="list asserted bytes not covered by named features")
    ex.add_argument("--json", action="store_true", help="emit stable machine-readable JSON")
    ex.add_argument("-o", "--output")
    ex.set_defaults(fn=cmd_explain)
    df = sub.add_parser("diff", help="compare two images by semantic feature and unmapped byte")
    df.add_argument("old")
    df.add_argument("new")
    df.add_argument("--crc", action="store_true", help="include stored CRC bytes in raw changes")
    df.add_argument("--json", action="store_true", help="emit stable machine-readable JSON")
    df.add_argument("-o", "--output")
    df.set_defaults(fn=cmd_diff)
    el = sub.add_parser("edit-lut"); el.add_argument("input"); el.add_argument("--le", required=True, help="x,y,z"); el.add_argument("--init", required=True, help="16-bit truth table, e.g. 0x96e9"); el.add_argument("-o", "--output", required=True); el.set_defaults(fn=cmd_edit_lut)
    vf = sub.add_parser("verify", help="cycle-sim a routed nextpnr JSON offline: report the AHB read-values "
                                       "it produces (+ optionally check a silicon-observed value set)")
    vf.add_argument("input", help="routed nextpnr 'generic' --write JSON")
    vf.add_argument("--observed", help="comma-separated silicon-observed read values to check (SOUND/COVER)")
    vf.add_argument("--cycles", type=int, default=96, help="cycles to simulate")
    vf.set_defaults(fn=cmd_verify)

    # ---- chip (SWD; the open programmer, agamemnon/program.py) ----
    def transport(parser, default="dap"):
        parser.add_argument("--transport", choices=["dap", "uart", "usb"], default=default)
        parser.add_argument("--port", help="serial port for UART Pico bridge or USB CDC uploader")

    pr = sub.add_parser("probe", help="identify AG32 over DAP, mask-ROM UART, or USB CDC")
    transport(pr)
    pr.set_defaults(fn=cmd_transport_probe)
    sr = sub.add_parser("sram", help="SRAM-inject a fabric image + firmware and run it (volatile)")
    sr.add_argument("firmware", help="RISC-V .bin loaded at 0x20000000 and run")
    sr.add_argument("-b", "--fabric", help="uncompressed fabric .bin loaded at 0x20002000")
    sr.add_argument("-w", "--words", type=int, default=10, help="result words to read from 0x20001000")
    sr.add_argument("--sleep", type=int, default=500, help="ms to run before halting")
    sr.set_defaults(fn=P.cmd_sram)
    rs = sub.add_parser(
        "fcb-restream",
        help="plan one-firmware/many-image SRAM restream (use --execute-sram to run)",
    )
    rs.add_argument("firmware", help="fcb_restream_probe.bin loaded once at 0x20000000")
    rs.add_argument("images", nargs="+", help="exact 99,944-byte uncompressed fabric images")
    rs.add_argument("--sleep", type=int, default=500, help="ms allowed per FCB request")
    rs.add_argument("--execute-sram", action="store_true",
                    help="execute the volatile DAP path; never writes flash")
    rs.set_defaults(fn=FCBR.cmd_restream)
    hc = sub.add_parser(
        "hil-campaign",
        help="validate and plan a hash-bound control/candidate HIL work list",
    )
    hc.add_argument("worklist", help="campaign work-list JSON")
    hc.add_argument("--root", help="artifact root (default: work-list directory)")
    hc.add_argument("--require-ready", action="store_true",
                    help="refuse if any denominator job is not executable")
    hc.add_argument("--execute-job", metavar="JOB_ID",
                    help="run one READY SRAM-restream job on the attached target")
    hc.add_argument("--sleep", type=int, default=500,
                    help="ms allowed for each configure-and-observe step")
    hc.set_defaults(fn=HILC.cmd_campaign)
    bk = sub.add_parser("backup", help="dump the whole 256 KB flash over DAP, UART, or USB")
    bk.add_argument("output")
    transport(bk)
    bk.set_defaults(fn=cmd_transport_backup)
    fl = sub.add_parser("flash", help="erase+program a binary to flash at --addr (open flasher, no agrv)")
    fl.add_argument("image", help="binary to write")
    fl.add_argument("--addr", required=True, help="flash address, e.g. 0x80008100")
    fl.add_argument("--backup", help="dump full flash here before writing (required; erases are destructive)")
    transport(fl)
    fl.set_defaults(fn=cmd_transport_flash)
    go = sub.add_parser("go", help="launch an address through the flash-resident USB uploader")
    go.add_argument("addr", help="application entry address, e.g. 0x80010000")
    transport(go, default="usb")
    go.set_defaults(fn=cmd_transport_go)
    im = sub.add_parser("image", help="assemble (+ optionally flash) a combined flash-boot image")
    im.add_argument("-b", "--fabric", required=True, help="uncompressed fabric .bin")
    im.add_argument("-m", "--mcu", help="MCU firmware .bin (-> 0x80000000)")
    im.add_argument("--logic-addr", help="fabric flash address, 4KB-aligned (default 0x80010000)")
    im.add_argument("--plan-json", help="write a portable hash-bound boot-plan manifest")
    im.add_argument("--flash", action="store_true", help="actually write it (default: print plan only)")
    im.add_argument("--backup", help="dump full flash here (required with --flash)")
    im.add_argument("--option-backup",
                    help="dump all 128 option bytes here (required with --write-options)")
    im.add_argument("--write-options", action="store_true",
                    help="also write the option config-pointer (UNVERIFIED; requires both backups)")
    im.set_defaults(fn=P.cmd_image)

    # ---- chip (mask-ROM UART0 through pico/ag32_uart_programmer) ----
    def uart_port(parser):
        parser.add_argument("--port", help="Pico USB serial port (auto-detected if unique)")

    upr = sub.add_parser("uart-probe", help="identify AG32 through the Pico-controlled UART boot ROM")
    uart_port(upr)
    upr.set_defaults(fn=U.cmd_uart_probe)
    ubk = sub.add_parser("uart-backup", help="dump all 256 KiB of main flash through UART0")
    ubk.add_argument("output")
    uart_port(ubk)
    ubk.set_defaults(fn=U.cmd_uart_backup)
    ufl = sub.add_parser("uart-flash", help="backup, sector-preserve, program, verify, and reset via UART0")
    ufl.add_argument("image", help="binary to write")
    ufl.add_argument("--addr", required=True, help="main-flash address, e.g. 0x80000000")
    ufl.add_argument("--backup", required=True, help="mandatory full 256-KiB pre-write backup path")
    uart_port(ufl)
    ufl.set_defaults(fn=U.cmd_uart_flash)
    urs = sub.add_parser("uart-reset", help="drive BOOT0 low and reset AG32 into main flash")
    uart_port(urs)
    urs.set_defaults(fn=U.cmd_uart_reset)

    run = sub.add_parser("run", help="run the current project without manually naming artifacts")
    run.add_argument("--project", help="project manifest or directory")
    run.add_argument("--transport", choices=["dap", "usb", "uart"], default="dap")
    run.add_argument("--port")
    run.add_argument("--flash", action="store_true", help="program the MCU image before USB GO")
    run.add_argument("--backup", help="mandatory full-flash backup for --flash")
    run.add_argument("--words", type=int, default=4)
    run.add_argument("--sleep", type=int, default=500)
    run.set_defaults(fn=PJ.cmd_run)

    monitor = sub.add_parser("monitor", help="open a serial terminal")
    monitor.add_argument("--port")
    monitor.add_argument("--baud", type=int, default=115200)
    monitor.set_defaults(fn=PJ.cmd_monitor)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (P.DapProgrammingError, U.UartProgrammingError, FileNotFoundError, ValueError,
            subprocess.CalledProcessError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
