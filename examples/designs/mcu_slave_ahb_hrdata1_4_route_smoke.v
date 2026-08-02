// Hardware-free strict route smoke for fabric-master read-data lanes [4:1].
module top;
  wire hrdata1;
  wire hrdata2;
  wire hrdata3;
  wire hrdata4;
  (* keep *) MCU_SLAVE_AHB_HRDATA1 source1(.DIN(hrdata1));
  (* keep *) MCU_SLAVE_AHB_HRDATA2 source2(.DIN(hrdata2));
  (* keep *) MCU_SLAVE_AHB_HRDATA3 source3(.DIN(hrdata3));
  (* keep *) MCU_SLAVE_AHB_HRDATA4 source4(.DIN(hrdata4));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y9_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata1, hrdata3, hrdata4, hrdata2}), .Q(retained_probe));
endmodule
