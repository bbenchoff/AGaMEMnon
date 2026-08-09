import csv
import json
import os
from agamemnon.engine import chipdb_schema
import re
import shutil
import subprocess

import pytest
from agamemnon.engine import bram_emit


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIPDB = os.path.join(ROOT, "agamemnon", "chipdb")


def test_portb_vendor_oracle_config_is_byte_exact():
    """The dynamic Port-B vendor oracle sets exactly these five BRAM-family bits."""
    enables = {
        "PORTB_CLKIN_EN": 1,
        "PORTB_CLKOUT_EN": 1,
        "PORTB_RSTIN_EN": 1,
        "PORTB_RSTOUT_EN": 1,
    }
    emitted = bram_emit.emit(13, 4, 0, 0b10, 0, enables, width_b=0)
    assert emitted == {
        (68078, 128),  # PORTB_CLKIN_EN
        (69238, 128),  # PORTB_CLKOUT_EN
        (71558, 64),   # CLKMODE[1]
        (72950, 128),  # PORTB_RSTIN_EN
        (73414, 128),  # PORTB_RSTOUT_EN
    }


def test_bram_owned_surface_covers_emitted_fields_but_not_unknown_controls():
    surface = bram_emit.owned_surface(13, 4)
    assert len(surface) == 9236  # 9216 INIT + 5+5 width + 2 clock + 8 gates
    for mux in bram_emit.OWNED_MUXES:
        assert set(bram_emit.CELLS[(13, 4, mux)].values()) <= surface
    for mux in ("CFG_PACKEDMODE", "CFG_DLYTIME", "CFG_RSEN_DLY"):
        assert surface.isdisjoint(bram_emit.CELLS[(13, 4, mux)].values())


def test_experimental_bram_surface_is_separate_and_complete():
    release = bram_emit.owned_surface(13, 4)
    experimental = bram_emit.owned_surface(13, 4, experimental=True)
    added = experimental - release
    assert len(added) == 9
    assert added == {
        bit for mux in bram_emit.EXPERIMENTAL_OWNED_MUXES
        for bit in bram_emit.CELLS[(13, 4, mux)].values()
    }


def test_bitgen_preserves_portb_gate_parameters():
    """Live DataOutB use must not silently change the primitive's gate mode."""
    source = os.path.join(ROOT, "agamemnon", "engine", "features", "bram.py")
    text = open(source, encoding="utf-8").read()
    assert "portb_read = any(" in text
    assert 'enables["PORTB_%s_EN" % sig] = 1' not in text
    assert 'enables[name] = _param_int(parameters, name, 0) or 0' in text
    assert "state.clears.extend(bram_emit.owned_surface(" in text
    assert "experimental=experimental_enabled" in text


def test_uarch_drops_only_a_completely_unused_portb_input_surface():
    source = os.path.join(
        ROOT, "agamemnon", "engine", "uarch", "agrv2k", "agrv2k.cc"
    )
    text = open(source, encoding="utf-8").read()
    assert "port_b_read_used" in text
    assert "port_b_write_used" in text
    assert "!port_b_read_used && !port_b_write_used" in text
    assert "unused BRAM Port B -> disconnected constant input surface" in text


def test_portb_width_has_an_independent_encoding():
    port_a_x18 = bram_emit.emit(13, 4, 0, 0, 0, {}, width_b=0)
    port_b_x9 = bram_emit.emit(13, 4, 0, 0, 0, {}, width_b=0b01000)
    assert port_a_x18 == set()
    assert port_b_x9 == {(72254, 64)}


@pytest.mark.parametrize("code", [0b00000, 0b01000, 0b01100, 0b01110, 0b01111])
def test_direct_bram_width_domain_accepts_only_lowered_modes(code):
    bram_emit.emit(13, 4, code, 0, 0, {}, width_b=code)


@pytest.mark.parametrize("port,kwargs", [
    ("A", {"width": 0b00001, "width_b": 0}),
    ("B", {"width": 0, "width_b": 0b00001}),
])
def test_model_invalid_bram_width_fails_before_emission(port, kwargs):
    with pytest.raises(ValueError, match=rf"PORT{port}_WIDTH code 00001"):
        bram_emit.emit(13, 4, clkmode=0, init_val=0, enables={}, **kwargs)


def test_direct_x36_candidate_requires_experimental_gate():
    with pytest.raises(ValueError, match="AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG"):
        bram_emit.emit(13, 4, 0b10000, 0, 0, {})


