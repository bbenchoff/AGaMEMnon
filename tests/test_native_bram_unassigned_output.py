"""BRAM BEL resolution and output reach must respect the supplied graph.

These are native packing checks, not bitstream or silicon qualification of the
optional site-read profile. A packer flag cannot add pips to an existing graph.
"""
import csv
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess

import pytest
from devdb_fixtures import devdb_path

ROOT = Path(__file__).resolve().parents[1]
BINARY = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
# These cases test two specific graph contracts, so a caller's shared native
# database must not silently substitute for either freshly emitted fixture.
DEVDBS = ({name: devdb_path(name) for name in ("strict_pcf", "strict_pcf_bram_site")}
          if BINARY and Path(BINARY).is_file() else {})


@lru_cache(maxsize=2)
def _egress_sources(devdb):
    with (devdb / "dev_pips.csv").open(newline="") as stream:
        return {row["src"] for row in csv.DictReader(stream)}


def _has_output_egress(devdb, bel):
    with (devdb / "dev_belpins.csv").open(newline="") as stream:
        source = next(row["wire"] for row in csv.DictReader(stream)
                      if row["bel"] == bel and row["pin"] == "DataOutA[0]")
    return source in _egress_sources(devdb)


def _design(bel):
    bram = dict(type="ALTA_BRAM9K", parameters={},
                attributes={"BEL": bel} if bel else {},
                port_directions={"DataOutA[0]": "output", "Clk0": "input"},
                connections={"DataOutA[0]": [2], "Clk0": [3]})
    sink = dict(type="GENERIC_SLICE", attributes={},
                parameters={"K": "100", "INIT": format(0xAAAA, "016b"), "FF_USED": "0"},
                port_directions={"I": "input", "F": "output", "Q": "output"},
                connections={"I": [2, "x", "x", "x"], "F": [], "Q": []})
    clock = dict(type="MCU_BUS_CLOCK", attributes={}, parameters={},
                 port_directions={"CLK": "output"}, connections={"CLK": [3]})
    return {"modules": {"top": dict(attributes={"top": 1}, ports={},
            cells={"ram": bram, "sink": sink, "clock": clock},
            netnames={"read": dict(bits=[2], attributes={}),
                      "clock": dict(bits=[3], attributes={})})}}


def _pack(tmp_path, bel, site_profile, graph_profile="strict_pcf"):
    if not DEVDBS:
        pytest.skip("set the isolated native executable")
    devdb = DEVDBS[graph_profile]
    assert (devdb / "dev_pips.csv").is_file()
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_design(bel)))
    output = tmp_path / "packed.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGAMEMNON_", "AGRV2K_"))}
    # A slice sink isolates BEL resolution/output packing from exact MCU exit
    # replay, while leaving ordinary output-reach bridge checks enabled.
    env["AGRV2K_BRAM_PINPACK"] = "1"
    if site_profile:
        env["AGAMEMNON_BRAM_SITE_READ_PATHS"] = "1"
    result = subprocess.run([BINARY, "--uarch", "agrv2k", "-o", f"chipdb={devdb}",
                             "--json", str(source), "--write", str(output),
                             "--top", "top", "--pack-only"],
                            env=env, capture_output=True, text=True, timeout=60)
    transcript = result.stdout + result.stderr
    (tmp_path / "native.log").write_text(transcript)
    return result, transcript, output


def test_unassigned_bram_output_packs_without_site_profile(tmp_path):
    result, transcript, output = _pack(tmp_path, None, False)
    assert result.returncode == 0, transcript
    assert output.is_file()


@pytest.mark.parametrize("bel", [None, "X99Y99_BRAM", "X14Y4_SLICE0"])
def test_site_profile_refuses_missing_or_non_bram_bel_by_name(tmp_path, bel):
    result, transcript, output = _pack(tmp_path, bel, True)
    assert result.returncode > 0, transcript  # a diagnostic, not a signal/abort
    expected = ("site-read output requires an assigned or valid requested BRAM BEL"
                if bel is None else "invalid requested BRAM BEL")
    assert expected in transcript
    assert "std::out_of_range" not in transcript
    assert not output.exists()


@pytest.mark.parametrize("bel", [f"X13Y{y}_BRAM" for y in range(1, 5)])
@pytest.mark.parametrize("site_profile", [False, True])
def test_requested_bram_output_packs_at_every_site(tmp_path, bel, site_profile):
    result, transcript, output = _pack(tmp_path, bel, site_profile, "strict_pcf_bram_site")
    assert _has_output_egress(DEVDBS["strict_pcf_bram_site"], bel)
    assert result.returncode == 0, transcript
    assert output.is_file()
    packed = json.loads(output.read_text())
    assert packed["modules"]["top"]["cells"]["ram"]["attributes"]["BEL"] == bel


@pytest.mark.parametrize("site_profile", [False, True])
def test_default_graph_packs_the_site_with_admitted_output(tmp_path, site_profile):
    result, transcript, output = _pack(tmp_path, "X13Y4_BRAM", site_profile)
    assert _has_output_egress(DEVDBS["strict_pcf"], "X13Y4_BRAM")
    assert result.returncode == 0, transcript
    assert output.is_file()


@pytest.mark.parametrize("bel", [f"X13Y{y}_BRAM" for y in (1, 2, 3)])
@pytest.mark.parametrize("site_profile", [False, True])
def test_packer_flag_cannot_supply_a_missing_graph_output(tmp_path, bel, site_profile):
    result, transcript, output = _pack(tmp_path, bel, site_profile)
    assert not _has_output_egress(DEVDBS["strict_pcf"], bel)
    assert result.returncode > 0, transcript
    assert "BRAM output DataOutA[0] reaches slice input pins in only 0 tile(s)" in transcript
    assert "std::out_of_range" not in transcript
    assert not output.exists()
