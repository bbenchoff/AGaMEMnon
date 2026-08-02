// Hardware-free strict simultaneous-ingress smoke for all 32 fabric-master
// read-data lanes. Eight retained four-lane reductions feed a final XOR tree.
module top;
  wire [31:0] hrdata;
  (* keep *) MCU_SLAVE_AHB_HRDATA0 s0(.DIN(hrdata[0]));
  (* keep *) MCU_SLAVE_AHB_HRDATA1 s1(.DIN(hrdata[1]));
  (* keep *) MCU_SLAVE_AHB_HRDATA2 s2(.DIN(hrdata[2]));
  (* keep *) MCU_SLAVE_AHB_HRDATA3 s3(.DIN(hrdata[3]));
  (* keep *) MCU_SLAVE_AHB_HRDATA4 s4(.DIN(hrdata[4]));
  (* keep *) MCU_SLAVE_AHB_HRDATA5 s5(.DIN(hrdata[5]));
  (* keep *) MCU_SLAVE_AHB_HRDATA6 s6(.DIN(hrdata[6]));
  (* keep *) MCU_SLAVE_AHB_HRDATA7 s7(.DIN(hrdata[7]));
  (* keep *) MCU_SLAVE_AHB_HRDATA8 s8(.DIN(hrdata[8]));
  (* keep *) MCU_SLAVE_AHB_HRDATA9 s9(.DIN(hrdata[9]));
  (* keep *) MCU_SLAVE_AHB_HRDATA10 s10(.DIN(hrdata[10]));
  (* keep *) MCU_SLAVE_AHB_HRDATA11 s11(.DIN(hrdata[11]));
  (* keep *) MCU_SLAVE_AHB_HRDATA12 s12(.DIN(hrdata[12]));
  (* keep *) MCU_SLAVE_AHB_HRDATA13 s13(.DIN(hrdata[13]));
  (* keep *) MCU_SLAVE_AHB_HRDATA14 s14(.DIN(hrdata[14]));
  (* keep *) MCU_SLAVE_AHB_HRDATA15 s15(.DIN(hrdata[15]));
  (* keep *) MCU_SLAVE_AHB_HRDATA16 s16(.DIN(hrdata[16]));
  (* keep *) MCU_SLAVE_AHB_HRDATA17 s17(.DIN(hrdata[17]));
  (* keep *) MCU_SLAVE_AHB_HRDATA18 s18(.DIN(hrdata[18]));
  (* keep *) MCU_SLAVE_AHB_HRDATA19 s19(.DIN(hrdata[19]));
  (* keep *) MCU_SLAVE_AHB_HRDATA20 s20(.DIN(hrdata[20]));
  (* keep *) MCU_SLAVE_AHB_HRDATA21 s21(.DIN(hrdata[21]));
  (* keep *) MCU_SLAVE_AHB_HRDATA22 s22(.DIN(hrdata[22]));
  (* keep *) MCU_SLAVE_AHB_HRDATA23 s23(.DIN(hrdata[23]));
  (* keep *) MCU_SLAVE_AHB_HRDATA24 s24(.DIN(hrdata[24]));
  (* keep *) MCU_SLAVE_AHB_HRDATA25 s25(.DIN(hrdata[25]));
  (* keep *) MCU_SLAVE_AHB_HRDATA26 s26(.DIN(hrdata[26]));
  (* keep *) MCU_SLAVE_AHB_HRDATA27 s27(.DIN(hrdata[27]));
  (* keep *) MCU_SLAVE_AHB_HRDATA28 s28(.DIN(hrdata[28]));
  (* keep *) MCU_SLAVE_AHB_HRDATA29 s29(.DIN(hrdata[29]));
  (* keep *) MCU_SLAVE_AHB_HRDATA30 s30(.DIN(hrdata[30]));
  (* keep *) MCU_SLAVE_AHB_HRDATA31 s31(.DIN(hrdata[31]));

  // The simultaneous vendor route inserts identity LUTs on lanes 13 and 27
  // before their group LUTs. Model those two ordinary logic hops explicitly.
  (* keep *) wire hrdata13_buffered;
  (* keep, BEL="X15Y8_SLICE7" *)
  LUT #(.K(4), .INIT(16'hff00)) buffer13(
    .I({hrdata[13], 3'b000}), .Q(hrdata13_buffered));
  (* keep *) wire hrdata27_buffered;
  (* keep, BEL="X14Y7_SLICE3" *)
  LUT #(.K(4), .INIT(16'hff00)) buffer27(
    .I({hrdata[27], 3'b000}), .Q(hrdata27_buffered));

  // Vendor simultaneous placement: eight group LUTs occupy slices 0..7 at
  // X14Y8. Input ordering follows the recovered terminal IMUX numbers.
  (* keep *) wire [7:0] group_xor;
  (* keep, BEL="X14Y8_SLICE4" *) LUT #(.K(4), .INIT(16'h6996)) g0(
    .I(hrdata[3:0]), .Q(group_xor[0]));
  (* keep, BEL="X14Y8_SLICE5" *) LUT #(.K(4), .INIT(16'h6996)) g1(
    .I({hrdata[5], hrdata[4], hrdata[7], hrdata[6]}), .Q(group_xor[1]));
  (* keep, BEL="X14Y8_SLICE0" *) LUT #(.K(4), .INIT(16'h6996)) g2(
    .I({hrdata[9], hrdata[8], hrdata[11], hrdata[10]}), .Q(group_xor[2]));
  (* keep, BEL="X14Y8_SLICE1" *) LUT #(.K(4), .INIT(16'h6996)) g3(
    .I({hrdata13_buffered, hrdata[12], hrdata[15], hrdata[14]}),
    .Q(group_xor[3]));
  (* keep, BEL="X14Y8_SLICE6" *) LUT #(.K(4), .INIT(16'h6996)) g4(
    .I({hrdata[17], hrdata[16], hrdata[19], hrdata[18]}), .Q(group_xor[4]));
  (* keep, BEL="X14Y8_SLICE7" *) LUT #(.K(4), .INIT(16'h6996)) g5(
    .I({hrdata[21], hrdata[20], hrdata[23], hrdata[22]}), .Q(group_xor[5]));
  (* keep, BEL="X14Y8_SLICE2" *) LUT #(.K(4), .INIT(16'h6996)) g6(
    .I({hrdata27_buffered, hrdata[26], hrdata[25], hrdata[24]}),
    .Q(group_xor[6]));
  (* keep, BEL="X14Y8_SLICE3" *) LUT #(.K(4), .INIT(16'h6996)) g7(
    .I({hrdata[29], hrdata[28], hrdata[31], hrdata[30]}), .Q(group_xor[7]));
endmodule