def test_experimental_bram_config_is_exact_and_opt_in():
    fields = {"DLYTIME": 0b11}
    with pytest.raises(ValueError, match="AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG"):
        bram_emit.emit(13, 4, 0, 0, 0, {}, experimental=fields)
    emitted = bram_emit.emit(
        13, 4, 0, 0, 0, {},
        experimental=fields, allow_experimental=True,
    )
    expected = {
        bram_emit.CELLS[(13, 4, "CFG_DLYTIME")][0],
        bram_emit.CELLS[(13, 4, "CFG_DLYTIME")][1],
    }
    assert emitted == expected


def test_experimental_bram_config_fails_closed_outside_admitted_scope():
    with pytest.raises(ValueError, match="RSEN_DLY"):
        bram_emit.emit(13, 4, 0, 0, 0, {},
                       experimental={"RSEN_DLY": 3}, allow_experimental=True)
    with pytest.raises(ValueError, match="X13Y1..Y4"):
        bram_emit.emit(12, 4, 0, 0, 0, {}, allow_experimental=True)


def test_experimental_bram_config_rejects_unadmitted_compositions():
    with pytest.raises(ValueError, match="at most one B4 experimental config row"):
        bram_emit.emit(13, 4, 0b10000, 0, 0, {}, width_b=0b10000,
                       allow_experimental=True)
    with pytest.raises(ValueError, match="at most one B4 experimental config row"):
        bram_emit.emit(13, 4, 0b10000, 0, 0, {},
                       experimental={"PACKEDMODE": 1}, allow_experimental=True)
    with pytest.raises(ValueError, match="at most one B4 experimental config row"):
        bram_emit.emit(13, 4, 0, 0, 0, {},
                       experimental={"PORTA_OUTREG": 1, "DLYTIME": 1},
                       allow_experimental=True)


def test_portb_bel_has_every_recovered_routable_pin():
    with open(os.path.join(CHIPDB, "bram9k_bel.csv"), newline="") as handle:
        rows = list(csv.DictReader(handle))
    pins = {(r["port"], int(r["bit"])): r["res"] for r in rows}

    assert [pins[("AddressB", bit)] for bit in range(13)] == [
        "IMUX%02d" % bit for bit in range(51, 64)
    ]
    assert [pins[("DataInB", bit)] for bit in range(18)] == [
        "IMUX%02d" % bit for bit in range(33, 51)
    ]
    assert [pins[("DataOutB", bit)] for bit in range(18)] == [
        "BufMUX%02d" % bit for bit in list(range(16, 24)) + [34] + list(range(24, 32)) + [35]
    ]
    assert pins[("ByteEnB", 0)] == "KMUX08"
    assert pins[("ByteEnB", 1)] == "KMUX09"
    assert pins[("WeB", 0)] == "KMUX00"
    assert pins[("ReB", 0)] == "KMUX07"
    assert pins[("ClkEn1", 0)] == "TileClkEnMUX01"


def test_portb_read_replaces_the_porta_kmux_select():
    source = os.path.join(ROOT, "agamemnon", "engine", "features", "bram.py")
    text = open(source, encoding="utf-8").read()
    assert '"bram_portb_read_ctrl.csv"' in text
    assert "bit == (69006, 2)" in text
    assert "KMUX71 -> KMUX62" in text


def test_portb_vendor_approach_edges_are_exact_and_conducting():
    expected = {
        (14, 8, 50, 14, 4, 18): (6, 9),
        (14, 8, 44, 14, 4, 90): (6, 9),
        (14, 7, 50, 14, 4, 12): (5, 9),
        (14, 7, 80, 14, 4, 42): (5, 9),
    }
    with open(os.path.join(CHIPDB, "rrg_edges_full.csv"), newline="") as handle:
        rows = list(csv.DictReader(handle))
    observed = {}
    for row in rows:
        if row["src_res"].startswith("RMUX") and row["dst_res"].startswith("RMUX"):
            key = (int(row["src_x"]), int(row["src_y"]), int(row["src_res"][4:]),
                   int(row["dst_x"]), int(row["dst_y"]), int(row["dst_res"][4:]))
            if key in expected:
                observed[key] = tuple(int(v) for v in row["cfg"].split("[")[1].rstrip("]").split(","))
                assert row["source"] == "observed"
    assert observed == expected

    with open(os.path.join(CHIPDB, "master_conduction.csv"), newline="") as handle:
        conducting = {(int(r["src_x"]), int(r["src_y"]), int(r["src_res"][4:]),
                       int(r["dst_x"]), int(r["dst_y"]), int(r["dst_res"][4:]))
                      for r in csv.DictReader(handle)
                      if r["src_res"].startswith("RMUX") and r["dst_res"].startswith("RMUX")}
    assert set(expected) <= conducting

    datasets, _ = chipdb_schema.load(
        os.path.join(CHIPDB, "sel_edge_pairs.agdb"), expected=("clean_edge",)
    )
    exact = datasets["clean_edge"]
    clean = set(list(expected)[:2])
    for edge, pair in expected.items():
        sx, sy, si, dx, dy, di = edge
        key = (dx, dy, "RMUX", di, "RMUX", sx, sy, si)
        if edge in clean:
            assert tuple(exact[key]) == pair
        else:
            # The electrical edge remains positive evidence, but conflicting
            # selector attribution keeps it out of the release clean table.
            assert key not in exact


