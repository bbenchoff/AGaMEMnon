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
  binary  : $AGAMEMNON_OPENOCD, else `openocd` on PATH
  config  : $AGAMEMNON_OOCD_CFG, else the shipped openocd/agrv2k.cfg (open config)
  scripts : $AGAMEMNON_OOCD_SCRIPTS (only if your OpenOCD can't `find target/swj-dp.tcl`)
"""
import os, sys, re, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN_CFG = os.path.join(HERE, "openocd", "agrv2k.cfg")   # shipped, vendor-free

# SRAM layout used by the inject path (matches the bring-up harness, silicon-proven)
SRAM_STUB   = 0x20000000        # firmware/stub entry
SRAM_SP     = 0x20008000        # stack pointer
SRAM_IMG    = 0x20002000        # uncompressed fabric image goes here (24986 words)
RESULT_ADDR = 0x20001000        # firmware writes results here; we read them back
DEVID_ADDR  = 0x03000100        # reads 0x40200001
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
                        "load_image %s %#x bin" % (_win(imgfile), addr),
                        "mww %#x %#x" % (FC_CR, CR_LOCK), "sleep 200"]


def _resolve():
    oocd = os.environ.get("AGAMEMNON_OPENOCD") or "openocd"
    cfg  = os.environ.get("AGAMEMNON_OOCD_CFG", OPEN_CFG)
    scr  = os.environ.get("AGAMEMNON_OOCD_SCRIPTS")
    return oocd, cfg, scr


def _win(p):
    return os.path.abspath(p).replace("\\", "/")   # OpenOCD wants native paths, not /c/...


def _oocd(cmds, timeout=180):
    oocd, cfg, scr = _resolve()
    args = [oocd]
    if scr:
        args += ["-s", scr]
    args += ["-f", cfg]
    for c in cmds:
        args += ["-c", c]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _mem(log):
    """Parse `mdw` output -> {addr: word}."""
    words = {}
    for m in re.finditer(r"(0x[0-9a-fA-F]{8}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(m.group(1), 16)
        for i, tok in enumerate(m.group(2).split()):
            words[base + 4 * i] = int(tok, 16)
    return words


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


def _verify_region(addr, path):
    data = open(path, "rb").read()
    vb = os.path.join(tempfile.gettempdir(), "agamemnon_vrfy_%08x.bin" % addr)
    _oocd(["reset halt", "dump_image %s %#x %d" % (_win(vb), addr, len(data)), "reset", "shutdown"])
    if not os.path.exists(vb):
        return False, "read-back failed"
    got = open(vb, "rb").read()[:len(data)]
    if got == data:
        return True, "%d B byte-exact @ 0x%08x" % (len(data), addr)
    n = next((i for i in range(len(data)) if got[i] != data[i]), 0)
    return False, "mismatch @ byte %d (got 0x%02x want 0x%02x)" % (n, got[n], data[n])


def cmd_probe(a):
    r = _oocd(["reset halt", "mdw %#x" % DEVID_ADDR, "reg misa", "reset", "shutdown"])
    log = r.stdout + r.stderr
    dev = _mem(log).get(DEVID_ADDR)
    if dev is None:
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
    cmds = ["reset halt"]
    if a.fabric:
        cmds.append("load_image %s %#x bin" % (_win(a.fabric), SRAM_IMG))
    cmds += ["load_image %s %#x bin" % (_win(a.firmware), SRAM_STUB),
             "reg pc %#x" % SRAM_STUB, "reg sp %#x" % SRAM_SP,
             "resume", "sleep %d" % a.sleep, "halt",
             "mdw %#x %d" % (RESULT_ADDR, a.words), "reset", "shutdown"]
    r = _oocd(cmds)
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
    r = _oocd(["reset halt", "dump_image %s %#x %d" % (_win(a.output), FLASH_BASE, FLASH_SIZE),
               "reset", "shutdown"])
    ok = os.path.exists(a.output) and os.path.getsize(a.output) == FLASH_SIZE
    print("backup -> %s : %s" % (a.output, "OK (%d B)" % FLASH_SIZE if ok else "FAILED"))
    if not ok:
        print("\n".join((r.stdout + r.stderr).splitlines()[-8:])); sys.exit(1)


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
    opt = (logic, (~logic) & 0xFFFFFFFF)

    print("== flash-boot image plan ==")
    if mcu:
        print("  MCU     %-28s %6d B -> 0x80000000" % (os.path.basename(mcu), msz))
    print("  Fabric  %-28s %6d B -> 0x%08x   (uncompressed, open)" % (os.path.basename(fabric), fsz, logic))
    print("  Option  0x81000030 = (0x%08x, 0x%08x)          (uncompressed config pointer)" % opt)
    if not a.flash:
        print("\n(plan only; add --flash to write, --backup <file> strongly recommended)")
        return

    if a.backup:
        _oocd(["reset halt", "dump_image %s %#x %d" % (_win(a.backup), FLASH_BASE, FLASH_SIZE),
               "reset", "shutdown"])
        if not (os.path.exists(a.backup) and os.path.getsize(a.backup) == FLASH_SIZE):
            print("backup FAILED -- aborting before any write"); sys.exit(1)
        print("backup -> %s (%d B)" % (a.backup, FLASH_SIZE))
    elif a.write_options:
        print("refusing --write-options without --backup (option bytes affect boot; keep a restore point)")
        sys.exit(2)

    # flash MCU + fabric with the proven open flasher (one session)
    cmds = ["reset halt"] + _fc_config()
    if mcu:
        for s in _sectors_for(0x80000000, msz):
            cmds += _fc_erase(s)
        cmds += _fc_program(0x80000000, mcu)
    for s in _sectors_for(logic, fsz):
        cmds += _fc_erase(s)
    cmds += _fc_program(logic, fabric) + ["reset", "shutdown"]
    _oocd(cmds, timeout=600)
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
    if a.backup:
        rb = _oocd(["reset halt", "dump_image %s %#x %d" % (_win(a.backup), FLASH_BASE, FLASH_SIZE),
                    "reset", "shutdown"])
        if not (os.path.exists(a.backup) and os.path.getsize(a.backup) == FLASH_SIZE):
            print("backup FAILED -- aborting before any write\n" + (rb.stdout + rb.stderr)[-600:]); sys.exit(1)
        print("backup -> %s (%d B)" % (a.backup, FLASH_SIZE))
    sectors = _sectors_for(addr, len(data))
    print("flashing %d B at 0x%08x (erasing %d sector(s))" % (len(data), addr, len(sectors)))
    cmds = ["reset halt"] + _fc_config()
    for s in sectors:
        cmds += _fc_erase(s)
    cmds += _fc_program(addr, a.image) + ["reset", "shutdown"]
    r = _oocd(cmds, timeout=300)
    ok, msg = _verify_region(addr, a.image)
    if ok:
        print("flash OK -- %s (open flasher, no agrv driver)" % msg)
    else:
        print("flash VERIFY FAILED: %s%s" % (msg, "  -- restore your --backup" if a.backup else ""))
        sys.exit(1)
