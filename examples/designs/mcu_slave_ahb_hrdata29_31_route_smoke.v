// Hardware-free strict route smoke for fabric-master read-data lanes [31:29].
module top;
  wire hrdata29, hrdata30, hrdata31;
  (* keep *) MCU_SLAVE_AHB_HRDATA29 source29(.DIN(hrdata29));
  (* keep *) MCU_SLAVE_AHB_HRDATA30 source30(.DIN(hrdata30));
  (* keep *) MCU_SLAVE_AHB_HRDATA31 source31(.DIN(hrdata31));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y7_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata29, hrdata31, hrdata30, 1'b0}), .Q(retained_probe));
endmodule
