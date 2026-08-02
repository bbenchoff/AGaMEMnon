// Hardware-free strict route smoke for fabric-master read-data lanes [16:13].
module top;
  wire hrdata13, hrdata14, hrdata15, hrdata16;
  (* keep *) MCU_SLAVE_AHB_HRDATA13 source13(.DIN(hrdata13));
  (* keep *) MCU_SLAVE_AHB_HRDATA14 source14(.DIN(hrdata14));
  (* keep *) MCU_SLAVE_AHB_HRDATA15 source15(.DIN(hrdata15));
  (* keep *) MCU_SLAVE_AHB_HRDATA16 source16(.DIN(hrdata16));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y8_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata16, hrdata14, hrdata15, hrdata13}), .Q(retained_probe));
endmodule
