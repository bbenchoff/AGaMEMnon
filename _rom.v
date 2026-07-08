module top(input clk);
  wire h0,h1,h2; (* keep *) MCU_DOUT a(.DOUT(h0)); (* keep *) MCU_DOUT b(.DOUT(h1)); (* keep *) MCU_DOUT c(.DOUT(h2));
  reg [2:0] addr=0; always @(posedge clk) addr<=addr+3'b1;
  reg [17:0] mem[0:7];
  initial begin mem[0]=18'd0;mem[1]=18'd3;mem[2]=18'd5;mem[3]=18'd6;mem[4]=18'd1;mem[5]=18'd7;mem[6]=18'd2;mem[7]=18'd4; end
  reg [17:0] dout; always @(posedge clk) dout<=mem[addr];
  assign h0=dout[0];assign h1=dout[1];assign h2=dout[2];
endmodule
