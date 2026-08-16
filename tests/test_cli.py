"""End-to-end CLI: `python -m agamemnon.cli decode | encode` round-trips the fixture file
byte-for-byte.

Driven via subprocess (a real process, not an in-process import) so this also proves the
`python -m agamemnon.cli` entry point and the package's relative imports resolve when invoked the
way a user would. Runs entirely in a temp dir; no hardware, no external data.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from agamemnon import cli

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


def test_pcf_package_pins_are_canonical_decimal(tmp_path):
    prefixed = tmp_path / "prefixed.pcf"
    bare = tmp_path / "bare.pcf"
    dedicated = tmp_path / "dedicated.pcf"
    prefixed.write_text("set_io led PIN_10\n", encoding="utf-8")
    bare.write_text("set_io led 10\n", encoding="utf-8")
    dedicated.write_text("set_io clock PIN_HSE\n", encoding="utf-8")

    assert cli._read_pcf(prefixed) == {"led": "PIN_10"}
    assert cli._read_pcf(bare) == {"led": "PIN_10"}
    assert cli._read_pcf(dedicated) == {"clock": "PIN_HSE"}


@pytest.mark.parametrize("spelling", ["0x10", "PIN_0x10", "PIN_A", "PIN_010"])
def test_pcf_rejects_non_decimal_or_noncanonical_package_pins(tmp_path, spelling):
    pcf = tmp_path / "bad.pcf"
    pcf.write_text("set_io led %s\n" % spelling, encoding="utf-8")

    with pytest.raises(ValueError, match="decimal physical lead"):
        cli._read_pcf(pcf)


def test_qualified_pad_vendor_presentation_is_derived_from_the_pcf(tmp_path):
    table = tmp_path / "pad_output_qualified_L48.csv"
    table.write_text(
        "pin,vendor_out_slice\n"
        "PIN_16,\n"
        'PIN_14,"14,9,15"\n',
        encoding="utf-8",
    )
    assert cli._qualified_pad_vendor_out({"o": "PIN_16"}, tmp_path) is None
    assert cli._qualified_pad_vendor_out({"o": "PIN_14"}, tmp_path) == "14,9,15"


def test_multiple_qualified_vendor_presentations_fail_closed(tmp_path):
    (tmp_path / "pad_output_qualified_L48.csv").write_text(
        'pin,vendor_out_slice\nPIN_14,"14,9,15"\nPIN_13,"14,9,14"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="multiple vendor-output slices"):
        cli._qualified_pad_vendor_out({"a": "PIN_14", "b": "PIN_13"}, tmp_path)


def _write_iob_netlist(path, cells, ports=None):
    path.write_text(json.dumps({
        "modules": {
            "top": {
                "attributes": {"top": "1"},
                "ports": ports or {},
                "cells": cells,
            },
        },
    }), encoding="utf-8")


def test_vendor_output_selection_uses_synthesized_io_direction(tmp_path):
    table = tmp_path / "pad_output_qualified_L48.csv"
    table.write_text(
        "pin,vendor_out_slice\n"
        'PIN_12,"14,9,4"\n'
        "PIN_16,\n",
        encoding="utf-8",
    )
    netlist = tmp_path / "directional.json"
    _write_iob_netlist(netlist, {
        "$iopadmap$top.pin_in": {
            "type": "GENERIC_IOB",
            "port_directions": {"PAD": "inout", "O": "output"},
        },
        "$iopadmap$top.pin_out": {
            "type": "GENERIC_IOB",
            "port_directions": {"PAD": "inout", "I": "input"},
        },
    })
    pcf = {"pin_in": "PIN_12", "pin_out": "PIN_16"}

    output_pcf = cli._pcf_output_constraints(netlist, pcf)

    assert output_pcf == {"pin_out": "PIN_16"}
    assert cli._qualified_pad_vendor_out(output_pcf, tmp_path) is None


def test_vendor_output_selection_keeps_actual_pin12_output(tmp_path):
    (tmp_path / "pad_output_qualified_L48.csv").write_text(
        'pin,vendor_out_slice\nPIN_12,"14,9,4"\n',
        encoding="utf-8",
    )
    netlist = tmp_path / "output.json"
    _write_iob_netlist(netlist, {
        "$iopadmap$top.pin_out": {
            "type": "GENERIC_IOB",
            "port_directions": {"PAD": "inout", "I": "input"},
        },
    })

    output_pcf = cli._pcf_output_constraints(netlist, {"pin_out": "PIN_12"})

    assert output_pcf == {"pin_out": "PIN_12"}
    assert cli._qualified_pad_vendor_out(output_pcf, tmp_path) == "14,9,4"


def test_pcf_output_direction_resolves_vector_offset_by_pad_bit(tmp_path):
    netlist = tmp_path / "vector.json"
    _write_iob_netlist(
        netlist,
        {
            "$iopadmap$top.gpio_1": {
                "type": "GENERIC_IOB",
                "port_directions": {"PAD": "inout", "I": "input"},
                "connections": {"PAD": [102]},
            },
        },
        ports={
            "gpio": {
                "direction": "output",
                "offset": 4,
                "bits": [101, 102],
            },
        },
    )

    assert cli._pcf_output_constraints(netlist, {"gpio[5]": "PIN_12"}) == {
        "gpio[5]": "PIN_12",
    }


@pytest.mark.parametrize("cells", [
    {},
    {
        "$iopadmap$top.pin": {
            "type": "GENERIC_IOB",
            "port_directions": {"I": "input"},
        },
        "$another.pin": {
            "type": "GENERIC_IOB",
            "port_directions": {"I": "input"},
        },
    },
])
def test_pcf_output_direction_resolution_fails_closed_on_ambiguous_iob(tmp_path, cells):
    netlist = tmp_path / "ambiguous.json"
    _write_iob_netlist(netlist, cells)

    with pytest.raises(ValueError, match="matched [02] synthesized GENERIC_IOB cells"):
        cli._pcf_output_constraints(netlist, {"pin": "PIN_12"})


def test_pcf_output_direction_resolution_fails_closed_on_malformed_bidir(tmp_path):
    netlist = tmp_path / "malformed.json"
    _write_iob_netlist(netlist, {
        "$iopadmap$top.pin": {
            "type": "GENERIC_IOB",
            "port_directions": {"I": "input", "O": "output"},
        },
    })

    with pytest.raises(ValueError, match="malformed bidirectional I/O directions"):
        cli._pcf_output_constraints(netlist, {"pin": "PIN_12"})


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
