// Consumer-only discriminator for the posted-write scratch stage.  With
// commit and data tied high, INIT=0x0d08 presents a constant one to D while
// retaining the exact qualified direct-D feedback and readback footprint.
module top;
  wire hclk;
  wire scratch_f, scratch_q;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(scratch_f));

  (* keep, BEL="X14Y11_SLICE7", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0D08), .FF_USED(1'b1))
    scratch_stage(.CLK(hclk), .I({scratch_q, 1'b0, 1'b1, 1'b1}),
                  .F(scratch_f), .Q(scratch_q));
endmodule
