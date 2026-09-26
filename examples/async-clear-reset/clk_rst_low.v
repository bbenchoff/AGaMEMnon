// Board-witnessed async-reset LED heartbeat, RTL-inverted (active-low reset
// input, active-high clear to zero at the flip-flop -- the same physical
// clear as clk_rst_high.v; see that file's header).
//
// Ported verbatim from AG32-Docs tools/vendor_witness/designs_open/clk_rst_low.v.
// The vendor image built from this exact RTL PASSED on silicon at 1220.7 Hz:
// edges = [1221, 1221, 1221]. Both polarities normalize to the SAME
// synthesized $_DFF_PP0_ class (yosys's `proc` pass canonicalizes them), so
// this design exercises the identical ASYNC_CLEAR_POS_ZERO admission path as
// clk_rst_high.v -- it exists to confirm that normalization, not to add a
// second physical case.
module clk_rst_low (input wire clock, input wire reset, output wire led);
    wire reset_n = ~reset;
    reg [12:0] hb;
    always @(posedge clock or negedge reset_n)
        if (!reset_n) hb <= 13'd0;
        else     hb <= hb + 13'd1;
    assign led = hb[12];
endmodule
