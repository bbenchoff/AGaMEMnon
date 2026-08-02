// Hardware-free strict route smoke for fabric-master read-data lanes [24:21].
module top;
  wire hrdata21, hrdata22, hrdata23, hrdata24;
  (* keep *) MCU_SLAVE_AHB_HRDATA21 source21(.DIN(hrdata21));
  (* keep *) MCU_SLAVE_AHB_HRDATA22 source22(.DIN(hrdata22));
  (* keep *) MCU_SLAVE_AHB_HRDATA23 source23(.DIN(hrdata23));
  (* keep *) MCU_SLAVE_AHB_HRDATA24 source24(.DIN(hrdata24));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y8_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata21, hrdata23, hrdata24, hrdata22}), .Q(retained_probe));
endmodule
