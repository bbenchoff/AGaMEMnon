// Archived inconclusive inter-tile carry seam probe. With the carry seed at slice 14,
// sum bit 0 is computed at slice 15 and sum bit 1 depends on the downward
// COUT15 -> CIN0 seam. Drive a=0 and a=1: the result must change 01 -> 10.
module top(input a, output y);
  wire a_buf;
  (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) input_buffer(
      .I({3'b000, a}), .Q(a_buf));
  (* keep *) wire [1:0] sum = {1'b0, a_buf} + 2'b01;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(sum[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(sum[1]));
  wire y_buf;
  (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) output_buffer(
      .I({3'b000, sum[1]}), .Q(y_buf));
  assign y = y_buf;
endmodule
