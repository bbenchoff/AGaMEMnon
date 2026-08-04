// Four distinct fabric sources driving the silicon-qualified independent
// local-interrupt corridors. Distinct LUT masks prevent source merging while
// I=0 keeps all four lanes safely low in this route/emission smoke. The source
// BELs are the exact sites used by the retained simultaneous silicon oracle.
// This source claims routing only, not pending/acknowledge semantics.
module top;
  wire irq0, irq1, irq2, irq3;

  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) source0(.I(4'b0000), .Q(irq0));
  (* keep, BEL="X14Y8_SLICE0" *)
  LUT #(.K(4), .INIT(16'hfffe)) source1(.I(4'b0000), .Q(irq1));
  (* keep, BEL="X10Y4_SLICE0" *)
  LUT #(.K(4), .INIT(16'haaaa)) source2(.I(4'b0000), .Q(irq2));
  (* keep, BEL="X14Y4_SLICE0" *)
  LUT #(.K(4), .INIT(16'hcccc)) source3(.I(4'b0000), .Q(irq3));

  (* keep *) MCU_LOCAL_INT0 sink0(.DOUT(irq0));
  (* keep *) MCU_LOCAL_INT1 sink1(.DOUT(irq1));
  (* keep *) MCU_LOCAL_INT2 sink2(.DOUT(irq2));
  (* keep *) MCU_LOCAL_INT3 sink3(.DOUT(irq3));
endmodule
