#!/usr/bin/env python3
"""AG32 / AGRV2K programmer — the hardware half of the `agamemnon` CLI. The flash protocol is open
and does not use the vendor `agrv` OpenOCD flash driver. The compatible OpenOCD transport-binary
requirement is documented explicitly below.

Commands (wired up in cli.py): probe / sram / backup / flash / image.
  probe   read DEVICE_ID over SWD (read-only sanity check)
  sram    SRAM-inject a fabric bitstream + firmware and RUN it (volatile; needs only generic RISC-V
          debug -- no flash driver)
  backup  dump the whole 256 KB flash to a file (do this before any flash write)
  flash   erase+program a binary to a flash address, then read back and byte-verify (OPEN flasher:
          drives the 0x40001000 controller directly -- protocol RE'd by differential capture of the
          vendor driver + verified on silicon)
  image   assemble a combined flash-boot image (MCU + uncompressed fabric + option config-pointer)
          and optionally write it

SWD needs a CMSIS-DAP probe (the AGM DAP-Link) + an OpenOCD built with RISC-V-over-ADIv5-DAP support
(`target create riscv -dap`). Resolution (all overridable):
  binary  : $AGAMEMNON_OPENOCD, verified `agamemnon install-openocd`, PlatformIO fallback,
            then `openocd` on PATH
  config  : $AGAMEMNON_OOCD_CFG, else the shipped openocd/agrv2k.cfg (open config)
  scripts : $AGAMEMNON_OOCD_SCRIPTS (only if your OpenOCD can't `find target/swj-dp.tcl`)
"""
import hashlib, json, os, sys, re, subprocess, tempfile

from . import __version__

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN_CFG = os.path.join(HERE, "openocd", "agrv2k.cfg")   # shipped, vendor-free

# SRAM layout used by the inject path (matches the bring-up harness, silicon-proven).
# SRAM is 128 KiB at [0x20000000, 0x20020000). The uncompressed fabric image (99944 B, fixed size)
# is staged at SRAM_IMG and runs to SRAM_IMG + 99944 = 0x2001a668. SRAM_SP MUST stay clear of that
# whole window (and clear of RESULT_ADDR / SRAM_STUB) -- every historical qualification script uses
# the top of SRAM (0x20020000) for exactly this reason. An SP inside the image window lets a deep
# firmware call stack silently corrupt the staged image before/during FCB streaming.
SRAM_STUB   = 0x20000000        # firmware/stub entry
SRAM_IMG    = 0x20002000        # uncompressed fabric image goes here (24986 words)
SRAM_SP     = 0x20020000        # stack pointer -- top of 128 KiB SRAM, clear of SRAM_IMG
RESULT_ADDR = 0x20001000        # firmware writes results here; we read them back
DEVID_ADDR  = 0x03000100        # reads 0x40200001
EXPECTED_DEVICE_ID = 0x40200001
FLASH_BASE  = 0x80000000
FLASH_SIZE  = 0x40000           # 256 KB
SECTOR      = 0x1000            # 4 KB flash sector

# Flash controller (0x40001000) protocol -- reverse-engineered by differential capture of the vendor
# agrv driver and VERIFIED on silicon (erase->0xFF, program==data). Fully open: driven here via
# generic `mww`/`load_image`, no vendor `agrv` OpenOCD flash bank.
FLASHC   = 0x40001000
FC_KEYR  = FLASHC + 0x04        # unlock: write KEY1 then KEY2
FC_SR    = FLASHC + 0x0C        # status: bit0 = BSY
FC_CR    = FLASHC + 0x10        # control
FC_AR    = FLASHC + 0x14        # address (sector base for erase)
FC_CFG   = FLASHC + 0x2C        # access config
FC_KEY1, FC_KEY2 = 0x45670123, 0xCDEF89AB
CR_LOCK, CR_ERASE, CR_PROG = 0x80, 0x42, 0x8211   # (re)lock / SER+STRT / PG mode

