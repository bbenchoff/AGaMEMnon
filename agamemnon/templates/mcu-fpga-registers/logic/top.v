// Silicon-qualification image for one controlled write wait composed with a
// GPIO4.1-resettable complete-byte writable bank. Lane 6 uses the separately
// qualified pure-open ingress and the scratch commit-stage combinational F;
// all other lanes retain their previously qualified storage contracts:
//   0x0 immutable ID 0x4d, 0x4 posted scratch, 0x8 counter[2:0],
//   0xc one-bit W1C status (write bit1=set hook, bit0=clear).
module agamemnon_ahb_register_bank_combined_wait_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire haddr3,
  input wire [7:0] hwdata, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [7:0] hrdata
);
  reg [2:0] counter;
  wire write_ready_f, scratch_commit_now;
`ifdef SYNTHESIS
  wire haddr3_leaf, write_pending;
  wire select_counter, select_status;
  wire scratch_commit_root, status_commit_root, any_write_commit;
  wire write_commit_lo, write_commit_hi;
  wire write_data_pipe1, write_data_pipe5, scratch5_next;
  wire [7:0] scratch, low_read;
  wire set_pulse, clear_pulse, status;
  wire [2:0] high_read;
`else
  reg write_pending = 1'b0;
  reg select_scratch = 1'b0;
  reg select_counter = 1'b0;
  reg select_status = 1'b0;
  reg scratch_commit_root = 1'b0;
  reg status_commit_root = 1'b0;
  reg write_data_pipe1 = 1'b0;
  reg write_data_pipe5 = 1'b0;
  reg [7:0] scratch = 8'h00;
  reg set_pulse = 1'b0;
  reg clear_pulse = 1'b0;
  reg status = 1'b0;
  wire any_write_commit = scratch_commit_root | status_commit_root;
  wire [7:0] low_read = select_scratch ?
      {scratch[7:2],
       (any_write_commit ? write_data_pipe1 : scratch[1]),
       (any_write_commit ? hwdata[0] : scratch[0])} :
      {6'b010011, (any_write_commit ? write_data_pipe1 : 1'b0),
       (any_write_commit ? hwdata[0] : 1'b1)};
  wire [2:0] high_read = select_counter ? counter :
                         (select_status ? {2'b00, status} : 3'b000);
`endif

  assign hreadyout = write_ready_f;
  assign hresp = 1'b0;

`ifndef SYNTHESIS
  // The accepted-write token is also the sole wait state. Gating token
  // capture with ready clears it during the stalled cycle, so the next cycle
  // completes without a feedback register or a duplicate commit.
  assign write_ready_f = reset_request || !write_pending;
  assign scratch_commit_now = write_pending && !haddr3 && haddr2;
`endif

`ifndef SYNTHESIS
  initial counter = 3'b000;
`endif
  // --hard-carry lowers the adder itself into the qualified seeded corridor.
  // The synchronous reset muxes remain separate from the carry sum so reset
  // dominates every counter bit without claiming a carry-FF reset primitive.
  always @(posedge hclk) begin
    if (reset_request)
      counter <= 3'b000;
    else
      counter <= counter + 1'b1;
  end

`ifdef SYNTHESIS
  // Keep the two hard ingress contracts that passed independently.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    addr3_ingress(.CLK(hclk), .I({haddr3, 3'b000}),
                  .F(haddr3_leaf), .Q());
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0080), .FF_USED(1'b1))
    write_stage(.CLK(hclk),
                .I({reset_request, write_ready_f, hwrite, htrans1}),
                .F(), .Q(write_pending));

  // F/OMUX18 uses the exact silicon-qualified dynamic HREADYOUT corridor.
  // DDDD implements reset || !write_pending. No response-state feedback and
  // none of the eliminated apply-to-controller edges are present.
  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDDDD), .FF_USED(1'b0))
    write_wait_stage(.CLK(hclk),
                     .I({2'b00, reset_request, write_pending}),
                     .F(write_ready_f), .Q());

  // Keep the qualified distribution root on the scratch commit itself.  The
  // full three-input decode closes the data-phase write only for offset four.
  (* keep, BEL = "X17Y12_SLICE0", AGRV2K_DISTRIBUTION_ROOT = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2020), .FF_USED(1'b1))
    scratch_commit_stage(.CLK(hclk),
                         .I({1'b0, write_pending, haddr3_leaf, haddr2}),
                         .F(scratch_commit_now), .Q(scratch_commit_root));

  // Register the two high address classes across the AHB phase edge.  The
  // low ID/scratch read mux retains the independently qualified live HADDR2
  // selector; these registered classes override it for offsets eight/C.
  (* keep, BEL = "X17Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h4444), .FF_USED(1'b1))
    select_counter_stage(.CLK(hclk), .I({2'b00, haddr3_leaf, haddr2}),
                         .F(), .Q(select_counter));
  (* keep, BEL = "X17Y12_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    select_status_stage(.CLK(hclk), .I({2'b00, haddr3_leaf, haddr2}),
                        .F(), .Q(select_status));

  (* keep, BEL = "X17Y12_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    status_commit_stage(.CLK(hclk),
                        .I({2'b00, write_pending, select_status}),
                        .F(), .Q(status_commit_root));
  (* keep, BEL = "X17Y12_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hEEEE), .FF_USED(1'b0))
    any_commit_decode(.CLK(hclk),
                      .I({2'b00, status_commit_root, scratch_commit_root}),
                      .F(any_write_commit), .Q());

  (* keep, BEL = "X14Y7_SLICE3", AGRV2K_ROUTE_THROUGH = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    write_commit_buffer_lo(.CLK(hclk),
                           .I({scratch_commit_root, 3'b000}),
                           .F(write_commit_lo), .Q());
  (* keep, BEL = "X14Y4_SLICE0", AGRV2K_ROUTE_THROUGH = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    write_commit_buffer_hi(.CLK(hclk),
                           .I({scratch_commit_root, 3'b000}),
                           .F(write_commit_hi), .Q());

  // Lanes zero and one are the qualified posted-forwarding paths. During a
  // status write they also carry the hard HWDATA values into fabric-local
  // W1C event stages; no additional hard-data consumer is introduced.
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFD5D), .FF_USED(1'b0))
    forwarding_mux0(.CLK(hclk),
                    .I({hwdata[0], any_write_commit,
                        scratch[0], haddr2}),
                    .F(low_read[0]), .Q());
  (* keep, BEL = "X14Y10_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    write_data_capture1(.CLK(hclk), .I({3'b000, hwdata[1]}),
                        .F(), .Q(write_data_pipe1));
  (* keep, BEL = "X14Y11_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hA808), .FF_USED(1'b0))
    forwarding_mux1(.CLK(hclk),
                    .I({write_data_pipe1, any_write_commit,
                        scratch[1], haddr2}),
                    .F(low_read[1]), .Q());
  (* keep, BEL = "X14Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBBBB), .FF_USED(1'b0))
    forwarding_mux2(.CLK(hclk), .I({2'b00, haddr2, scratch[2]}),
                    .F(low_read[2]), .Q());
  (* keep, BEL = "X14Y11_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBBBB), .FF_USED(1'b0))
    forwarding_mux3(.CLK(hclk), .I({2'b00, haddr2, scratch[3]}),
                    .F(low_read[3]), .Q());
  (* keep, BEL = "X14Y11_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    forwarding_mux4(.CLK(hclk), .I({2'b00, haddr2, scratch[4]}),
                    .F(low_read[4]), .Q());
  (* keep, BEL = "X15Y12_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    forwarding_mux5(.CLK(hclk), .I({2'b00, haddr2, scratch[5]}),
                    .F(low_read[5]), .Q());
  (* keep, BEL = "X14Y11_SLICE13" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBBBB), .FF_USED(1'b0))
    forwarding_mux6(.CLK(hclk), .I({2'b00, haddr2, scratch[6]}),
                    .F(low_read[6]), .Q());
  (* keep, BEL = "X14Y11_SLICE11" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    forwarding_mux7(.CLK(hclk), .I({2'b00, haddr2, scratch[7]}),
                    .F(low_read[7]), .Q());

  // Preserve the exact eight-lane scratch footprint unchanged.
  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00D8), .FF_USED(1'b1))
    scratch_storage0(.CLK(hclk),
                     .I({reset_request, scratch[0], hwdata[0], write_commit_lo}),
                     .F(), .Q(scratch[0]));
  // Slice6 is reserved for the already-qualified dynamic response source.
  // Lane1 consumes only fabric-local data/commit signals here; the strict
  // build and full silicon oracle qualify this relocated storage footprint.
  (* keep, BEL = "X15Y12_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00D8), .FF_USED(1'b1))
    scratch_storage1(.CLK(hclk),
                     .I({reset_request, scratch[1], write_data_pipe1,
                         write_commit_lo}), .F(), .Q(scratch[1]));
  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00B8), .FF_USED(1'b1))
    scratch_storage2(.CLK(hclk),
                     .I({reset_request, scratch[2], write_commit_hi, hwdata[2]}),
                     .F(), .Q(scratch[2]));
  (* keep, BEL = "X15Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00D8), .FF_USED(1'b1))
    scratch_storage3(.CLK(hclk),
                     .I({reset_request, scratch[3], hwdata[3], write_commit_hi}),
                     .F(), .Q(scratch[3]));
  (* keep, BEL = "X15Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00D8), .FF_USED(1'b1))
    scratch_storage4(.CLK(hclk),
                     .I({reset_request, scratch[4], hwdata[4], write_commit_hi}),
                     .F(), .Q(scratch[4]));
  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    write_data_capture5(.CLK(hclk), .I({3'b000, hwdata[5]}),
                        .F(), .Q(write_data_pipe5));
  (* keep, BEL = "X14Y11_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00CA), .FF_USED(1'b0))
    scratch_next_mux5(.CLK(hclk),
                      .I({reset_request, write_commit_lo,
                          write_data_pipe5, scratch[5]}),
                      .F(scratch5_next), .Q());
  (* keep, BEL = "X14Y11_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    scratch_storage5(.CLK(hclk), .I({3'b000, scratch5_next}),
                     .F(), .Q(scratch[5]));
  // Lane 6 retains its exact pure-open-qualified HWDATA6 ingress at I0 while
  // the commit-stage F supplies the data-phase commit at I1. The registered
  // Q remains the hold term at I3 and coexists with HREADYOUT's own source.
  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00B8), .FF_USED(1'b1))
    scratch_storage6(.CLK(hclk),
                     .I({reset_request, scratch[6], scratch_commit_now,
                         hwdata[6]}),
                     .F(), .Q(scratch[6]));
  (* keep, BEL = "X14Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00CA), .FF_USED(1'b1))
    scratch_storage7(.CLK(hclk),
                     .I({reset_request, write_commit_lo, hwdata[7], scratch[7]}),
                     .F(), .Q(scratch[7]));

  // W1C state consumes only fabric-local forwarded data. Set wins over clear.
  (* keep, BEL = "X15Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    clear_event_stage(.CLK(hclk),
                      .I({2'b00, status_commit_root, low_read[0]}),
                      .F(), .Q(clear_pulse));
  (* keep, BEL = "X15Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    set_event_stage(.CLK(hclk),
                    .I({2'b00, status_commit_root, low_read[1]}),
                    .F(), .Q(set_pulse));
  (* keep, BEL = "X15Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00DC), .FF_USED(1'b1))
    status_storage(.CLK(hclk),
                   .I({reset_request, status, set_pulse, clear_pulse}),
                   .F(), .Q(status));

  (* keep, BEL = "X15Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF888), .FF_USED(1'b0))
    high_mux0(.CLK(hclk),
              .I({status, select_status, counter[0], select_counter}),
              .F(high_read[0]), .Q());
  (* keep, BEL = "X15Y11_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    high_mux1(.CLK(hclk), .I({2'b00, counter[1], select_counter}),
              .F(high_read[1]), .Q());
  (* keep, BEL = "X15Y11_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    high_mux2(.CLK(hclk), .I({2'b00, counter[2], select_counter}),
              .F(high_read[2]), .Q());

  // F1E0 = (counter/status selected) ? high_read : low_read.
  // HRDATA0 has one additional output buffer, so this intermediate mux is
  // not MCU-pinpacked and must use an ordinary qualified even slice.
  (* keep, BEL = "X15Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF1E0), .FF_USED(1'b0))
    class_mux0(.CLK(hclk), .I({low_read[0], high_read[0],
                               select_status, select_counter}),
               .F(hrdata[0]), .Q());
  (* keep, BEL = "X15Y11_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF1E0), .FF_USED(1'b0))
    class_mux1(.CLK(hclk), .I({low_read[1], high_read[1],
                               select_status, select_counter}),
               .F(hrdata[1]), .Q());
  (* keep, BEL = "X15Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF1E0), .FF_USED(1'b0))
    class_mux2(.CLK(hclk), .I({low_read[2], high_read[2],
                               select_status, select_counter}),
               .F(hrdata[2]), .Q());
  (* keep, BEL = "X15Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h1100), .FF_USED(1'b0))
    class_mux3(.CLK(hclk), .I({low_read[3], 1'b0,
                               select_status, select_counter}),
               .F(hrdata[3]), .Q());
  (* keep, BEL = "X15Y11_SLICE9" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h1100), .FF_USED(1'b0))
    class_mux4(.CLK(hclk), .I({low_read[4], 1'b0,
                               select_status, select_counter}),
               .F(hrdata[4]), .Q());
  (* keep, BEL = "X15Y11_SLICE11" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h1100), .FF_USED(1'b0))
    class_mux5(.CLK(hclk), .I({low_read[5], 1'b0,
                               select_status, select_counter}),
               .F(hrdata[5]), .Q());
  (* keep, BEL = "X15Y11_SLICE13" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h1100), .FF_USED(1'b0))
    class_mux6(.CLK(hclk), .I({low_read[6], 1'b0,
                               select_status, select_counter}),
               .F(hrdata[6]), .Q());
  (* keep, BEL = "X15Y11_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h1100), .FF_USED(1'b0))
    class_mux7(.CLK(hclk), .I({low_read[7], 1'b0,
                               select_status, select_counter}),
               .F(hrdata[7]), .Q());
`else
  assign hrdata = (select_counter || select_status) ?
                  {5'b00000, high_read} : low_read;

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      // Read-address classification remains live while state is held reset,
      // matching the explicit synthesis stages.
      select_scratch <= !haddr3 && haddr2;
      select_counter <= haddr3 && !haddr2;
      select_status <= haddr3 && haddr2;
      scratch_commit_root <= 1'b0;
      status_commit_root <= 1'b0;
      write_data_pipe1 <= 1'b0;
      write_data_pipe5 <= 1'b0;
      scratch <= 8'h00;
      set_pulse <= 1'b0;
      clear_pulse <= 1'b0;
      status <= 1'b0;
    end else begin
      write_data_pipe1 <= hwdata[1];
      write_data_pipe5 <= hwdata[5];
      if (scratch_commit_root)
        scratch <= {hwdata[7], scratch[6], write_data_pipe5,
                    hwdata[4:2], write_data_pipe1, hwdata[0]};
      if (scratch_commit_now)
        scratch[6] <= hwdata[6];
      set_pulse <= status_commit_root && low_read[1];
      clear_pulse <= status_commit_root && low_read[0];
      if (set_pulse)
        status <= 1'b1;
      else if (clear_pulse)
        status <= 1'b0;
      scratch_commit_root <= write_pending && select_scratch;
      status_commit_root <= write_pending && select_status;
      write_pending <= write_ready_f && htrans1 && hwrite;
      select_scratch <= !haddr3 && haddr2;
      select_counter <= haddr3 && !haddr2;
      select_status <= haddr3 && haddr2;
    end
  end
`endif
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2, haddr3;
  wire reset_request;
  wire [7:0] hwdata, readback;
  wire hrdata0, hreadyout, hresp;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
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
  agamemnon_ahb_register_bank_combined_wait_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3), .hwdata(hwdata),
    .reset_request(reset_request), .hreadyout(hreadyout), .hresp(hresp),
    .hrdata(readback));
endmodule
