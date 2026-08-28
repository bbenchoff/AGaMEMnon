import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    found = shutil.which(name)
    if found:
        return Path(found)
    suite = ROOT.parent / "AG32-Docs" / "tools" / "oss-cad-suite" / "bin"
    for candidate in (suite / name, suite / f"{name}.exe"):
        if candidate.exists():
            return candidate
    return None


def test_read_master_wait_error_and_timeout_protocol(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_master.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s", "tb_fabric_ahb_read_master",
        "-o", str(image),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master.v"),
        str(ROOT / "examples" / "designs" / "tb_fabric_ahb_read_master.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert "PASS: reset-idle read master wait/error/timeout cases" in run.stdout


def test_read_master_cannot_issue_writes():
    source = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_master.v").read_text(encoding="utf-8")
    assert "assign HWRITE = 1'b0;" in source
    assert "assign HWDATA = 32'b0;" in source


def test_sram_base_lowering_uses_only_the_exact_request_profile():
    source = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_master_ag32_sram_base.v").read_text(
                  encoding="utf-8")
    assert "STATE_PRESENT" in source
    assert "if (hready_complete)" in source
    assert 'BEL="X14Y9_SLICE2"' in source
    assert "wire core_hsel = state[0]" in source
    assert "state0_ff" in source and ".CLK(hclk)" in source
    assert "0x20000000 and 0x20000004" in source
    assert "next_selected_word = word_select;" in source
    assert "selected_word_ff" in source
    # The two state slices appear in mutually exclusive ordinary/traced
    # generate branches; either elaborated design still contains 19 FFs.
    assert source.count(".FF_USED(1)") == 21
    assert source.count(") MCU_DOUT ") == 64
    assert source.count("(* keep *) MCU_SLAVE_AHB_") == 14
    assert 'BEL="X14Y7_SLICE14"' in source
    assert 'BEL="X18Y9_SLICE15"' in source
    assert 'BEL="X14Y12_DUAL_SLICE0"' in source
    assert "haddr0(.DOUT(control[4]))" in source
    assert "haddr1(.DOUT(control[6]))" in source
    assert "haddr2(.DOUT(haddr2_presented))" in source
    assert "haddr29(.DOUT(control[0]))" in source
    assert "source_hready" in source and "INIT(16'hFFFF)" in source
    assert "source_hwrite" in source and "INIT(16'h0000)" in source
    assert 'BEL="X14Y9_SLICE0"' in source
    assert ".I({hrdata0, hreadyout, hresp, 1'b0})" in source
    assert "INIT(16'h6996)" in source
    assert "one response signature bit" in source
    assert "MCU_SLAVE_AHB_HRDATA1" not in source


def test_research_build_can_fail_closed_on_selector_evidence():
    source = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert '"--require-clean-selectors", action="store_true"' in source
    assert 'default_devdb += "_clean_selectors"' in source
    assert '"AGAMEMNON_CLEAN_SEL_GATE=1" if require_clean_selectors' in source
    assert "if not research_unsafe or require_clean_selectors:" in source


def test_exact_read_observer_evidence_is_bounded_and_selector_clean():
    record = json.loads((ROOT / "qualification" /
                         "fabric_ahb_read_observer_evidence.jsonl").read_text(
                             encoding="utf-8"))
    assert record["build"] == "pass"
    assert record["hardware"] == "not-run"
    assert record["holdout_n"] == 0
    assert record["response_scope"] == (
        "one-xor-signature-bit-from-hreadyout-hresp-hrdata0")
    assert record["exact_route_edges"] == {
        "haddr01_retained_suffixes": 5,
        "haddr29": 4,
        "haddr2": 5,
        "independent_request_controls": 54,
        "response_hreadyout_hresp_hrdata0": 6,
    }
    assert record["route_data_pips"] == {
        "configurable_mapped": 178,
        "fixed_endpoints": 75,
        "legacy_absolute": 0,
        "predicted": 0,
        "total": 253,
        "unmapped": 0,
    }
    assert record["zero_regression_benchmark"]["predicted"] == 0
    assert record["zero_regression_benchmark"]["unmapped"] == 0


def test_sram_base_lowering_registered_presentation_simulation(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_master_ag32_sram_base.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s",
        "tb_fabric_ahb_read_master_ag32_sram_base", "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_master_ag32_sram_base.v"),
        str(ROOT / "examples" / "designs" /
            "tb_fabric_ahb_read_master_ag32_sram_base.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert ("PASS: exact-source SRAM-base read observer registered presentation"
            in run.stdout)


def test_mcu_readable_observer_endpoint_is_read_only_and_bounded():
    source = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_observer_endpoint.v").read_text(
                  encoding="utf-8")
    assert "parameter REQUEST_ENABLE = 1'b1" in source
    assert "request_arm_source" in source
    assert "REQUEST_ENABLE ? 16'hffff : 16'h0000" in source
    assert ".start(start_pulse)" in source
    assert ".word_select(latched_word_select)" in source
    assert "MCU_DIN command_haddr2" in source
    assert "MCU_DIN command_htrans1_input" in source
    assert "command_pending && !command_htrans1 && !busy" in source
    assert "command_htrans1 && !busy && !command_pending" in source
    assert "command_word_select != latched_word_select" in source
    assert "0x60000000 and 0x60000004" in source
    assert source.count("MCU_DOUT observer_h") == 4
    assert "MCU_AHB_HREADYOUT" in source
    assert "MCU_AHB_HRESP" in source
    assert "MCU_AHB_HWRITE" not in source
    assert "sample a sequence" in source
    assert "status word" in source
    assert ".response_sampled(response_sampled)" in source
    assert ".response_valid(response_valid)" in source


