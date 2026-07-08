module top(input clk);
  wire h0,h1,h2,h3; (* keep *) MCU_DOUT a(.DOUT(h0)); (* keep *) MCU_DOUT b(.DOUT(h1));
  (* keep *) MCU_DOUT c(.DOUT(h2)); (* keep *) MCU_DOUT d(.DOUT(h3));
  reg [3:0] acc=0; always @(posedge clk) acc<=acc+4'd3;
  assign h0=acc[0];assign h1=acc[1];assign h2=acc[2];assign h3=acc[3];
endmodule
