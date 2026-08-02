// Hardware-free strict route smoke for fabric-master read-data lanes [28:25].
module top;
  wire hrdata25, hrdata26, hrdata27, hrdata28;
  (* keep *) MCU_SLAVE_AHB_HRDATA25 source25(.DIN(hrdata25));
  (* keep *) MCU_SLAVE_AHB_HRDATA26 source26(.DIN(hrdata26));
  (* keep *) MCU_SLAVE_AHB_HRDATA27 source27(.DIN(hrdata27));
  (* keep *) MCU_SLAVE_AHB_HRDATA28 source28(.DIN(hrdata28));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y7_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata25, hrdata27, hrdata28, hrdata26}), .Q(retained_probe));
endmodule