def test_portb_silicon_corridors_have_exact_edges_and_selector_bits():
    with open(os.path.join(CHIPDB, "bram_portb_corridors.csv"), newline="") as handle:
        corridors = list(csv.DictReader(handle))
    assert len([r for r in corridors if r["port"] == "AddressB"]) == 13
    assert {(r["port"], r["bit"]) for r in corridors if r["port"] == "DataOutB"} == {
        ("DataOutB", "1"), ("DataOutB", "2")
    }
    assert {r["evidence"] for r in corridors} == {
        "vendor-internal-counter-x2-silicon",
        "vendor-independent-fabric-portb-bus-route",
    }

    with open(os.path.join(CHIPDB, "bram9k_edges.csv"), newline="") as handle:
        edges = {(r["src_tile"], r["src_x"], r["src_y"], r["src_res"],
                  r["dst_tile"], r["dst_x"], r["dst_y"], r["dst_res"])
                 for r in csv.DictReader(handle)}
    with open(os.path.join(CHIPDB, "bram_pip_cfg.csv"), newline="") as handle:
        cfg = {(r["dst_res"], r["src_res"], r["ddx"], r["ddy"])
               for r in csv.DictReader(handle)}
    with open(os.path.join(CHIPDB, "bram_resolver.json")) as handle:
        resolver = json.load(handle)
    for row in corridors:
        edge = tuple(row[k] for k in ("src_tile", "src_x", "src_y", "src_res",
                                      "dst_tile", "dst_x", "dst_y", "dst_res"))
        assert edge in edges
        dst = row["dst_res"].rstrip("0123456789") + str(int(row["dst_res"].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")))
        src = row["src_res"].rstrip("0123456789") + str(int(row["src_res"].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")))
        ddx = str(int(row["dst_x"]) - int(row["src_x"]))
        ddy = str(int(row["dst_y"]) - int(row["src_y"]))
        key = (dst, src, ddx, ddy)
        dm = re.match(r"([A-Za-z]+)(\d+)", dst)
        sm = re.match(r"([A-Za-z]+)(\d+)", src)
        resolvable = False
        if dm and sm and dm.group(1) in resolver["NPI"]:
            df, di = dm.group(1), int(dm.group(2))
            sf, si = sm.group(1), int(sm.group(2))
            go = di % resolver["NPI"][df]
            keys = (
                "|".join(map(str, (df, di, sf, si, int(ddx), int(ddy)))),
                "|".join(map(str, (df, go, sf, si, int(ddx), int(ddy)))),
                "|".join(map(str, (df, sf, int(ddx), int(ddy), si % 16))),
            )
            resolvable = (keys[0] in resolver["L0"] or
                          keys[1] in resolver["L1"] or
                          keys[2] in resolver["L2"])
        assert key in cfg or resolvable
        # x2 uses physical DataOutB lanes 1 and 2.  Its complete active read
        # boundary and all independent address terminals have direct oracle
        # codewords rather than a generalized selector fallback.
        if row["port"] == "AddressB" or (row["port"] == "DataOutB" and row["bit"] in {"1", "2"}):
            assert key in cfg

    # These two graph-adjacent alternatives produced a static open image and
    # must remain excluded by arch.py's default corridor gate.
    arch = open(os.path.join(
        ROOT, "agamemnon", "engine", "features", "bram.py"
    ), encoding="utf-8").read()
    assert "_outside_bram_corridor(r)" in arch


def test_x9_data5_uses_the_silicon_qualified_direct_corridor():
    """The old BufMUX13->RMUX75 edge drove a static lane on silicon."""
    with open(os.path.join(CHIPDB, "bram9k_edges.csv"), newline="") as handle:
        edges = {
            (row["src_x"], row["src_y"], row["src_res"],
             row["dst_x"], row["dst_y"], row["dst_res"])
            for row in csv.DictReader(handle)
        }
    assert ("13", "4", "BufMUX13", "14", "4", "RMUX92") in edges
    assert ("13", "4", "BufMUX13", "14", "4", "RMUX75") not in edges

    with open(os.path.join(CHIPDB, "bram_pip_cfg.csv"), newline="") as handle:
        cfg = list(csv.DictReader(handle))
    q5 = [row for row in cfg
          if row["dst_res"] == "RMUX92" and row["src_res"] == "BufMUX13"
          and row["ddx"] == "1" and row["ddy"] == "0"]
    assert {(int(row["byte"]), int(row["mask"])) for row in q5} == {
        (73510, 4), (73626, 64)
    }
    assert not [row for row in cfg
                if row["dst_res"] == "RMUX75" and row["src_res"] == "BufMUX13"
                and row["ddx"] == "1" and row["ddy"] == "0"]

    with open(os.path.join(CHIPDB, "master_conduction.csv"), newline="") as handle:
        conduction = {
            (row["src_res"], row["src_x"], row["src_y"],
             row["dst_res"], row["dst_x"], row["dst_y"])
            for row in csv.DictReader(handle)
        }
    assert ("RMUX92", "14", "4", "RMUX75", "14", "8") in conduction
    assert ("RMUX75", "14", "8", "RMUX20", "14", "12") in conduction

    with open(os.path.join(CHIPDB, "bram_x9_data5_paths.csv"), newline="") as handle:
        paths = list(csv.DictReader(handle))
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y4_BufMUX13", "X14Y4_RMUX92"),
        ("X14Y4_RMUX92", "X14Y8_RMUX75"),
        ("X14Y8_RMUX75", "X14Y12_RMUX20"),
        ("X14Y12_RMUX20", "X13Y12_BBMUXE07"),
        ("X13Y12_BBMUXE07", "X0Y5_SinkMUXPseudo07"),
    ]
    with open(os.path.join(CHIPDB, "bram_x9_data5_pip_cfg.csv"), newline="") as handle:
        fields = list(csv.DictReader(handle))
    assert [(row["cfg_group"], row["set_selectors"]) for row in fields] == [
        ("CFG_RMUX12", "32;39"), ("CFG_RMUX3", "22;29")
    ]
    with open(os.path.join(CHIPDB, "bram_x9_data5_mcu_exit.csv"), newline="") as handle:
        exit_row = next(csv.DictReader(handle))
    assert (exit_row["src_res"], exit_row["edge_res"], exit_row["selectors"]) == (
        "RMUX20", "BBMUXE07", "2;6"
    )


def test_x9_data4_simultaneous_alternate_has_complete_exact_footprint():
    """q4 leaves the shared RMUX92 through its silicon-qualified alternate."""
    with open(os.path.join(CHIPDB, "bram9k_edges.csv"), newline="") as handle:
        edges = {
            (row["src_x"], row["src_y"], row["src_res"],
             row["dst_x"], row["dst_y"], row["dst_res"])
            for row in csv.DictReader(handle)
        }
    assert ("13", "4", "BufMUX12", "14", "4", "RMUX75") in edges
    with open(os.path.join(CHIPDB, "bram_pip_cfg.csv"), newline="") as handle:
        cfg = list(csv.DictReader(handle))
    q4 = [row for row in cfg
          if row["dst_res"] == "RMUX75" and row["src_res"] == "BufMUX12"
          and row["ddx"] == "1" and row["ddy"] == "0"]
    assert {(int(row["byte"]), int(row["mask"])) for row in q4} == {
        (71886, 2), (72003, 64), (72814, 2), (72815, 32)
    }
    with open(os.path.join(CHIPDB, "bram_x9_data4_mcu_exit.csv"),
              newline="") as handle:
        exit_row = next(csv.DictReader(handle))
    assert (exit_row["src_res"], exit_row["edge_res"], exit_row["selectors"]) == (
        "RMUX43", "BBMUXE06", "1;6"
    )
    with open(os.path.join(CHIPDB, "bram_x9_data4_simultaneous_paths.csv"),
              newline="") as handle:
        path = [(row["src_wire"], row["dst_wire"])
                for row in csv.DictReader(handle)]
    assert path == [
        ("X13Y4_BufMUX12", "X14Y4_RMUX75"),
        ("X14Y4_RMUX75", "X14Y8_RMUX15"),
        ("X14Y8_RMUX15", "X15Y8_RMUX62"),
        ("X15Y8_RMUX62", "X15Y12_RMUX56"),
        ("X15Y12_RMUX56", "X14Y12_RMUX43"),
        ("X14Y12_RMUX43", "X13Y12_BBMUXE06"),
        ("X13Y12_BBMUXE06", "X0Y5_SinkMUXPseudo06"),
    ]
    uarch = open(os.path.join(
        ROOT, "agamemnon", "engine", "uarch", "agrv2k", "agrv2k.cc"),
        encoding="utf-8").read()
    assert "pre-routed simultaneous x9 q4 over %d exact pip(s)" in uarch


def test_x9_data5_complementary_source_corridor_is_experiment_gated():
    arch = open(os.path.join(
        ROOT, "agamemnon", "engine", "features", "mcu_ahb.py"
    ),
                encoding="utf-8").read()
    assert 'os.environ.get("AGAMEMNON_X9_Q5_ALT_EXPERIMENT")' in arch
    with open(os.path.join(CHIPDB, "bram_x9_data5_alt_candidate_paths.csv"),
              newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["src_wire"], row["dst_wire"]) for row in rows] == [
        ("X13Y4_BufMUX13", "X14Y4_RMUX75"),
        ("X14Y4_RMUX75", "X14Y8_RMUX15"),
        ("X14Y8_RMUX15", "X15Y8_RMUX69"),
        ("X15Y8_RMUX69", "X15Y12_RMUX93"),
        ("X15Y12_RMUX93", "X14Y12_RMUX86"),
        ("X14Y12_RMUX86", "X13Y12_BBMUXE07"),
        ("X13Y12_BBMUXE07", "X0Y5_SinkMUXPseudo07"),
    ]
    assert {row["evidence"] for row in rows} == {
        "vendor-routed-source-plus-corpus-downstream-not-qualified"
    }
    with open(os.path.join(
            CHIPDB, "bram_x9_data5_alt_candidate_pip_cfg.csv"),
            newline="") as handle:
        cfg = list(csv.DictReader(handle))
    assert [(int(row["byte"]), int(row["mask"])) for row in cfg] == [
        (71886, 2), (72003, 64), (72814, 2), (72931, 32)
    ]
    feature = open(os.path.join(ROOT, "agamemnon", "engine", "features", "bram.py"),
                   encoding="utf-8").read()
    assert 'options.enabled("AGAMEMNON_X9_Q5_ALT_EXPERIMENT")' in feature


def _yosys():
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for ext in ("", ".exe"):
            candidate = os.path.join(oss, "bin", "yosys" + ext)
            if os.path.exists(candidate):
                return candidate
    return shutil.which("yosys")


def test_yosys_infers_one_dual_read_bram(tmp_path):
    yosys = _yosys()
    if not yosys:
        pytest.skip("yosys absent (set AGAMEMNON_OSS or put yosys on PATH)")
    source = tmp_path / "dual_read.v"
    output = tmp_path / "dual_read.json"
    source.write_text("""
module top(input clk, input [8:0] a, input [8:0] b, output reg [1:0] qa, output reg [1:0] qb);
  (* ram_style = "block" *) reg [1:0] mem [0:511];
  integer i;
  initial for (i = 0; i < 512; i = i + 1) mem[i] = i[1:0];
  always @(posedge clk) begin qa <= mem[a]; qb <= mem[b]; end
endmodule
""")
    synth = os.path.join(ROOT, "agamemnon", "synth", "synth_pads.tcl")
    env = dict(os.environ)
    oss = env.get("AGAMEMNON_OSS")
    if oss:
        env["YOSYSHQ_ROOT"] = oss + os.sep
        env["PATH"] = os.path.join(oss, "bin") + os.pathsep + os.path.join(oss, "lib") + \
                      os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [yosys, "-q", "-p", "tcl %s 4 %s" % (synth, output), str(source)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout
    module = json.loads(output.read_text())["modules"]["top"]
    brams = [cell for cell in module["cells"].values() if cell["type"] == "ALTA_BRAM9K"]
    assert len(brams) == 1
    assert brams[0]["parameters"]["PORTA_WIDTH"] == "01110"
    assert brams[0]["parameters"]["PORTB_WIDTH"] == "01110"
    assert brams[0]["connections"]["AddressB"]
    assert brams[0]["connections"]["DataOutB"]
    # x2 physical addressing appends one selected low bit; logical read data
    # returns on physical DataOut[2:1], exactly as the vendor alta_ram9k wrapper.
    addr_b = brams[0]["connections"]["AddressB"]
    assert addr_b[0] == "1"
    # synth_pads inserts an output pad between the top-level qb port and the
    # BRAM.  Its pre-pad net is the logical read value produced by techmap.
    port_b_read = module["netnames"]["$iopadmap$qb"]["bits"]
    physical_b = brams[0]["connections"]["DataOutB"]
    assert physical_b[1:3] == port_b_read
