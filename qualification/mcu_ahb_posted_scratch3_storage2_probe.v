// Lane-2 storage discriminator for the three-bit posted bank.
//
// This keeps the exact HWDATA2 consumer/storage site and its registered
// address/write controls, but bypasses the experiment-only forwarding route.
module top;
  wire hclk, htrans1, hwrite, haddr2, hwdata2;
  wire scratch2;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(scratch2));

  (* keep, BEL = "X14Y12_SLICE1" *) reg write_pending;
  (* keep, BEL = "X14Y12_SLICE0" *) reg addr_pipe;

`ifdef SYNTHESIS
  // I0=HWDATA2, I1=write_pending, I2=address tag, I3=own Q.
  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFB08), .FF_USED(1'b1))
    storage(.CLK(hclk),
            .I({scratch2, addr_pipe, write_pending, hwdata2}),
            .F(), .Q(scratch2));
`else
  reg scratch2_r;
  assign scratch2 = scratch2_r;
`endif

  always @(posedge hclk) begin
`ifndef SYNTHESIS
    if (write_pending && !addr_pipe)
      scratch2_r <= hwdata2;
`endif
    write_pending <= htrans1 && hwrite;
    addr_pipe <= haddr2;
  end
endmodule
