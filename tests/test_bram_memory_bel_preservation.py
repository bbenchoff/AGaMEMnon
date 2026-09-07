"""A memory placement constraint must survive lowering, or fail explicitly."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _memory(module, bel, width=1, addr=9):
    attributes = 'ram_style="block"' + (f', BEL="{bel}"' if bel is not None else '')
    return f'''module {module}(input clk, we, input [{addr-1}:0] addr,
        input [{width-1}:0] din, output reg [{width-1}:0] dout);
      (* {attributes} *) reg [{width-1}:0] mem [0:{(1 << addr)-1}];
      always @(posedge clk) begin
        if (we) mem[addr] <= din;
        dout <= mem[addr];
      end
    endmodule
    '''


def _synth(tmp_path, rtl):
    oss = os.environ.get("AGAMEMNON_OSS")
    binary = shutil.which("yosys")
    if oss:
        binary = next((str(path) for path in (Path(oss) / "bin/yosys", Path(oss) / "bin/yosys.exe")
                       if path.is_file()), binary)
    if not binary:
        pytest.skip("yosys absent")
    source, output = tmp_path / "source.v", tmp_path / "output.json"
    source.write_text(rtl)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGAMEMNON_", "AGRV2K_"))}
    if oss:
        env["YOSYSHQ_ROOT"] = oss + os.sep
        env["PATH"] = os.pathsep.join((str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")))
    env.update(AGAMEMNON_YOSYS_TOP="top", AGAMEMNON_YOSYS_JSON=str(output),
               AGAMEMNON_INTERNAL_PORTS="1")
    proc = subprocess.run([binary, "-q", "-c", str(ROOT / "agamemnon/synth/synth_pads.tcl"), str(source)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    log = proc.stdout + proc.stderr
    (tmp_path / "synthesis.log").write_text(log)
    cells = json.loads(output.read_text())["modules"]["top"]["cells"] if output.exists() else {}
    brams = {name: cell for name, cell in cells.items() if cell["type"] == "ALTA_BRAM9K"}
    return proc, log, brams


@pytest.mark.parametrize("bel", [f"X13Y{y}_BRAM" for y in range(1, 5)])
def test_memory_bel_survives_full_synthesis_at_each_site(tmp_path, bel):
    proc, log, brams = _synth(tmp_path, _memory("top", bel))
    assert proc.returncode == 0, log
    assert len(brams) == 1
    assert next(iter(brams.values()))["attributes"].get("BEL") == bel


@pytest.mark.parametrize("other_bel", [None, "X13Y2_BRAM"])
def test_constrained_memory_does_not_assign_other_memories(tmp_path, other_bel):
    rtl = _memory("left", "X13Y1_BRAM") + _memory("right", other_bel) + '''
      module top(input clk, we, input [8:0] addr, input [1:0] din, output [1:0] dout);
        left l(clk, we, addr, din[0], dout[0]);
        right r(clk, we, addr, din[1], dout[1]);
      endmodule
    '''
    proc, log, brams = _synth(tmp_path, rtl)
    assert proc.returncode == 0, log
    assert len(brams) == 2
    assert sorted((cell["attributes"].get("BEL") for cell in brams.values()), key=str) == \
        sorted(["X13Y1_BRAM", other_bel], key=str)


def test_unconstrained_memory_stays_unconstrained(tmp_path):
    proc, log, brams = _synth(tmp_path, _memory("top", None))
    assert proc.returncode == 0, log
    assert len(brams) == 1
    assert "BEL" not in next(iter(brams.values()))["attributes"]


def test_bracketed_memory_identifier_is_selected_exactly(tmp_path):
    rtl = _memory("top", "X13Y3_BRAM").replace("mem", "\\storage[3] ")
    proc, log, brams = _synth(tmp_path, rtl)
    assert proc.returncode == 0, log
    assert len(brams) == 1
    assert next(iter(brams.values()))["attributes"].get("BEL") == "X13Y3_BRAM"


def test_one_bel_is_not_copied_to_multiple_split_blocks(tmp_path):
    proc, log, _ = _synth(tmp_path, _memory("top", "X13Y4_BRAM", 18, 10))
    assert proc.returncode != 0
    assert "memory BEL constraint requires exactly one physical block" in log


@pytest.mark.parametrize("bel", ["X99Y99_BRAM", "X14Y4_SLICE0"])
def test_invalid_memory_bel_is_not_silently_lost(tmp_path, bel):
    proc, log, _ = _synth(tmp_path, _memory("top", bel))
    assert proc.returncode != 0
    assert "memory BEL constraint is not a device BRAM site" in log