DEFAULT_LOGIC = 0x80010000       # sector-aligned default fabric address, clear of a <64KB MCU
OPT_UNCOMP    = 0x81000030       # option-byte slot: uncompressed config pointer (addr, ~addr)
OPT_BASE      = 0x81000000
OPT_SIZE      = 0x80


class DapProgrammingError(RuntimeError):
    """A DAP/OpenOCD session failed with target state potentially unknown."""


def _unlock():
    return ["mww %#x %#x" % (FC_KEYR, FC_KEY1), "mww %#x %#x" % (FC_KEYR, FC_KEY2)]


def _fc_config():
    return _unlock() + ["mww %#x 0x8001045a" % FC_CFG, "mww %#x 0x34" % FC_AR,
                        "mww %#x 0x4040" % FC_CR, "mww %#x %#x" % (FC_CR, CR_LOCK)]


def _fc_erase(sector):
    return _unlock() + ["mww %#x %#x" % (FC_AR, sector), "mww %#x %#x" % (FC_CR, CR_ERASE),
                        "mww %#x %#x" % (FC_CR, CR_LOCK), "sleep 200"]


def _fc_program(addr, imgfile):
    return _unlock() + ["mww %#x %#x" % (FC_CR, CR_PROG),
                        "load_image %s %#x bin" % (_tcl_path(imgfile), addr),
                        "mww %#x %#x" % (FC_CR, CR_LOCK), "sleep 200"]


def _resolve():
    oocd = os.environ.get("AGAMEMNON_OPENOCD")
    auto_scripts = None
    if not oocd:
        from .tool_install import discover_openocd
        oocd, auto_scripts = discover_openocd()
    if not oocd:
        pio = os.environ.get("PLATFORMIO_CORE_DIR") or os.path.join(os.path.expanduser("~"), ".platformio")
        package = os.path.join(pio, "packages", "tool-agrv_openocd")
        candidate = os.path.join(package, "bin", "openocd.exe" if os.name == "nt" else "openocd")
        if os.path.exists(candidate):
            oocd = candidate
            auto_scripts = os.path.join(package, "share", "openocd", "scripts")
    oocd = oocd or "openocd"
    cfg  = os.environ.get("AGAMEMNON_OOCD_CFG", OPEN_CFG)
    scr  = os.environ.get("AGAMEMNON_OOCD_SCRIPTS") or auto_scripts
    return oocd, cfg, scr


def _win(p):
    return os.path.abspath(p).replace("\\", "/")   # OpenOCD wants native paths, not /c/...


def _tcl_path(path):
    """Quote a native path as one OpenOCD Tcl word, including spaces safely."""
    value = _win(path)
    for character in ("\\", '"', "$", "[", "]"):
        value = value.replace(character, "\\" + character)
    return '"' + value + '"'


def _oocd(cmds, timeout=180):
    oocd, cfg, scr = _resolve()
    args = [oocd]
    if scr:
        args += ["-s", scr]
    args += ["-f", cfg]
    for c in cmds:
        args += ["-c", c]
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DapProgrammingError(
            "OpenOCD timed out after %s s; target state is unknown and the "
            "operation was not retried" % timeout
        ) from exc
    except OSError as exc:
        raise DapProgrammingError("could not start OpenOCD: %s" % exc) from exc


