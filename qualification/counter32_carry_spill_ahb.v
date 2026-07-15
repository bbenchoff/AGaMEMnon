// Full vendor-observed 33-site carry-corridor qualification.  A large odd
// increment keeps the complete 32-bit ripple chain while making bit 31 toggle
// rapidly enough for the finite SRAM-only AHB sampler to observe it.
module top(input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));

  reg [31:0] cnt;
  always @(posedge clk)
    cnt <= cnt + 32'h01010101;

  assign h0 = cnt[0];
  assign h1 = cnt[31];
endmodule
