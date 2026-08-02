// First protocol-safe External AHB endpoint: every transfer completes in one
// cycle with OKAY and reads return a fixed identification word. Writes are
// accepted and intentionally have no effect.
module agamemnon_mcu_ahb_constant_slave #(
  parameter [31:0] READ_DATA = 32'h4147_414d
) ();
  wire hclk, hresetn, hready, hwrite;
  wire [1:0] htrans;
  wire [2:0] hsize, hburst;
  wire [31:0] haddr, hwdata;
  wire hreadyout, hresp;
  wire [31:0] hrdata = READ_DATA;

  // Give the two response controls independent physical sources. Sharing the
  // global VCC/GND drivers with all 32 HRDATA sinks forces unrelated boundary
  // corridors onto one tree and can strand the dedicated control endpoints.
  (* keep *) LUT #(.K(4), .INIT(16'hffff)) ready_constant(
    .I(4'b0000), .Q(hreadyout));
  (* keep *) LUT #(.K(4), .INIT(16'h0000)) okay_constant(
    .I(4'b0000), .Q(hresp));

  agamemnon_mcu_ahb_port port_i(
    .HCLK(hclk), .HRESETn(hresetn), .HREADY(hready), .HTRANS(htrans),
    .HSIZE(hsize), .HBURST(hburst), .HWRITE(hwrite), .HADDR(haddr),
    .HWDATA(hwdata), .HREADYOUT(hreadyout), .HRESP(hresp), .HRDATA(hrdata));

  wire _unused_request = hclk ^ hresetn ^ hready ^ hwrite ^ ^htrans ^
                         ^hsize ^ ^hburst ^ ^haddr ^ ^hwdata;
endmodule
