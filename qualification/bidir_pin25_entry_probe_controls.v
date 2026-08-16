// Silicon-qualified PIN10 entry boundary, observed through the same GP8 sink.
// The external arm terminates InputMUX02 -> RMUX15 -> RMUX53 -> IMUX11 at
// X19Y12_SLICE2 I3, exactly as the retained serial_mux input qualification.

module pin25_entry_probe_external(input drive_low, inout link, output observed);
  wire staged;
  (* keep *) wire link_terminated;
  (* keep, BEL = "X19Y12_SLICE2", AGRV2K_PIN10_ENTRY_PROBE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    pin10_entry_stage(.CLK(), .I({drive_low, 3'b000}), .F(staged), .Q());
  assign link = staged ? 1'b0 : 1'bz;
  assign observed = staged;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    link_sink(.CLK(), .I({1'b0, link, 2'b00}), .F(link_terminated), .Q());
endmodule

module pin25_entry_probe_const0(input drive_low, inout link, output observed);
  wire staged;
  (* keep *) wire link_terminated;
  (* keep, BEL = "X19Y12_SLICE2", AGRV2K_PIN10_ENTRY_PROBE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0000), .FF_USED(1'b0))
    pin10_entry_stage(.CLK(), .I({drive_low, 3'b000}), .F(staged), .Q());
  assign link = staged ? 1'b0 : 1'bz;
  assign observed = staged;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    link_sink(.CLK(), .I({1'b0, link, 2'b00}), .F(link_terminated), .Q());
endmodule

module pin25_entry_probe_const1(input drive_low, inout link, output observed);
  wire staged;
  (* keep *) wire link_terminated;
  (* keep, BEL = "X19Y12_SLICE2", AGRV2K_PIN10_ENTRY_PROBE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFFFF), .FF_USED(1'b0))
    pin10_entry_stage(.CLK(), .I({drive_low, 3'b000}), .F(staged), .Q());
  assign link = staged ? 1'b0 : 1'bz;
  assign observed = staged;
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    link_sink(.CLK(), .I({1'b0, link, 2'b00}), .F(link_terminated), .Q());
endmodule
