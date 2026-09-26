// Board-witnessed async-reset LED heartbeat, active-high polarity.
//
// Ported verbatim from AG32-Docs tools/vendor_witness/designs_open/clk_rst_high.v
// (gen_clock_modes.py, 2026-09-25 clock matrix session). The vendor image built
// from this exact RTL PASSED on silicon at 1220.7 Hz (tolerance 5%): edges =
// [1221, 1221, 1221]. This is the design the ASYNC_CLEAR_POS_ZERO admission
// (agrv2k.cc, AGRV2K_SHARED_CONTROL_ASYNC_CLEAR) exists to let the open flow
// build too. See ../../docs/ASYNC_CLEAR_RESET.md for the graph/codeword
// evidence and README.md in this directory for the build/board recipe.
//
// The if/else form (not `hb <= reset ? 0 : hb+1`) is required: both af.exe's
// and AGaMEMnon's own yosys throw "Multiple edge sensitive events found for
// this signal!" on the ternary form. This is a synthesis-idiom trap, not a
// silicon or place&route limitation.
module clk_rst_high (input wire clock, input wire reset, output wire led);
    reg [12:0] hb;
    always @(posedge clock or posedge reset)
        if (reset) hb <= 13'd0;
        else     hb <= hb + 13'd1;
    assign led = hb[12];
endmodule
