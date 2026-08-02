// Hardware-free strict route smoke for fabric-master read-data lanes [8:5].
module top;
  wire hrdata5, hrdata6, hrdata7, hrdata8;
  (* keep *) MCU_SLAVE_AHB_HRDATA5 source5(.DIN(hrdata5));
  (* keep *) MCU_SLAVE_AHB_HRDATA6 source6(.DIN(hrdata6));
  (* keep *) MCU_SLAVE_AHB_HRDATA7 source7(.DIN(hrdata7));
  (* keep *) MCU_SLAVE_AHB_HRDATA8 source8(.DIN(hrdata8));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y8_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata5, hrdata7, hrdata8, hrdata6}), .Q(retained_probe));
endmodule
