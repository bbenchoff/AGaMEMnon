// Same-slice discriminator for the vendor x9 q3 readback corridor.
// HADDR[2] drives X14Y4 slice0 I0; F exits on MCU HRDATA[3].
module top(input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));

  wire h3;
  (* keep *) MCU_DOUT mcu_h3(.DOUT(h3));

  (* keep, BEL="X14Y4_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    same_site_buffer(.CLK(clk), .I({3'b000, ahb_word[0]}), .F(h3), .Q());
endmodule
