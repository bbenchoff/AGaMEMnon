// Lane-2 storage with a same-tile address-gated readback cell.
//
// The X14Y11 slice4 Q output reaches its hard HRDATA exit but has failed
// through three longer routes.  Keep the first consumer on the same tile:
// data enters slice2/I0, the live HADDR[2] branch enters I1, and 0x2222
// implements data && !address before the ordinary MCU readback exit.  The
// registered address tag remains the write-phase consumer; using live HADDR
// here keeps read selection in the AHB address phase.
module top;
  wire hclk, htrans1, hwrite, haddr2, hwdata2;
  wire scratch2, hrdata2;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(hrdata2));

  (* keep, BEL = "X14Y12_SLICE1" *) reg write_pending;
  (* keep, BEL = "X14Y12_SLICE0" *) reg addr_pipe;
  wire write_commit0;

  (* keep, BEL = "X17Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h4444), .FF_USED(1'b1))
    write_commit_stage(.CLK(hclk),
                       .I({write_pending, addr_pipe, write_pending, addr_pipe}),
                       .F(), .Q(write_commit0));

  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBB88), .FF_USED(1'b1))
    storage(.CLK(hclk),
            .I({scratch2, 1'b0, write_commit0, hwdata2}),
            .F(), .Q(scratch2));

  (* keep, BEL = "X14Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2222), .FF_USED(1'b0))
    forwarding(.I({2'b00, haddr2, scratch2}), .F(hrdata2), .Q());

  always @(posedge hclk) begin
    write_pending <= htrans1 && hwrite;
    addr_pipe <= haddr2;
  end
endmodule
