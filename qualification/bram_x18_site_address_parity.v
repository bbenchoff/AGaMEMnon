// Constrained open-flow discriminator for the three non-default L48 BRAM sites.
//
// Each of the 512 native x18 Port-A words stores the parity of its nine-bit
// word address in DataOutA[0].  A single read lane therefore sensitizes every
// AddressA word-select input without requiring a wide BRAM-to-MCU exit.  The
// three tops differ only in the requested hard-block BEL.  This source is a
// qualification oracle, not a generic arbitrary-site support claim.
module bram_x18_site_address_parity #(
  parameter integer SITE = 1,
  parameter integer CONSTANT_ONE = 0
) (input clk);
  wire [8:0] word_address;
  (* keep *) MCU_DIN mcu_haddr2 (.DIN(word_address[0]));
  (* keep *) MCU_DIN mcu_haddr3 (.DIN(word_address[1]));
  (* keep *) MCU_DIN mcu_haddr4 (.DIN(word_address[2]));
  (* keep *) MCU_DIN mcu_haddr5 (.DIN(word_address[3]));
  (* keep *) MCU_DIN mcu_haddr6 (.DIN(word_address[4]));
  (* keep *) MCU_DIN mcu_haddr7 (.DIN(word_address[5]));
  (* keep *) MCU_DIN mcu_haddr8 (.DIN(word_address[6]));
  (* keep *) MCU_DIN mcu_haddr9 (.DIN(word_address[7]));
  (* keep *) MCU_DIN mcu_haddr10(.DIN(word_address[8]));
  wire hready;
  (* keep *) MCU_AHB_HREADY mcu_hready(.DIN(hready));

  function [9215:0] parity_init;
    integer word;
    begin
      parity_init = 9216'b0;
      for (word = 0; word < 512; word = word + 1)
        parity_init[word * 18 +: 18] = {17'b0,
          CONSTANT_ONE ? 1'b1 : ^word[8:0]};
    end
  endfunction

  wire [17:0] data_out;
  generate
    if (SITE == 1) begin : site_y1
      (* keep, BEL = "X13Y1_BRAM" *) ALTA_BRAM9K #(
        .INIT_VAL(parity_init()), .PORTA_WIDTH(5'b00000),
        .PORTB_WIDTH(5'b00000), .CLKMODE(2'b01),
        .PORTA_CLKIN_EN(1'b1), .PORTA_CLKOUT_EN(1'b1),
        .PORTA_RSTIN_EN(1'b1), .PORTA_RSTOUT_EN(1'b1),
        .PORTB_CLKIN_EN(1'b1), .PORTB_CLKOUT_EN(1'b1),
        .PORTB_RSTIN_EN(1'b1), .PORTB_RSTOUT_EN(1'b1)
      ) mem (
        .AddressA({word_address, 4'b1111}),
        .DataInA(18'b0), .DataOutA(data_out),
        .WeA(1'b0), .ReA(hready), .ByteEnA(2'b11),
        .Clk0(clk), .ClkEn0(hready),
        .AsyncReset0(1'b0));
    end else if (SITE == 2) begin : site_y2
      (* keep, BEL = "X13Y2_BRAM" *) ALTA_BRAM9K #(
        .INIT_VAL(parity_init()), .PORTA_WIDTH(5'b00000),
        .PORTB_WIDTH(5'b00000), .CLKMODE(2'b01),
        .PORTA_CLKIN_EN(1'b1), .PORTA_CLKOUT_EN(1'b1),
        .PORTA_RSTIN_EN(1'b1), .PORTA_RSTOUT_EN(1'b1),
        .PORTB_CLKIN_EN(1'b1), .PORTB_CLKOUT_EN(1'b1),
        .PORTB_RSTIN_EN(1'b1), .PORTB_RSTOUT_EN(1'b1)
      ) mem (
        .AddressA({word_address, 4'b1111}),
        .DataInA(18'b0), .DataOutA(data_out),
        .WeA(1'b0), .ReA(hready), .ByteEnA(2'b11),
        .Clk0(clk), .ClkEn0(hready),
        .AsyncReset0(1'b0));
    end else if (SITE == 3) begin : site_y3
      (* keep, BEL = "X13Y3_BRAM" *) ALTA_BRAM9K #(
        .INIT_VAL(parity_init()), .PORTA_WIDTH(5'b00000),
        .PORTB_WIDTH(5'b00000), .CLKMODE(2'b01),
        .PORTA_CLKIN_EN(1'b1), .PORTA_CLKOUT_EN(1'b1),
        .PORTA_RSTIN_EN(1'b1), .PORTA_RSTOUT_EN(1'b1),
        .PORTB_CLKIN_EN(1'b1), .PORTB_CLKOUT_EN(1'b1),
        .PORTB_RSTIN_EN(1'b1), .PORTB_RSTOUT_EN(1'b1)
      ) mem (
        .AddressA({word_address, 4'b1111}),
        .DataInA(18'b0), .DataOutA(data_out),
        .WeA(1'b0), .ReA(hready), .ByteEnA(2'b11),
        .Clk0(clk), .ClkEn0(hready),
        .AsyncReset0(1'b0));
    end else begin : site_y4
      (* keep, BEL = "X13Y4_BRAM" *) ALTA_BRAM9K #(
        .INIT_VAL(parity_init()), .PORTA_WIDTH(5'b00000),
        .PORTB_WIDTH(5'b00000), .CLKMODE(2'b01),
        .PORTA_CLKIN_EN(1'b1), .PORTA_CLKOUT_EN(1'b1),
        .PORTA_RSTIN_EN(1'b1), .PORTA_RSTOUT_EN(1'b1),
        .PORTB_CLKIN_EN(1'b1), .PORTB_CLKOUT_EN(1'b1),
        .PORTB_RSTIN_EN(1'b1), .PORTB_RSTOUT_EN(1'b1)
      ) mem (
        .AddressA({word_address, 4'b1111}),
        .DataInA(18'b0), .DataOutA(data_out),
        .WeA(1'b0), .ReA(hready), .ByteEnA(2'b11),
        .Clk0(clk), .ClkEn0(hready),
        .AsyncReset0(1'b0));
    end
  endgenerate

  generate
    if (SITE == 1) begin : observe_y1
      (* keep *) MCU_DOUT mcu_h8(.DOUT(data_out[0]));
    end else if (SITE == 2) begin : observe_y2
      (* keep *) MCU_DOUT mcu_h16(.DOUT(data_out[0]));
    end else if (SITE == 3) begin : observe_y3
      (* keep *) MCU_DOUT mcu_h24(.DOUT(data_out[0]));
    end else begin : observe_y4
      (* keep *) MCU_DOUT mcu_h0(.DOUT(data_out[0]));
    end
  endgenerate
endmodule

module top_y1(input clk);
  bram_x18_site_address_parity #(.SITE(1)) dut(.clk(clk));
endmodule

module top_y2(input clk);
  bram_x18_site_address_parity #(.SITE(2)) dut(.clk(clk));
endmodule

module top_y3(input clk);
  bram_x18_site_address_parity #(.SITE(3)) dut(.clk(clk));
endmodule

module top_y4(input clk);
  bram_x18_site_address_parity #(.SITE(4)) dut(.clk(clk));
endmodule

module top_y1_one(input clk);
  bram_x18_site_address_parity #(.SITE(1), .CONSTANT_ONE(1)) dut(.clk(clk));
endmodule

module top_y4_one(input clk);
  bram_x18_site_address_parity #(.SITE(4), .CONSTANT_ONE(1)) dut(.clk(clk));
endmodule
