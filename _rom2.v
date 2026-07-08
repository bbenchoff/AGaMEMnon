module top(input clk);
  wire h0,h1,h2; (* keep *) MCU_DOUT a(.DOUT(h0)); (* keep *) MCU_DOUT b(.DOUT(h1)); (* keep *) MCU_DOUT c(.DOUT(h2));
  reg [8:0] addr=0; always @(posedge clk) addr<=addr+9'b1;
  reg [17:0] mem[0:511];
  integer i; initial for (i=0;i<512;i=i+1) mem[i]=i[17:0]^18'h2AA55;
  reg [17:0] dout; always @(posedge clk) dout<=mem[addr];
  assign h0=dout[0];assign h1=dout[1];assign h2=dout[2];
endmodule
