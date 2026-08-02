// Hardware-free strict route smoke for fabric-master read-data lanes [20:17].
module top;
  wire hrdata17, hrdata18, hrdata19, hrdata20;
  (* keep *) MCU_SLAVE_AHB_HRDATA17 source17(.DIN(hrdata17));
  (* keep *) MCU_SLAVE_AHB_HRDATA18 source18(.DIN(hrdata18));
  (* keep *) MCU_SLAVE_AHB_HRDATA19 source19(.DIN(hrdata19));
  (* keep *) MCU_SLAVE_AHB_HRDATA20 source20(.DIN(hrdata20));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y8_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) probe(
    .I({hrdata17, hrdata19, hrdata20, hrdata18}), .Q(retained_probe));
endmodule
