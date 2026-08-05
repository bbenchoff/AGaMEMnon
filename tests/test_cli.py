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


def test_cli_agasc_round_trip_is_byte_exact(tmp_path):
    work = str(tmp_path)
    src = os.path.join(work, "blinky.bin")
    asc = os.path.join(work, "blinky.agasc")
    rebuilt = os.path.join(work, "rebuilt.bin")
    shutil.copyfile(FIXTURE, src)

    dec = _run_cli(["to-agasc", src, "-o", asc], cwd=work)
    assert dec.returncode == 0, dec.stdout
    assert "asserted named feature(s)" in dec.stdout
    with open(asc, encoding="utf-8") as f:
        text = f.read()
    assert ".agasc 1" in text and ".tile " in text and ".raw " in text

    enc = _run_cli(["from-agasc", asc, "-o", rebuilt], cwd=work)
    assert enc.returncode == 0, enc.stdout
    with open(src, "rb") as f:
        original = f.read()
    with open(rebuilt, "rb") as f:
        output = f.read()
    assert output == original


def test_cli_edit_lut_changes_one_raw_byte(tmp_path):
    # The edit-lut subcommand reports exactly one changed payload byte for a
    # single-LE INIT edit and regenerates the FCB-checked CRC.
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
    explained = _run_cli(["explain", out], cwd=work)
    assert explained.returncode == 0, explained.stdout
    assert "crc valid" in explained.stdout.lower(), explained.stdout


def test_cli_edit_lut_preserves_uncompressed_sram_form(tmp_path):
    work = str(tmp_path)
    raw = os.path.join(work, "blinky.raw")
    src = os.path.join(work, "blinky-uncompressed.bin")
    out = os.path.join(work, "edited-uncompressed.bin")
    decoded = _run_cli(["decode", FIXTURE, "-o", raw], cwd=work)
    assert decoded.returncode == 0, decoded.stdout
    with open(FIXTURE, "rb") as stream:
        header = stream.read(8)
    with open(raw, "rb") as stream:
        payload = stream.read()
    with open(src, "wb") as stream:
        stream.write(header + payload)

    edited = _run_cli(
        ["edit-lut", src, "--le", "20,12,1", "--init", "0x96e9", "-o", out],
        cwd=work,
    )
    assert edited.returncode == 0, edited.stdout
    assert os.path.getsize(out) == os.path.getsize(src) == 99944
    explained = _run_cli(["explain", out], cwd=work)
    assert explained.returncode == 0, explained.stdout
    assert "image uncompressed" in explained.stdout.lower(), explained.stdout
    assert "crc valid" in explained.stdout.lower(), explained.stdout


ROUTED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "counter_ahb_routed.json")


def test_cli_verify_counter_reachable_set(tmp_path):
    # The offline verifier cycle-sims the silicon-proven 4-bit counter's routed netlist. Its two taps
    # (cnt[0], cnt[3]) cycle through every combination, so the reachable read set is exactly {0,1,2,3},
    # the MCU_DOUT bind is sound, and it exits 0.
    res = _run_cli(["verify", ROUTED, "--cycles", "32"], cwd=str(tmp_path))
    assert res.returncode == 0, res.stdout
    assert "[0, 1, 2, 3]" in res.stdout, res.stdout
    assert "OK" in res.stdout and "SCRAMBLED" not in res.stdout, res.stdout


def test_cli_verify_observed_soundness(tmp_path):
    # --observed compares a silicon value set to the sim: the proven set passes SOUND; an impossible
    # value (7, outside the 2-bit readout) is flagged as a MISMATCH (non-zero exit).
    ok = _run_cli(["verify", ROUTED, "--observed", "0,1,2,3", "--cycles", "32"], cwd=str(tmp_path))
    assert ok.returncode == 0, ok.stdout
    assert "VERDICT: CORRECT" in ok.stdout, ok.stdout

    bad = _run_cli(["verify", ROUTED, "--observed", "0,1,7", "--cycles", "32"], cwd=str(tmp_path))
    assert bad.returncode != 0, bad.stdout
    assert "MISMATCH" in bad.stdout, bad.stdout
