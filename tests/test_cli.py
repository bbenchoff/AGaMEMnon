"""End-to-end CLI: `python -m agamemnon.cli decode | encode` round-trips the fixture file
byte-for-byte.

Driven via subprocess (a real process, not an in-process import) so this also proves the
`python -m agamemnon.cli` entry point and the package's relative imports resolve when invoked the
way a user would. Runs entirely in a temp dir; no hardware, no external data.
"""
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "blinky.bin")


def _run_cli(args, cwd):
    env = dict(os.environ)
    # Ensure the in-tree package wins regardless of any installed copy.
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", *args],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_cli_decode_encode_round_trip(tmp_path):
    work = str(tmp_path)
    src = os.path.join(work, "blinky.bin")
    raw = os.path.join(work, "raw.img")
    rebuilt = os.path.join(work, "rebuilt.bin")
    shutil.copyfile(FIXTURE, src)

    dec = _run_cli(["decode", src, "-o", raw], cwd=work)
    assert dec.returncode == 0, dec.stdout
    assert os.path.getsize(raw) == 99936

    enc = _run_cli(["encode", raw, "-o", rebuilt], cwd=work)
    assert enc.returncode == 0, enc.stdout

    with open(src, "rb") as f:
        orig = f.read()
    with open(rebuilt, "rb") as f:
        out = f.read()
    assert out == orig, "CLI decode->encode is not byte-identical to the original .bin"


def test_cli_edit_lut_changes_one_raw_byte(tmp_path):
    # The edit-lut subcommand reports exactly one changed raw byte for a single-LE INIT edit.
    work = str(tmp_path)
    src = os.path.join(work, "blinky.bin")
    out = os.path.join(work, "edited.bin")
    shutil.copyfile(FIXTURE, src)

    res = _run_cli(
        ["edit-lut", src, "--le", "20,12,1", "--init", "0x96e9", "-o", out],
        cwd=work,
    )
    assert res.returncode == 0, res.stdout
    assert "1 raw byte(s) changed" in res.stdout, res.stdout
    assert os.path.exists(out)
