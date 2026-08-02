// Hardware-free strict-routing smoke for the first read-only fabric-master
// response slice. This is not a protocol-valid AHB master or a silicon image.
module top;
  wire hreadyout;
  wire hresp;
  wire hrdata0;
  (* keep *) MCU_SLAVE_AHB_HREADYOUT response_ready(.DIN(hreadyout));
  (* keep *) MCU_SLAVE_AHB_HRESP response_error(.DIN(hresp));
  (* keep *) MCU_SLAVE_AHB_HRDATA0 response_data0(.DIN(hrdata0));
  (* keep *) wire retained_probe;
  (* keep, BEL="X14Y9_SLICE0" *)
  // Vendor routes HRDATA0/HREADYOUT/HRESP onto physical I[3:1]
  // respectively; I[0] is unused.
  LUT #(.K(4), .INIT(16'hc33c)) response_probe(
    .I({hrdata0, hreadyout, hresp, 1'b0}), .Q(retained_probe));
endmodule
