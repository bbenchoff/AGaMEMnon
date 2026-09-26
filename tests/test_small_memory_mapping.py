"""Real synthesis preserves explicit block requests and bounds soft RAM use."""
import json

import pytest

from test_bram_unmapped_memory_warning import _synth


def memory_source(depth, width, attribute=""):
    address_bits = (depth - 1).bit_length()
    return """
module top(input clk, input we, input [%d:0] addr,
           input [%d:0] din, output reg [%d:0] dout);
  %s reg [%d:0] mem [0:%d];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
""" % (address_bits - 1, width - 1, width - 1, attribute, width - 1, depth - 1)


@pytest.mark.parametrize("depth,width", [(32, 8), (64, 4), (8, 32)])
def test_small_writable_memory_uses_logic_without_source_attributes(tmp_path, depth, width):
    result = _synth(tmp_path, memory_source(depth, width), "small.v")
    assert result.returncode == 0, result.stdout
    module = json.loads((tmp_path / "small.v.json").read_text())["modules"]["top"]
    types = [cell["type"] for cell in module["cells"].values()]
    assert "ALTA_BRAM9K" not in types
    assert depth * width <= types.count("DFF") <= depth * width + width
    assert json.loads((tmp_path / "small.v.json.leftover_mem.json").read_text()) == ["top/mem"]


@pytest.mark.parametrize("depth,width,attribute", [
    (32, 8, '(* ram_style = "block" *)'),
    (512, 2, ""),
])
def test_explicit_block_or_deep_ram_stays_on_hard_memory(tmp_path, depth, width, attribute):
    result = _synth(tmp_path, memory_source(depth, width, attribute), "hard.v")
    assert result.returncode == 0, result.stdout
    module = json.loads((tmp_path / "hard.v.json").read_text())["modules"]["top"]
    assert sum(cell["type"] == "ALTA_BRAM9K" for cell in module["cells"].values()) == 1
    assert json.loads((tmp_path / "hard.v.json.leftover_mem.json").read_text()) == []
