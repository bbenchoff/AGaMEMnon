"""Preflight an OpenOCD input before it enters an AGaMEMnon SDK bundle."""

from pathlib import Path
import subprocess


def executable_in(root):
    root = Path(root)
    names = ("openocd.exe", "openocd")
    candidates = [root / "bin" / name for name in names]
    candidates += [root / "src" / name for name in names]
    candidates += [root / name for name in names]
    return next((item for item in candidates if item.is_file()), None)


def classify_dap_probe(output):
    """Classify a parser-only `target create riscv -dap missing` probe."""
    lower = output.lower()
    if "dap name invalid" in lower or "invalid dap" in lower or "dap 'missing'" in lower:
        return True
    if "unknown option" in lower or "unknown target type riscv" in lower:
        return False
    return None


def probe_dap(executable, timeout=10):
    result = subprocess.run(
        [str(executable), "-c", "target create agamemnon_probe riscv -dap missing",
         "-c", "shutdown"],
        capture_output=True, text=True, timeout=timeout,
    )
    output = result.stdout + result.stderr
    accepted = classify_dap_probe(output)
    if accepted is not True:
        raise RuntimeError(
            "OpenOCD did not prove the required `target create riscv -dap` parser path:\n" + output
        )
    return output


def validate_corresponding_source(source):
    """Require a distributable source tree, not a URL or binary-only package."""
    source = Path(source).resolve()
    if not source.is_dir():
        raise RuntimeError("OpenOCD corresponding source must be an unpacked directory")
    license_files = [source / "COPYING", source / "LICENSE",
                     source / "LICENSES" / "preferred" / "GPL-2.0"]
    if not any(item.exists() for item in license_files):
        raise RuntimeError("OpenOCD corresponding source has no GPL license text")
    riscv_source = source / "src" / "target" / "riscv" / "riscv.c"
    if not riscv_source.is_file():
        raise RuntimeError("OpenOCD corresponding source has no src/target/riscv/riscv.c")
    text = riscv_source.read_text(encoding="utf-8", errors="replace")
    if "dap" not in text.lower():
        raise RuntimeError("OpenOCD RISC-V source contains no DAP implementation marker")
    return source


def audit(root, corresponding_source):
    executable = executable_in(root)
    if executable is None:
        raise RuntimeError("OpenOCD input has no bin/openocd executable")
    probe_dap(executable)
    source = validate_corresponding_source(corresponding_source)
    return executable, source

