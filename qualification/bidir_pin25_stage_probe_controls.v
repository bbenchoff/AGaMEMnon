// Direct observation of the X14Y4 PIN10 ingress stage, with constant controls.
//
// All three tops retain the safe PIN25 release/drive-low composition solely so
// the uarch locks the identical vendor stage ingress/egress.  PIN18 reports the
// stage output directly instead of reporting PIN25 readback.  const0/const1
// calibrate the entire stage-to-PIN18 observation channel; external is the
// single-variable PIN10 ingress arm.

module pin25_stage_probe_external(input drive_low, inout link, output observed);
  wire staged;
  (* keep *) wire link_terminated;
  (* keep, BEL = "X14Y4_SLICE4", AGRV2K_PIN25_VENDOR_STAGE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    pin10_vendor_stage(.CLK(), .I({1'b0, drive_low, 2'b00}), .F(staged), .Q());
  assign link = staged ? 1'b0 : 1'bz;
  assign observed = staged;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    link_sink(.CLK(), .I({1'b0, link, 2'b00}), .F(link_terminated), .Q());
endmodule

module pin25_stage_probe_const0(input drive_low, inout link, output observed);
  wire staged;
  (* keep *) wire link_terminated;
  (* keep, BEL = "X14Y4_SLICE4", AGRV2K_PIN25_VENDOR_STAGE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0000), .FF_USED(1'b0))
    pin10_vendor_stage(.CLK(), .I({1'b0, drive_low, 2'b00}), .F(staged), .Q());
  assign link = staged ? 1'b0 : 1'bz;
  assign observed = staged;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    link_sink(.CLK(), .I({1'b0, link, 2'b00}), .F(link_terminated), .Q());
endmodule

module pin25_stage_probe_const1(input drive_low, inout link, output observed);
  wire staged;
  (* keep *) wire link_terminated;
  (* keep, BEL = "X14Y4_SLICE4", AGRV2K_PIN25_VENDOR_STAGE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFFFF), .FF_USED(1'b0))
    pin10_vendor_stage(.CLK(), .I({1'b0, drive_low, 2'b00}), .F(staged), .Q());
  assign link = staged ? 1'b0 : 1'bz;
  assign observed = staged;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    link_sink(.CLK(), .I({1'b0, link, 2'b00}), .F(link_terminated), .Q());
endmodule
