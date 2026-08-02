// Hardware-free routing smoke test for the recovered External AHB controls.
// The response equations are intentionally not a legal peripheral. Do not
// load this image on hardware; use the protocol-qualified endpoint instead.
module top;
  wire hready, htrans0, htrans1, hwrite;
  wire [2:0] hsize, hburst;
  wire haddr24, haddr25;
  wire htrans0_buf, hsize0_buf, hreadyout_buf;

  (* keep *) MCU_AHB_HREADY  mcu_hready  (.DIN(hready));
  (* keep *) MCU_AHB_HTRANS0 mcu_htrans0 (.DIN(htrans0));
  (* keep *) MCU_DIN mcu_htrans1 (.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite  (.DIN(hwrite));
  (* keep *) MCU_AHB_HSIZE0  mcu_hsize0  (.DIN(hsize[0]));
  (* keep *) MCU_AHB_HSIZE1  mcu_hsize1  (.DIN(hsize[1]));
  (* keep *) MCU_AHB_HSIZE2  mcu_hsize2  (.DIN(hsize[2]));
  (* keep *) MCU_AHB_HBURST0 mcu_hburst0 (.DIN(hburst[0]));
  (* keep *) MCU_AHB_HBURST1 mcu_hburst1 (.DIN(hburst[1]));
  (* keep *) MCU_AHB_HBURST2 mcu_hburst2 (.DIN(hburst[2]));

  // Three vendor paths cross a logic slice. Keep those identity LUTs at the
  // exact oracle sites; the other lanes are direct hard-source/hard-sink paths.
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'hff00)) htrans0_identity(
    .I({htrans0, 3'b000}), .Q(htrans0_buf));
  (* keep, BEL="X14Y12_SLICE13" *)
  LUT #(.K(4), .INIT(16'hff00)) hsize0_identity(
    .I({hsize[0], 3'b000}), .Q(hsize0_buf));
  (* keep, BEL="X14Y12_SLICE15", AGRV2K_MCU_PINPACKED=1 *)
  LUT #(.K(4), .INIT(16'hff00)) hreadyout_identity(
    .I({haddr24, 3'b000}), .Q(hreadyout_buf));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hwrite));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(hready));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(htrans0_buf));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(htrans1));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(hsize0_buf));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(hsize[1]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(hsize[2]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(hburst[0]));
  (* keep *) MCU_DOUT mcu_h8(.DOUT(hburst[1]));
  (* keep *) MCU_DOUT mcu_h9(.DOUT(hburst[2]));

  (* keep *) MCU_DIN mcu_haddr24(.DIN(haddr24));
  (* keep *) MCU_DIN mcu_haddr25(.DIN(haddr25));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout_buf));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(haddr25));
endmodule
