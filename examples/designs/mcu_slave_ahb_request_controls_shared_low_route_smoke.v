// Hardware-free strict smoke for all 11 fabric-master AHB request qualifiers.
// The recovered vendor oracle used one shared source, so this proves only a
// simultaneous shared safe-low route, not independently routable controls or
// a protocol-valid master.
module top;
  (* keep *) wire request_low;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) request_source(
    .I(4'b0000), .Q(request_low));

  (* keep *) MCU_SLAVE_AHB_HSEL hsel(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HREADY hready(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HTRANS0 htrans0(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HTRANS1 htrans1(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HSIZE0 hsize0(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HSIZE1 hsize1(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HSIZE2 hsize2(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HBURST0 hburst0(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HBURST1 hburst1(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HBURST2 hburst2(.DOUT(request_low));
  (* keep *) MCU_SLAVE_AHB_HWRITE hwrite(.DOUT(request_low));
endmodule
