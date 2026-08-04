// Candidate HADDR[3] alternate-ingress qualification oracle.
// HTRANS[1] keeps its simultaneous vendor corridor occupied so the router
// must use a disjoint HADDR[3] ingress.  AHB NONSEQ reads hold HTRANS[1] high,
// making HRDATA[0] the inverse of HADDR[3] during the address sweep.
module top;
  wire haddr3, htrans1;
  wire value;

  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr3));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) LUT #(.K(4), .INIT(16'h6666)) xor_lut
    (.I({2'b00, htrans1, haddr3}), .Q(value));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(value));
endmodule
