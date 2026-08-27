"""Fail-closed ELF/disassembly gates for buffered HIL observers.

The gate is intentionally narrower than a generic RISC-V data-flow engine.  A
trace window may load its endpoint through ``a0`` and may access a linker-bound
high-SRAM scratch object.  A store through any other pointer is rejected.  This
is sufficient to reject the frozen R4 mailbox-RMW shape while keeping the rule
auditable and reusable by later buffered observers.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

from .project import find_riscv_tool


SRAM_BASE = 0x20000000
HIGH_SRAM_BASE = 0x2001B000
OBSERVER_WINDOW_END = 0x2001C000
SRAM_END = 0x20020000
SCRATCH_SYMBOL = "ag32_hil_observer_scratch"
TRACE_SYMBOL = "trace_phase"


class ObserverAuditError(RuntimeError):
    """The observer ELF cannot prove a non-perturbative trace window."""


def _objdump(elf_path, *arguments, objdump=None):
    executable = objdump or find_riscv_tool("riscv64-unknown-elf-objdump")
    result = subprocess.run(
        [str(executable), *arguments, str(elf_path)],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        raise ObserverAuditError("objdump failed: %s" % result.stderr.strip())
    return result.stdout


def _symbols(table):
    result = {}
    for line in table.splitlines():
        fields = line.split()
        if len(fields) < 2 or not re.fullmatch(r"[0-9a-fA-F]{8}", fields[0]):
            continue
        name = fields[-1]
        size = 0
        if len(fields) >= 2 and re.fullmatch(r"[0-9a-fA-F]{8}", fields[-2]):
            size = int(fields[-2], 16)
        result[name] = {"address": int(fields[0], 16), "size": size}
    return result


def _function(disassembly, name):
    marker = re.compile(r"^\s*([0-9a-fA-F]+) <%s>:\s*$" % re.escape(name))
    next_symbol = re.compile(r"^\s*[0-9a-fA-F]+ <[^>]+>:\s*$")
    lines = disassembly.splitlines()
    for index, line in enumerate(lines):
        match = marker.match(line)
        if not match:
            continue
        body = []
        for candidate in lines[index + 1:]:
            if next_symbol.match(candidate):
                break
            if candidate.strip():
                body.append(candidate)
        return int(match.group(1), 16), body
    raise ObserverAuditError("ELF is missing required %s trace symbol" % name)


def _instruction(line):
    match = re.match(
        r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{4,8}\s+)+"
        r"(\S+)(?:\s+(.*?))?\s*$", line,
    )
    if not match:
        return None
    operands = (match.group(3) or "").split("#", 1)[0].strip()
    return int(match.group(1), 16), match.group(2), operands


def _memory_base(operands):
    match = re.search(r"[-+]?\d+\((\w+)\)", operands)
    return None if match is None else match.group(1)


def _is_load(mnemonic):
    return mnemonic in {
        "lb", "lbu", "lh", "lhu", "lw", "c.lw", "c.lwsp",
    }


def _is_store(mnemonic):
    return mnemonic in {"sb", "sh", "sw", "c.sw", "c.swsp"}


def _trace_callsites(disassembly, trace_symbol):
    """Prove every trace call's endpoint and phase from machine code."""
    unused, lines = _function(disassembly, "main")
    constants = {}
    calls = []
    caller_saved = {
        "ra", "t0", "t1", "t2", "t3", "t4", "t5", "t6",
        "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
    }
    for line in lines:
        decoded = _instruction(line)
        if decoded is None:
            continue
        address, mnemonic, operands = decoded
        fields = [field.strip() for field in operands.split(",") if field.strip()]
        if mnemonic == "lui" and len(fields) == 2:
            constants[fields[0]] = int(fields[1], 0) << 12
        elif mnemonic == "addi" and len(fields) == 3:
            source = constants.get(fields[1])
            constants[fields[0]] = (
                None if source is None else (source + int(fields[2], 0)) & 0xFFFFFFFF)
        elif mnemonic == "c.addi" and len(fields) == 2:
            source = constants.get(fields[0])
            constants[fields[0]] = (
                None if source is None else (source + int(fields[1], 0)) & 0xFFFFFFFF)
        elif mnemonic == "c.li" and len(fields) == 2:
            constants[fields[0]] = int(fields[1], 0) & 0xFFFFFFFF
        elif mnemonic in {"mv", "c.mv"} and len(fields) == 2:
            constants[fields[0]] = constants.get(fields[1])

        if mnemonic not in {"jal", "c.jal"}:
            continue
        if "<%s>" % trace_symbol in operands:
            calls.append({
                "instruction": "0x%08x" % address,
                "status": constants.get("a0"),
                "phase": constants.get("a1"),
            })
        for register in caller_saved:
            constants[register] = None

    expected_status = [0x60000000, 0x60000004, 0x60000000]
    expected_phase = [0, 1, 2]
    if ([call["status"] for call in calls] != expected_status
            or [call["phase"] for call in calls] != expected_phase):
        raise ObserverAuditError(
            "trace callsites do not prove exact 0x60000000/+4 endpoint order")
    return calls


