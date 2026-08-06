// Byte-wide ID/scratch endpoint plus the qualified three-bit read-only
// counter breadth. Offset 8 returns {5'b0,counter}; offset C remains zero.
module agamemnon_ahb_id_scratch_counter3_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire haddr3,
  input wire [7:0] hwdata, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [7:0] hrdata
);
  (* keep, BEL = "X14Y12_SLICE1" *) reg write_pending;
  (* keep, BEL = "X14Y12_SLICE0" *) reg addr_pipe;
  (* keep, BEL = "X14Y12_SLICE2" *) reg addr3_pipe;
  (* keep *) reg write_data_pipe1;
`ifdef SYNTHESIS
  wire write_data_pipe5;
  wire scratch5_next;
  wire write_commit_root, write_commit_lo, write_commit_hi;
  wire [7:0] scratch;
  wire [1:0] low_read;
  wire [2:0] counter;
`else
  reg write_data_pipe5;
  reg write_commit0;
  reg [7:0] scratch;
  reg [2:0] counter;
`endif
  wire htrans1_leaf;

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;

`ifndef SYNTHESIS
  initial counter = 3'b000;
  always @(posedge hclk)
    counter <= counter + 1'b1;
`endif

`ifdef SYNTHESIS
  (* keep, BEL = "X17Y12_SLICE0", AGRV2K_DISTRIBUTION_ROOT = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2020), .FF_USED(1'b1))
    write_commit_stage(.CLK(hclk),
                       .I({1'b0, write_pending, addr3_pipe, addr_pipe}),
                       .F(), .Q(write_commit_root));

  (* keep, BEL = "X14Y7_SLICE3", AGRV2K_ROUTE_THROUGH = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    write_commit_buffer_lo(.CLK(hclk),
                           .I({write_commit_root, 3'b000}),
                           .F(write_commit_lo), .Q());
  (* keep, BEL = "X14Y4_SLICE0", AGRV2K_ROUTE_THROUGH = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    write_commit_buffer_hi(.CLK(hclk),
                           .I({write_commit_root, 3'b000}),
                           .F(write_commit_hi), .Q());

  (* keep, BEL = "X14Y8_SLICE8", AGRV2K_ROUTE_THROUGH = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    htrans1_ingress(.CLK(hclk), .I({3'b000, htrans1}),
                    .F(htrans1_leaf), .Q());

  // Ordinary LUT-feedback counter avoids the four-site direct-D pool already
  // occupied by byte scratch. These three equations implement +1 modulo 8.
  (* keep, BEL = "X15Y8_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5555), .FF_USED(1'b1))
    counter0(.CLK(hclk), .I({3'b000, counter[0]}), .F(), .Q(counter[0]));
  (* keep, BEL = "X15Y8_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h6666), .FF_USED(1'b1))
    counter1(.CLK(hclk), .I({2'b00, counter[1], counter[0]}), .F(), .Q(counter[1]));
  (* keep, BEL = "X15Y8_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h7878), .FF_USED(1'b1))
    counter2(.CLK(hclk), .I({1'b0, counter[2], counter[1], counter[0]}), .F(), .Q(counter[2]));

  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFD5D), .FF_USED(1'b0))
    forwarding_mux0(.CLK(hclk),
                    .I({hwdata[0], write_commit_lo, scratch[0], addr_pipe}),
                    .F(low_read[0]), .Q());
  (* keep, BEL = "X14Y11_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hA808), .FF_USED(1'b0))
    forwarding_mux1(.CLK(hclk),
                    .I({write_data_pipe1, write_commit_lo,
                        scratch[1], addr_pipe}),
                    .F(low_read[1]), .Q());
  (* keep, BEL = "X14Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0CAF), .FF_USED(1'b0))
    forwarding_mux2(.CLK(hclk),
                    .I({haddr3, haddr2, counter[2], scratch[2]}),
                    .F(hrdata[2]), .Q());
  (* keep, BEL = "X14Y11_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0CAF), .FF_USED(1'b0))
    forwarding_mux3(.CLK(hclk),
                    .I({haddr3, haddr2, 1'b0, scratch[3]}),
                    .F(hrdata[3]), .Q());
  (* keep, BEL = "X14Y11_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0CA0), .FF_USED(1'b0))
    forwarding_mux4(.CLK(hclk),
                    .I({haddr3, haddr2, 1'b0, scratch[4]}),
                    .F(hrdata[4]), .Q());
  (* keep, BEL = "X14Y11_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0CA0), .FF_USED(1'b0))
    forwarding_mux5(.CLK(hclk),
                    .I({haddr3, haddr2, 1'b0, scratch[5]}),
                    .F(hrdata[5]), .Q());
  (* keep, BEL = "X14Y11_SLICE13" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0CAF), .FF_USED(1'b0))
    forwarding_mux6(.CLK(hclk),
                    .I({haddr3, haddr2, 1'b0, scratch[6]}),
                    .F(hrdata[6]), .Q());
  (* keep, BEL = "X14Y11_SLICE11" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0CA0), .FF_USED(1'b0))
    forwarding_mux7(.CLK(hclk),
                    .I({haddr3, haddr2, 1'b0, scratch[7]}),
                    .F(hrdata[7]), .Q());

  // I3=low ID/scratch value, I2=HADDR3, I1=HADDR2, I0=counter.
  // 2F20 selects low_read for offsets 0/4, counter for offset 8, and zero
  // for offset C.
  (* keep, BEL = "X15Y11_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2F20), .FF_USED(1'b0))
    class_mux0(.CLK(hclk), .I({low_read[0], haddr3, haddr2, counter[0]}), .F(hrdata[0]), .Q());
  (* keep, BEL = "X15Y11_SLICE9" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2F20), .FF_USED(1'b0))
    class_mux1(.CLK(hclk), .I({low_read[1], haddr3, haddr2, counter[1]}), .F(hrdata[1]), .Q());

  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage0(.CLK(hclk),
                     .I({scratch[0], 1'b0, hwdata[0], write_commit_lo}),
                     .F(), .Q(scratch[0]));
  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage1(.CLK(hclk),
                     .I({scratch[1], 1'b0,
                         write_data_pipe1, write_commit_lo}),
                     .F(), .Q(scratch[1]));
  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBB88), .FF_USED(1'b1))
    scratch_storage2(.CLK(hclk),
                     .I({scratch[2], 1'b0, write_commit_hi, hwdata[2]}),
                     .F(), .Q(scratch[2]));
  (* keep, BEL = "X15Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage3(.CLK(hclk),
                     .I({scratch[3], 1'b0, hwdata[3], write_commit_hi}),
                     .F(), .Q(scratch[3]));
  (* keep, BEL = "X15Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage4(.CLK(hclk),
                     .I({scratch[4], 1'b0, hwdata[4], write_commit_hi}),
                     .F(), .Q(scratch[4]));

  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    write_data_capture5(.CLK(hclk), .I({3'b000, hwdata[5]}),
                        .F(), .Q(write_data_pipe5));
  (* keep, BEL = "X14Y11_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCACA), .FF_USED(1'b0))
    scratch_next_mux5(.CLK(hclk),
                      .I({1'b0, write_commit_lo,
                          write_data_pipe5, scratch[5]}),
                      .F(scratch5_next), .Q());
  (* keep, BEL = "X14Y11_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    scratch_storage5(.CLK(hclk), .I({3'b000, scratch5_next}),
                     .F(), .Q(scratch[5]));

  // The qualified HWDATA6 consumer is slice15/I0. Its Q exit is an MCU-only
  // corridor, so fold commit/hold into this slice instead of trying to fan the
  // captured Q back into a separate fabric next-state LUT. This is the same
  // BB88 equation already qualified for lane2: I0=data, I1=commit, I3=own Q.
  // The constant HREADYOUT source remains live and is allocated elsewhere.
  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBB88), .FF_USED(1'b1))
    scratch_storage6(.CLK(hclk),
                     .I({scratch[6], 1'b0, write_commit_hi, hwdata[6]}),
                     .F(), .Q(scratch[6]));

  // HWDATA7 is exact at slice0/I1. The already-qualified low commit leaf
  // reaches I2 there; use I0 for own-Q hold. CACA implements
  // commit ? HWDATA7 : Q with no guessed selector.
  (* keep, BEL = "X14Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCACA), .FF_USED(1'b1))
    scratch_storage7(.CLK(hclk),
                     .I({1'b0, write_commit_lo, hwdata[7], scratch[7]}),
                     .F(), .Q(scratch[7]));
`else
  assign htrans1_leaf = htrans1;
  wire [7:0] low_read_sim = haddr2 ?
                       {scratch[7:2],
                        (write_commit0 ? write_data_pipe1 : scratch[1]),
                        (write_commit0 ? hwdata[0] : scratch[0])} : 8'h4d;
  assign hrdata = haddr3 ? (haddr2 ? 8'h00 : {5'b0, counter}) : low_read_sim;
`endif

  always @(posedge hclk)
    write_data_pipe1 <= hwdata[1];
`ifndef SYNTHESIS
  always @(posedge hclk)
    write_data_pipe5 <= hwdata[5];
`endif

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      addr_pipe <= 1'b0;
      addr3_pipe <= 1'b0;
`ifndef SYNTHESIS
      write_commit0 <= 1'b0;
      scratch <= 8'b00000000;
`endif
    end else begin
`ifndef SYNTHESIS
      if (write_pending && addr_pipe)
        scratch[7:2] <= hwdata[7:2];
      if (write_commit0) begin
        scratch[1] <= write_data_pipe1;
        scratch[0] <= hwdata[0];
      end
      write_commit0 <= write_pending && addr_pipe;
`endif
      write_pending <= htrans1_leaf && hwrite;
      addr_pipe <= haddr2;
      addr3_pipe <= haddr3;
    end
  end
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2, haddr3;
  wire [7:0] hwdata, readback;
  wire hrdata0, hreadyout, hresp;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr3));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata[0]));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata[1]));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata[2]));
  (* keep *) MCU_DIN mcu_hwdata3(.DIN(hwdata[3]));
  (* keep *) MCU_DIN mcu_hwdata4(.DIN(hwdata[4]));
  (* keep *) MCU_DIN mcu_hwdata5(.DIN(hwdata[5]));
  (* keep *) MCU_DIN mcu_hwdata6(.DIN(hwdata[6]));
  (* keep *) MCU_DIN mcu_hwdata7(.DIN(hwdata[7]));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(readback[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(readback[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(readback[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(readback[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(readback[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(readback[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(readback[7]));
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    readback_buffer0(.CLK(hclk), .I({3'b000, readback[0]}),
                     .F(hrdata0), .Q());
  agamemnon_ahb_id_scratch_counter3_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3),
    .hwdata(hwdata), .reset_request(1'b0), .hreadyout(hreadyout),
    .hresp(hresp), .hrdata(readback));
endmodule