def _mem(log):
    """Parse `mdw` output -> {addr: word}."""
    words = {}
    for m in re.finditer(r"(0x[0-9a-fA-F]{8}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(m.group(1), 16)
        for i, tok in enumerate(m.group(2).split()):
            words[base + 4 * i] = int(tok, 16)
    return words


def _require_ag32():
    """Refuse any DAP write unless a separate read identifies the AG32."""
    result = _oocd([
        "reset halt", "mdw %#x" % DEVID_ADDR, "shutdown",
    ])
    device = _mem(result.stdout + result.stderr).get(DEVID_ADDR)
    if result.returncode or device != EXPECTED_DEVICE_ID:
        raise DapProgrammingError(
            "target identity check failed: expected 0x%08x, got %s"
            % (EXPECTED_DEVICE_ID, "no response" if device is None else "0x%08x" % device)
        )
    return device


def _sectors_for(addr, size):
    if size <= 0:
        return []
    first = addr & ~(SECTOR - 1)
    last = (addr + size - 1) & ~(SECTOR - 1)
    return list(range(first, last + SECTOR, SECTOR))


def _validate_flash_span(addr, size, label="image"):
    """Reject empty or out-of-range writes before any erase command is constructed."""
    end = addr + size
    flash_end = FLASH_BASE + FLASH_SIZE
    if size <= 0:
        raise ValueError("%s is empty; refusing a flash operation" % label)
    if addr < FLASH_BASE or end > flash_end or end < addr:
        raise ValueError("%s span 0x%08x..0x%08x is outside flash 0x%08x..0x%08x"
                         % (label, addr, end - 1, FLASH_BASE, flash_end - 1))
    return end


def _portable_label(path):
    """Describe an input artifact without retaining a workstation root."""
    original = os.path.normpath(str(path))
    if not os.path.isabs(original) and original != ".." and not original.startswith(".." + os.sep):
        return original.replace("\\", "/")
    resolved = os.path.abspath(original)
    try:
        relative = os.path.relpath(resolved, os.getcwd())
    except ValueError:
        relative = None
    if relative and relative != ".." and not relative.startswith(".." + os.sep):
        return relative.replace("\\", "/")
    return os.path.basename(resolved)


def _artifact_record(kind, path, address, image_format):
    data = open(path, "rb").read()
    return {
        "kind": kind,
        "path": _portable_label(path),
        "address": address,
        "end_exclusive": address + len(data),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": image_format,
    }


def build_image_plan(fabric, mcu=None, logic=DEFAULT_LOGIC, *, flash=False,
                     backup=False, write_options=False, option_backup=False):
    """Return the portable, hash-bound plan used by ``agamemnon image``."""
    regions = []
    if mcu:
        regions.append(_artifact_record("mcu", mcu, FLASH_BASE, "raw-binary"))
    regions.append(_artifact_record(
        "fabric", fabric, logic, "agrv2k-uncompressed-config"
    ))
    option_value = logic
    return {
        "schema": 1,
        "kind": "agamemnon-flash-boot-plan",
        "agamemnon_version": __version__,
        "path_policy": {
            "portable": True,
            "artifacts": "cwd-relative-or-basename",
        },
        "flash": {
            "base": FLASH_BASE,
            "size": FLASH_SIZE,
            "sector_size": SECTOR,
        },
        "regions": regions,
        "option_pointer": {
            "address": OPT_UNCOMP,
            "value": option_value,
            "complement": (~option_value) & 0xFFFFFFFF,
            "write_requested": bool(write_options),
            "qualification": "unsupported",
        },
        "operation": {
            "flash_requested": bool(flash),
            "backup_requested": bool(backup),
            "option_backup_requested": bool(option_backup),
        },
    }


def _verify_region(addr, path):
    data = open(path, "rb").read()
    descriptor, readback = tempfile.mkstemp(
        prefix="agamemnon-verify-%08x-" % addr, suffix=".bin"
    )
    os.close(descriptor)
    os.unlink(readback)
    try:
        result = _oocd([
            "reset halt",
            "dump_image %s %#x %d" % (_tcl_path(readback), addr, len(data)),
            "reset", "shutdown",
        ])
        if result.returncode or not os.path.exists(readback):
            return False, "read-back failed"
        got = open(readback, "rb").read()
        if len(got) != len(data):
            return False, "read-back length %d differs from expected %d" % (len(got), len(data))
        if got == data:
            return True, "%d B byte-exact @ 0x%08x" % (len(data), addr)
        n = next(i for i in range(len(data)) if got[i] != data[i])
        return False, "mismatch @ byte %d (got 0x%02x want 0x%02x)" % (n, got[n], data[n])
    finally:
        if os.path.exists(readback):
            os.unlink(readback)


def _dump_backup(path, address, size):
    """Capture one region to a temporary file, then atomically publish it."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".agamemnon-backup-", suffix=".bin", dir=parent
    )
    os.close(descriptor)
    os.unlink(temporary)
    try:
        result = _oocd([
            "reset halt",
            "dump_image %s %#x %d" % (_tcl_path(temporary), address, size),
            "reset", "shutdown",
        ])
        if result.returncode or not os.path.exists(temporary):
            return False
        if os.path.getsize(temporary) != size:
            return False
        os.replace(temporary, target)
        return True
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cmd_probe(a):
    r = _oocd(["reset halt", "mdw %#x" % DEVID_ADDR, "reg misa", "reset", "shutdown"])
    log = r.stdout + r.stderr
    dev = _mem(log).get(DEVID_ADDR)
    if r.returncode or dev is None:
        print("no device found (check the DAP-Link + board + an OpenOCD with `riscv -dap`).")
        print("\n".join(log.splitlines()[-8:])); sys.exit(1)
    print("DEVICE_ID = 0x%08x%s" % (dev, "  (AGRV2K OK)" if dev == 0x40200001 else "  (unexpected)"))


def cmd_sram(a):
    """Load a fabric image (+ firmware) into SRAM, run it, read back results. Volatile: no flash
    touched, needs only generic RISC-V debug. The firmware is expected to FCB-config the fabric from
    0x20002000 (see mcu/ag32.h ag32_fcb_config) and write results to 0x20001000."""
    if a.fabric and os.path.getsize(a.fabric) != 99944:
        print("warning: fabric image is %d bytes, expected 99944 (uncompressed AGaMEMnon .bin)"
              % os.path.getsize(a.fabric))
    _require_ag32()
    cmds = ["reset halt"]
    if a.fabric:
        cmds.append("load_image %s %#x bin" % (_tcl_path(a.fabric), SRAM_IMG))
    cmds += ["load_image %s %#x bin" % (_tcl_path(a.firmware), SRAM_STUB),
             "reg pc %#x" % SRAM_STUB, "reg sp %#x" % SRAM_SP,
             "resume", "sleep %d" % a.sleep, "halt",
             "mdw %#x %d" % (RESULT_ADDR, a.words),
             # This command promises to load and *run* a volatile design. A
             # reset here discarded the SRAM fabric image before an external
             # Pico or logic analyzer could observe it. Resume and detach;
             # a board reset or power cycle restores the flash-boot image.
             "resume", "shutdown"]
    r = _oocd(cmds)
    if r.returncode:
        raise DapProgrammingError(
            "OpenOCD SRAM session failed; target state is unknown and partial "
            "mailbox output was ignored"
        )
    log = r.stdout + r.stderr
    words = _mem(log)
    vals = [words.get(RESULT_ADDR + 4 * i) for i in range(a.words)]
    if all(v is None for v in vals):
        print("no result read back:\n" + "\n".join(log.splitlines()[-10:])); sys.exit(1)
    print("result @ 0x%08x:" % RESULT_ADDR)
    for i, v in enumerate(vals):
        print("  [%d] 0x%08x" % (i, v or 0))
    if vals and vals[0] == 0x000f0002:
        print("  (word[0] = FCB STAT 0x000f0002 -> fabric configured OK)")


def cmd_backup(a):
    ok = _dump_backup(a.output, FLASH_BASE, FLASH_SIZE)
    print("backup -> %s : %s" % (a.output, "OK (%d B)" % FLASH_SIZE if ok else "FAILED"))
    if not ok:
        sys.exit(1)


def cmd_image(a):
    """Assemble the flash-boot image (MCU + uncompressed fabric + option config-pointer) and, with
    --flash, write it via the open flasher. The MCU + fabric writes are the silicon-proven open
    flasher. Writing the option pointer (--write-options) is the ONE unverified step (the option-byte
    program sequence should be confirmed by differential capture first -- see docs/flashboot/
    flash_controller.md); it is opt-in and requires --backup. After a power-cycle the boot ROM loads
    the fabric + runs the MCU."""
    fabric = a.fabric
    fsz = os.path.getsize(fabric)
    if fsz != 99944:
        print("warning: fabric is %d B, expected 99944 (uncompressed AGaMEMnon .bin)" % fsz)
    mcu, msz = a.mcu, (os.path.getsize(a.mcu) if a.mcu else 0)
    logic = int(a.logic_addr, 0) if a.logic_addr else DEFAULT_LOGIC
    if logic & (SECTOR - 1):
        print("--logic-addr must be 4 KB-aligned"); sys.exit(2)
    if msz and 0x80000000 + msz > logic:
        print("MCU (%d B) would overlap the fabric at 0x%08x; raise --logic-addr" % (msz, logic)); sys.exit(2)
    try:
        _validate_flash_span(logic, fsz, "fabric image")
        if msz:
            _validate_flash_span(FLASH_BASE, msz, "MCU image")
    except ValueError as e:
        print("refusing: %s" % e); sys.exit(2)
    option_backup = getattr(a, "option_backup", None)
    if a.write_options and not a.flash:
        print("refusing --write-options without --flash")
        sys.exit(2)
    if a.flash and not a.backup:
        print("refusing --flash without --backup (a complete pre-write backup is mandatory)")
        sys.exit(2)
    if a.write_options and not option_backup:
        print("refusing --write-options without --option-backup")
        sys.exit(2)
    input_paths = {os.path.normcase(os.path.abspath(path)) for path in (fabric, mcu) if path}
    backup_paths = [path for path in (a.backup, option_backup) if path]
    normalized_backups = [os.path.normcase(os.path.abspath(path)) for path in backup_paths]
    plan_json = getattr(a, "plan_json", None)
    output_paths = [*normalized_backups]
    if plan_json:
        output_paths.append(os.path.normcase(os.path.abspath(plan_json)))
    if any(path in input_paths for path in output_paths):
        print("refusing: an output path aliases an input image")
        sys.exit(2)
    if len(set(output_paths)) != len(output_paths):
        print("refusing: manifest and backup outputs must use different files")
        sys.exit(2)
    opt = (logic, (~logic) & 0xFFFFFFFF)

    plan = build_image_plan(
        fabric, mcu, logic,
        flash=a.flash,
        backup=bool(a.backup),
        write_options=a.write_options,
        option_backup=bool(option_backup),
    )
    if plan_json:
        output = os.path.abspath(plan_json)
        parent = os.path.dirname(output)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(plan, indent=2) + "\n")
        print("  Manifest %s" % output)

    print("== flash-boot image plan ==")
    if mcu:
        print("  MCU     %-28s %6d B -> 0x80000000" % (os.path.basename(mcu), msz))
    print("  Fabric  %-28s %6d B -> 0x%08x   (uncompressed, open)" % (os.path.basename(fabric), fsz, logic))
    print("  Option  0x81000030 = (0x%08x, 0x%08x)          (uncompressed config pointer)" % opt)
    if not a.flash:
        print("\n(plan only; add --flash --backup <file> to write)")
        return

    _require_ag32()
    if not _dump_backup(a.backup, FLASH_BASE, FLASH_SIZE):
        print("backup FAILED -- aborting before any write"); sys.exit(1)
    print("backup -> %s (%d B)" % (a.backup, FLASH_SIZE))
    if a.write_options:
        if not _dump_backup(option_backup, OPT_BASE, OPT_SIZE):
            print("option-byte backup FAILED -- aborting before any write"); sys.exit(1)
        print("option backup -> %s (%d B)" % (option_backup, OPT_SIZE))

    # flash MCU + fabric with the proven open flasher (one session)
    cmds = ["reset halt"] + _fc_config()
    if mcu:
        for s in _sectors_for(0x80000000, msz):
            cmds += _fc_erase(s)
        cmds += _fc_program(0x80000000, mcu)
    for s in _sectors_for(logic, fsz):
        cmds += _fc_erase(s)
    cmds += _fc_program(logic, fabric) + ["reset", "shutdown"]
    program_result = _oocd(cmds, timeout=600)
    if program_result.returncode:
        raise DapProgrammingError(
            "OpenOCD combined-image program session failed; target flash state "
            "is unknown and verification was not started"
        )
    ok = True
    if mcu:
        o, m = _verify_region(0x80000000, mcu); ok &= o; print("  MCU    : %s" % m)
    o, m = _verify_region(logic, fabric); ok &= o; print("  Fabric : %s" % m)

    if a.write_options:
        print("!! writing option pointer at 0x81000030 -- UNVERIFIED sequence (see docs/flashboot/");
        print("   flash_controller.md); confirm via differential capture before trusting; BOOT0=1 recovers.")
        oc = ["reset halt",
              "mww %#x %#x" % (FLASHC + 0x08, FC_KEY1), "mww %#x %#x" % (FLASHC + 0x08, FC_KEY2),  # OPTKEYR
              "mww %#x %#x" % (FC_CR, CR_PROG),
              "mww %#x %#x" % (OPT_UNCOMP, opt[0]), "mww %#x %#x" % (OPT_UNCOMP + 4, opt[1]),
              "mww %#x %#x" % (FC_CR, CR_LOCK), "sleep 200",
              "mdw %#x 2" % OPT_UNCOMP, "reset", "shutdown"]
        r = _oocd(oc)
        if r.returncode:
            raise DapProgrammingError(
                "OpenOCD option-byte session failed; option state is unknown; "
                "do not power-cycle until the backup is restored"
            )
        got = _mem(r.stdout + r.stderr)
        gv = (got.get(OPT_UNCOMP), got.get(OPT_UNCOMP + 4))
        print("  option read-back: (0x%08x, 0x%08x) %s"
              % (gv[0] or 0, gv[1] or 0, "OK" if gv == opt else "!= expected -- do NOT power-cycle; restore backup"))
        ok &= (gv == opt)

    print("=> image %s" % ("flashed + verified" if ok else "FAILED -- see above"))
    if not ok:
        sys.exit(1)


def cmd_flash(a):
    """OPEN flasher: write a binary to flash at `addr`, erasing the sectors it spans, via the
    0x40001000 controller (no vendor `agrv` driver). Backs up first if asked, then reads back and
    byte-verifies. This is the reverse-engineered, silicon-verified erase+program sequence."""
    addr = int(a.addr, 0)
    data = open(a.image, "rb").read()
    try:
        _validate_flash_span(addr, len(data), os.path.basename(a.image))
    except ValueError as e:
        print("refusing: %s" % e); sys.exit(2)
    _require_ag32()
    if a.backup:
        if not _dump_backup(a.backup, FLASH_BASE, FLASH_SIZE):
            print("backup FAILED -- aborting before any write"); sys.exit(1)
        print("backup -> %s (%d B)" % (a.backup, FLASH_SIZE))
    sectors = _sectors_for(addr, len(data))
    print("flashing %d B at 0x%08x (erasing %d sector(s))" % (len(data), addr, len(sectors)))
    cmds = ["reset halt"] + _fc_config()
    for s in sectors:
        cmds += _fc_erase(s)
    cmds += _fc_program(addr, a.image) + ["reset", "shutdown"]
    r = _oocd(cmds, timeout=300)
    if r.returncode:
        raise DapProgrammingError(
            "OpenOCD flash program session failed; target flash state is "
            "unknown and verification was not started"
        )
    ok, msg = _verify_region(addr, a.image)
    if ok:
        print("flash OK -- %s (open flasher, no agrv driver)" % msg)
    else:
        print("flash VERIFY FAILED: %s%s" % (msg, "  -- restore your --backup" if a.backup else ""))
        sys.exit(1)
