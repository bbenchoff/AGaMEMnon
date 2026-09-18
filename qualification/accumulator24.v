`default_nettype none
module top(input wire clock, input wire reset, output wire led);
  // acc_probe core (2026-09-17): a 32-bit LFSR (x^32+x^22+x^2+x^1, self-seeding) feeds a 24-bit accumulator
  // every cycle; a 12-bit prescaler samples acc[23] into the LED FF every 4096 cycles. Exercises the carry
  // chain (24-bit add), XOR/LUT logic and a wide fanout. LED pattern is deterministic; Fmax is where the
  // accumulator's carry path or the LFSR fails. reset = pad, registered once inside the fabric.
  reg rst_r = 1'b1;
  reg [31:0] lfsr = 32'd0;
  reg [23:0] acc  = 32'd0;
  reg [11:0] pre  = 12'd0;
  reg        led_r = 1'b0;
  wire fb = lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0];
  always @(posedge clock) begin
      rst_r <= reset;
      // v2 (2026-09-17): the accumulator is reset-free so SUM drives its FF directly (the open packer only
      // fuses a register into a carry slice when D = SUM); reset zeroes the addend; the checker solves the accumulator start value.
      acc <= acc + (rst_r ? 32'd0 : lfsr);
      if (rst_r) begin lfsr <= 32'd0; pre <= 12'd0; led_r <= 1'b0; end
      else begin
          lfsr <= (lfsr == 32'd0) ? 32'hDEADBEEF : {lfsr[30:0], fb};
          pre  <= pre + 12'd1;
          if (pre == 12'hFFF) led_r <= acc[23];
      end
  end
  (* keep *) wire led_i;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) o_buf(.CLK(), .I({3'b000, led_r}), .F(led_i), .Q());
  assign led = led_i;
endmodule
`default_nettype wire
