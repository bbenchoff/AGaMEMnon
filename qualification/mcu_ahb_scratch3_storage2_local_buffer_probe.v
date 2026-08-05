// Lane-2 storage through a nearby explicit identity buffer.
//
// This isolates the X14Y11 slice4 registered source from the distant
// X15Y12 forwarding terminal.  A pass proves that a complete local
// route-through restores internal consumption of the already-qualified
// storage state.
module top;
  wire hclk, htrans1, hwrite, haddr2, hwdata2;
  wire scratch2, scratch2_buf;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(scratch2_buf));

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

  (* keep, BEL = "X14Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    local_buffer(.I({3'b000, scratch2}), .F(scratch2_buf), .Q());

  always @(posedge hclk) begin
    write_pending <= htrans1 && hwrite;
    addr_pipe <= haddr2;
  end
endmodule
