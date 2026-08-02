// Hardware-free strict route smoke for fabric-master read-data lanes [12:9].
module top;
  wire hrdata9, hrdata10, hrdata11, hrdata12;
  (* keep *) MCU_SLAVE_AHB_HRDATA9 source9(.DIN(hrdata9));
  (* keep *) MCU_SLAVE_AHB_HRDATA10 source10(.DIN(hrdata10));
  (* keep *) MCU_SLAVE_AHB_HRDATA11 source11(.DIN(hrdata11));
  (* keep *) MCU_SLAVE_AHB_HRDATA12 source12(.DIN(hrdata12));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y8_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata10, hrdata11, hrdata9, hrdata12}), .Q(retained_probe));
endmodule
