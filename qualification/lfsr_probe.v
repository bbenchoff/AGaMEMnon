// lfsr_probe.v (2026-09-17): bit-exact emission probe for arbitrary LUT/FF logic on silicon.
// An 8-bit prescaler enables a 16-bit Fibonacci LFSR (x^16+x^14+x^13+x^11, seed 0xACE1) once every
// 256 clocks; led = lfsr[0]. With a 10 MHz fabric clock the LFSR steps every 25.6 us, so a 2 us Pico
// capture sees each state ~12 times; the captured bit sequence must equal the software LFSR sequence.
// reset (active-high, PIN_15) reloads the seed; the LED is presented through a kept LUT buffer.
`default_nettype none
module top(input wire clock, input wire reset, output wire led);
    reg [7:0]  pre = 8'd0;
    reg [15:0] lfsr = 16'hACE1;
    wire fb = lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10];
    always @(posedge clock) begin
        if (reset) begin pre <= 8'd0; lfsr <= 16'hACE1; end
        else begin
            pre <= pre + 8'd1;
            if (pre == 8'hFF) lfsr <= {lfsr[14:0], fb};
        end
    end
    (* keep *) wire led_i;
    (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) o_buf(.CLK(), .I({3'b000, lfsr[0]}), .F(led_i), .Q());
    assign led = led_i;
endmodule
`default_nettype wire
