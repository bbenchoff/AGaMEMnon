// Corpus-style async-reset design: a real design SHAPE, not a bare LED
// heartbeat -- a 15-bit free-running counter and a 4-state FSM, sharing one
// external asynchronous clear net, sized (17 registered bits total, > the
// packer's 16-slice-per-tile control-set chunk) so pack_shared_async_clear
// (agrv2k.cc) MUST split this one shared reset across more than one
// physical LogicTile, and the corpus proves the per-tile
// CtrlMUX->TileAsyncMUX01 route independently at each site it lands on, not
// just once.
//
// `led` is driven SOLELY by the counter's top bit -- a clean, single-
// frequency heartbeat at freq_hz/2^15 (305.2 Hz at the qualified 10 MHz
// reference, matching clk_rst_high/low's oracle style: cycles-per-edge =
// 2^15 = 32768). It must stop while `reset` is asserted and resume
// immediately after release (the silicon proof of the async clear). The
// FSM's state is exposed on a second pad (`fsm_msb`, unmeasured by the
// board job but real: it keeps yosys from optimizing the FSM away as dead
// logic) so it is genuinely present in the routed design, sharing the SAME
// reset net as the counter.
module clk_rst_multi_tile (input wire clock, input wire reset,
                            output wire led, output wire fsm_msb);
    // 15-bit free-running counter, async-cleared.
    reg [14:0] count;
    always @(posedge clock or posedge reset)
        if (reset) count <= 15'd0;
        else       count <= count + 15'd1;

    // 4-state FSM (2 FF), async-cleared on the SAME net, advances on the
    // counter's top bit so its period is a clean multiple of the counter's.
    localparam S0 = 2'b00, S1 = 2'b01, S2 = 2'b10, S3 = 2'b11;
    reg [1:0] state;
    always @(posedge clock or posedge reset)
        if (reset) state <= S0;
        else begin
            case (state)
                S0: state <= count[14] ? S1 : S0;
                S1: state <= !count[14] ? S2 : S1;
                S2: state <= count[14] ? S3 : S2;
                S3: state <= !count[14] ? S0 : S3;
                default: state <= S0;
            endcase
        end

    assign led = count[14];
    assign fsm_msb = state[1];
endmodule
