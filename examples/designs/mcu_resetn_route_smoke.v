// Hardware-free proof that the typed MCU reset source reaches ordinary logic.
// RESETN is passed through a LUT and returned on HRDATA[0]. This is an
// extraction topology, not a legal AHB endpoint; do not load it.
module top;
  wire resetn;
  wire observed;

  (* keep *) MCU_RESETN mcu_resetn(.RESETN(resetn));
  (* keep *) LUT #(.K(4), .INIT(16'hff00)) reset_identity(
    .I({resetn, 3'b000}), .Q(observed));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