def audit_buffered_observer_elf(
        elf_path, *, objdump=None, trace_symbol=TRACE_SYMBOL,
        scratch_symbol=SCRATCH_SYMBOL):
    """Return a machine-readable proof or reject the observer ELF.

    Accepted trace memory operations are endpoint loads through ``a0``, stack
    accesses (the campaign runner binds SP to 0x20020000), and accesses whose
    register lineage begins at the exact high-SRAM scratch object.  Low-SRAM
    address construction and unproven pointer stores fail closed.
    """
    elf_path = Path(elf_path)
    data = elf_path.read_bytes()
    if data[:6] != b"\x7fELF\x01\x01":
        raise ObserverAuditError("observer must be a little-endian ELF32 file")

    symbol_table = _symbols(_objdump(elf_path, "-t", objdump=objdump))
    if scratch_symbol not in symbol_table:
        raise ObserverAuditError(
            "missing linker-bound high-SRAM scratch symbol; frozen mailbox "
            "pointer observers are not buffered")
    scratch = symbol_table[scratch_symbol]
    scratch_start = scratch["address"]
    scratch_end = scratch_start + scratch["size"]
    if scratch["size"] < 32 * 4:
        raise ObserverAuditError("observer scratch is smaller than 32 words")
    if not (HIGH_SRAM_BASE <= scratch_start < scratch_end <= OBSERVER_WINDOW_END):
        raise ObserverAuditError("observer scratch is outside the R5 high-SRAM window")
    linker_start = symbol_table.get("__ag32_hil_observer_scratch_start")
    linker_end = symbol_table.get("__ag32_hil_observer_scratch_end")
    if (linker_start is None or linker_end is None
            or linker_start["address"] != scratch_start
            or linker_end["address"] != scratch_end):
        raise ObserverAuditError("linker scratch bounds do not match the object")

    disassembly = _objdump(
        elf_path, "-d", "-M", "no-aliases", objdump=objdump,
    )
    trace_calls = _trace_callsites(disassembly, trace_symbol)
    trace_address, trace_lines = _function(disassembly, trace_symbol)
    if not (HIGH_SRAM_BASE <= trace_address < SRAM_END):
        raise ObserverAuditError("trace code is not executing from high SRAM")

    # Register provenance is deliberately coarse.  It tracks whether an
    # address derives from the exact scratch page; arithmetic preserves that
    # provenance, while overwritten registers lose it.
    provenance = {}
    memory_ops = []
    scratch_stores = 0
    endpoint_loads = 0
    for line in trace_lines:
        decoded = _instruction(line)
        if decoded is None:
            continue
        address, mnemonic, operands = decoded
        fields = [field.strip() for field in operands.split(",") if field.strip()]

        if mnemonic == "lui" and len(fields) == 2:
            register = fields[0]
            value = int(fields[1], 0) << 12
            if SRAM_BASE <= value < HIGH_SRAM_BASE:
                raise ObserverAuditError(
                    "trace constructs low-SRAM address at 0x%08x" % address)
            provenance[register] = (
                "scratch" if scratch_start & ~0xFFF == value else "other"
            )
        elif mnemonic in {"addi", "c.addi", "c.addi16sp"} and fields:
            destination = fields[0]
            source = fields[1] if mnemonic == "addi" and len(fields) > 1 else destination
            provenance[destination] = provenance.get(source, "other")
        elif mnemonic in {"add", "c.add"} and len(fields) >= 2:
            destination = fields[0]
            sources = fields[1:] if mnemonic == "add" else fields[:2]
            provenance[destination] = (
                "scratch" if any(provenance.get(item) == "scratch" for item in sources)
                else "other"
            )
        elif mnemonic in {"mv", "c.mv"} and len(fields) == 2:
            provenance[fields[0]] = provenance.get(fields[1], "other")
        elif (mnemonic.startswith("c.li") or mnemonic == "addi") and fields:
            provenance[fields[0]] = "other"

        if not (_is_load(mnemonic) or _is_store(mnemonic)):
            continue
        base = _memory_base(operands)
        operation = "store" if _is_store(mnemonic) else "load"
        memory_ops.append({
            "address": "0x%08x" % address,
            "operation": operation,
            "base": base,
        })
        if base in {"sp"}:
            continue
        if operation == "load" and base == "a0":
            endpoint_loads += 1
            continue
        if provenance.get(base) == "scratch":
            if operation == "store":
                scratch_stores += 1
            continue
        raise ObserverAuditError(
            "trace %s at 0x%08x uses unproven pointer %s; low-SRAM "
            "mailbox traffic cannot be excluded" % (operation, address, base)
        )

    if endpoint_loads < 1:
        raise ObserverAuditError("trace has no endpoint load through a0")
    if scratch_stores < 1:
        raise ObserverAuditError("trace never stores to proven high-SRAM scratch")

    return {
        "schema": 1,
        "kind": "agamemnon-buffered-hil-observer-elf-audit",
        "elf": str(elf_path),
        "trace_symbol": trace_symbol,
        "trace_address": "0x%08x" % trace_address,
        "scratch_symbol": scratch_symbol,
        "scratch_start": "0x%08x" % scratch_start,
        "scratch_end": "0x%08x" % scratch_end,
        "trace_calls": [{
            "instruction": call["instruction"],
            "status": "0x%08x" % call["status"],
            "phase": call["phase"],
        } for call in trace_calls],
        "low_sram_load_store_in_trace": 0,
        "endpoint_load_instructions": endpoint_loads,
        "scratch_store_instructions": scratch_stores,
        "memory_operations": memory_ops,
        "verdict": "pass-buffered-observer-noninterference-gate",
    }