def test_mcu_readable_observer_endpoint_bounds_reads_by_transactions(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_observer_endpoint.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s",
        "tb_fabric_ahb_read_observer_endpoint", "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_master_ag32_sram_base.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_observer_endpoint.v"),
        str(ROOT / "examples" / "designs" /
            "tb_fabric_ahb_read_observer_endpoint.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert ("PASS: transaction-triggered fabric AHB observer endpoint cadence"
            in run.stdout)


def test_pico_trace_wrapper_timeline_and_sparse_lane_contract(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_observer_pico_trace.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s",
        "tb_fabric_ahb_read_observer_pico_trace", "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_master_ag32_sram_base.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_observer_endpoint.v"),
        str(ROOT / "examples" / "designs" /
            "fabric_ahb_read_observer_pico_trace.v"),
        str(ROOT / "examples" / "designs" /
            "tb_fabric_ahb_read_observer_pico_trace.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert "PASS: Pico trace crossed master-state/pending/start timeline" in run.stdout

    wrapper = (ROOT / "examples" / "designs" /
               "fabric_ahb_read_observer_pico_trace.v").read_text(
                   encoding="utf-8")
    constraints = (ROOT / "examples" / "constraints" /
                   "fabric_ahb_read_observer_pico_trace_L48.pcf").read_text(
                       encoding="utf-8")
    assert "trace_command_pending,\n    trace_start_pulse,\n    trace_master_state1,\n    trace_master_state0" in wrapper
    assert constraints.splitlines() == [
        "set_io trace[0] PIN_25",
        "set_io trace[1] PIN_26",
        "set_io trace[2] PIN_27",
        "set_io trace[3] PIN_28",
    ]
    # Harness truth for CAP8 base 12 is sparse: GP12, GP13, GP16, GP17.
    assert sum(1 << bit for bit in (0, 1, 4, 5)) == 0x33


def test_pico_raw_registered_state_compare_timeline_and_pin_contract(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_observer_pico_state_compare.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s",
        "tb_fabric_ahb_read_observer_pico_state_compare", "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_master_ag32_sram_base.v"),
        str(ROOT / "agamemnon" / "rtl" /
            "fabric_ahb_read_observer_endpoint.v"),
        str(ROOT / "examples" / "designs" /
            "fabric_ahb_read_observer_pico_state_compare.v"),
        str(ROOT / "examples" / "designs" /
            "tb_fabric_ahb_read_observer_pico_state_compare.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert "PASS: Pico raw/registered master-state comparison timeline" in run.stdout

    wrapper = (ROOT / "examples" / "designs" /
               "fabric_ahb_read_observer_pico_state_compare.v").read_text(
                   encoding="utf-8")
    constraints = (ROOT / "examples" / "constraints" /
                   "fabric_ahb_read_observer_pico_state_compare_L48.pcf").read_text(
                       encoding="utf-8")
    assert "registered_master_state[0]" in wrapper
    assert "registered_master_state[1]" in wrapper
    assert "raw_master_state[0]" in wrapper
    assert "raw_master_state[1]" in wrapper
    master = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_master_ag32_sram_base.v").read_text(
                  encoding="utf-8")
    assert ".TRACE_STATE_OUTPUT(1'b1)" in wrapper
    assert 'BEL="X14Y11_SLICE4"' in master
    assert 'BEL="X14Y11_SLICE5"' in master
    assert 'BEL="X14Y11_SLICE6"' in wrapper
    assert 'BEL="X14Y11_SLICE7"' in wrapper
    assert wrapper.count(".FF_USED(1)") == 2
    assert constraints.splitlines() == [
        "set_io trace[0] PIN_25",
        "set_io trace[1] PIN_26",
        "set_io trace[2] PIN_27",
        "set_io trace[3] PIN_28",
    ]


def test_ag32_wrapper_binds_every_hard_boundary_lane():
    source = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_master_ag32.v").read_text(encoding="utf-8")
    assert "agamemnon_fabric_ahb_read_master" in source
    controls = [
        "HSEL", "HREADY", "HTRANS0", "HTRANS1", "HSIZE0", "HSIZE1",
        "HSIZE2", "HBURST0", "HBURST1", "HBURST2", "HWRITE",
    ]
    for control in controls:
        assert f"MCU_SLAVE_AHB_{control} " in source
    for lane in range(32):
        assert f"mcu_slave_haddr{lane}(.DOUT(haddr[{lane}]))" in source
        assert f"mcu_slave_hwdata{lane}(.DOUT(hwdata[{lane}]))" in source
        assert f"MCU_SLAVE_AHB_HRDATA{lane} mcu_slave_hrdata{lane}" in source
    assert "MCU_SLAVE_AHB_HREADYOUT" in source
    assert "MCU_SLAVE_AHB_HRESP" in source


def test_ag32_wrapper_reset_idle_zero_wait_simulation(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_master_ag32.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s", "tb_fabric_ahb_read_master_ag32",
        "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master.v"),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master_ag32.v"),
        str(ROOT / "examples" / "designs" /
            "tb_fabric_ahb_read_master_ag32.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert "PASS: AG32 read-master wrapper reset-idle zero-wait binding" in run.stdout
