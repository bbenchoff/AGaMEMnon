// One-terminal-at-a-time x9 AddressA identity oracle.
//
// The BRAM is instantiated explicitly: an inferred ROM with only one live
// address input is correctly folded into a LUT by synthesis and therefore is
// not a valid terminal experiment.  All inactive terminals are coherently
// tied, including the native x9 AddressA[2:0] subselect of 3'b111.
//
// Logical word bit zero is address parity.  Consequently any electrically
// live word-address terminal changes the observed bit, independently of the
// terminal's actual decoded address identity.
module x9_one_terminal #(
  parameter HADDR_BIT = 2,
  parameter TERMINAL = 3
) (input clk);
  wire live_address;

  generate
    if (HADDR_BIT == 2) begin : source_haddr2
      (* keep *) MCU_DIN mcu_haddr2(.DIN(live_address));
    end else if (HADDR_BIT == 3) begin : source_haddr3
      (* keep *) MCU_DIN mcu_haddr3(.DIN(live_address));
    end else begin : source_haddr4
      (* keep *) MCU_DIN mcu_haddr4(.DIN(live_address));
    end
  endgenerate

  wire [12:0] address_a = 13'b0000000000111 |
                          ({12'b0, live_address} << TERMINAL);
  wire [17:0] data_out_a;

  function [9215:0] parity_init;
    integer word;
    begin
      parity_init = 9216'b0;
      for (word = 0; word < 1024; word = word + 1)
        parity_init[word * 9 +: 9] = {8'b0, ^word[9:0]};
    end
  endfunction

  (* keep *) ALTA_BRAM9K #(
    .INIT_VAL(parity_init()),
    .PORTA_WIDTH(5'b01000),
    .PORTB_WIDTH(5'b00000),
    .CLKMODE(2'b00)
  ) bram (
    .AddressA(address_a),
    .DataInA(18'b0),
    .DataOutA(data_out_a),
    .WeA(1'b0),
    .ReA(1'b1),
    .ByteEnA(2'b11),
    .AddressB(13'b0),
    .DataInB(18'b0),
    .DataOutB(),
    .WeB(1'b0),
    .ReB(1'b0),
    .ByteEnB(2'b00),
    .Clk0(clk),
    .Clk1(1'b0),
    .ClkEn0(1'b1),
    .ClkEn1(1'b0)
  );

  // x9 logical bit zero is the vendor-wrapper physical DataOutA[9] lane.
  wire observed;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    read_buffer(.CLK(clk), .I({3'b000, data_out_a[9]}), .F(observed), .Q());
  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule

module top_addr3(input clk);
  x9_one_terminal #(.HADDR_BIT(2), .TERMINAL(3)) dut(.clk(clk));
endmodule

module top_addr4(input clk);
  x9_one_terminal #(.HADDR_BIT(3), .TERMINAL(4)) dut(.clk(clk));
endmodule

module top_addr5(input clk);
  x9_one_terminal #(.HADDR_BIT(4), .TERMINAL(5)) dut(.clk(clk));
endmodule
