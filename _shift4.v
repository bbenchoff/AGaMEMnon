module top(input clk);
  wire h0,h1,h2,h3; (* keep *) MCU_DOUT a(.DOUT(h0)); (* keep *) MCU_DOUT b(.DOUT(h1));
  (* keep *) MCU_DOUT c(.DOUT(h2)); (* keep *) MCU_DOUT d(.DOUT(h3));
  reg t=0; always @(posedge clk) t<=~t;
  reg [3:0] s=0; always @(posedge clk) s<={s[2:0],t};
  assign h0=s[0];assign h1=s[1];assign h2=s[2];assign h3=s[3];
endmodule
