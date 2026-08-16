// Qualified exact replay: INIT=0, DataInA[1]=1 witness, WeA absent.
module top(input clk);
  wire h0, h1, h2, h3, resetn;
  (* keep *) MCU_RESETN mcu_resetn(.RESETN(resetn));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(h2));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(h3));
  (* keep, BEL = "X14Y8_SLICE2", AGRV2K_OMUX_SEL = 0 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1))
    source_stage(.CLK(clk), .I({h2, 3'b000}), .F(), .Q(h1));
  (* keep, BEL = "X10Y4_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b1))
    state_stage(.CLK(clk), .I({h1, 3'b000}), .F(), .Q(h2));
  wire din1;
  (* keep *) GENERIC_SLICE #(.INIT(16'hffff), .FF_USED(1'b0))
    src_d1(.CLK(clk), .I(4'b0), .F(din1), .Q());
  wire [17:0] q;
  (* keep *) ALTA_BRAM9K #(
    .INIT_VAL(9216'b0), .PORTA_WIDTH(5'b00000), .PORTB_WIDTH(5'b00000),
    .CLKMODE(2'b10), .PORTA_CLKIN_EN(1'b1), .PORTA_CLKOUT_EN(1'b1),
    .PORTA_RSTIN_EN(1'b1), .PORTA_RSTOUT_EN(1'b1),
    .PORTB_CLKIN_EN(1'b0), .PORTB_CLKOUT_EN(1'b0),
    .PORTB_RSTIN_EN(1'b0), .PORTB_RSTOUT_EN(1'b0)
  ) mem (
    .AddressA(13'h00f), .DataInA({16'b0, din1, 1'b0}), .DataOutA(q),
    .WeA(1'b0), .ReA(1'b1), .ByteEnA(2'b11),
    .AddressB(13'b0), .DataInB(18'b0), .DataOutB(),
    .WeB(1'b0), .ReB(1'b0), .ByteEnB(2'b11),
    .Clk0(clk), .Clk1(clk), .ClkEn0(1'b1), .ClkEn1(1'b1),
    .AsyncReset0(resetn));
  assign h0 = q[1];
  (* keep, BEL = "X14Y12_SLICE0", AGRV2K_CARRY_CRL = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCCCC), .FF_USED(1'b0))
    path_observer(.CLK(clk), .I({2'b00, h1, h2}), .F(h3), .Q());
endmodule
