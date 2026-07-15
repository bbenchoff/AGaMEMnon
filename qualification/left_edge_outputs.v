// L48 left-edge output-bank qualification.  All four package pads at IOTILE
// (0,4) must route simultaneously through their vendor-observed feeder RMUXes.
module top(input clk, output [3:0] led);
  reg [3:0] q;
  always @(posedge clk)
    q <= ~q;
  assign led = q;
endmodule
