// True held 16-bit External-AHB scratch using the silicon-qualified one-wait
// controller and one external combinational feedback buffer per state bit.
//
// Fifteen state cells retain the exact silicon-qualified posted-capture16
// BELs. Lane 12 is the sole unavoidable exception: its posted BEL is
// X14Y11_SLICE6, which is also the qualified write-wait LUT/OMUX20 source.
// Keeping both functions there would require an unqualified direct-D split and
// would ask OMUX20 to carry two different nets. Lane 12 is therefore left for
// the strict placer, while the qualified wait controller keeps slice6.
//
// For every lane, INIT 0B08 implements
//   reset ? 0 : write_pending ? HWDATA[i] : feedback[i]
// and a separate kept identity LUT returns state Q to that feedback input.
// No LUT consumes the Q of its own FF, so the design uses no direct-D cells.
(* top *)
module top;
  wire hclk, htrans1, hwrite, reset_request;
  wire write_pending, write_ready_f, hresp;
  wire [15:0] hwdata, state, feedback;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(write_ready_f));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));

  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata[0]));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata[1]));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata[2]));
  (* keep *) MCU_DIN mcu_hwdata3(.DIN(hwdata[3]));
  (* keep *) MCU_DIN mcu_hwdata4(.DIN(hwdata[4]));
  (* keep *) MCU_DIN mcu_hwdata5(.DIN(hwdata[5]));
  (* keep *) MCU_DIN mcu_hwdata6(.DIN(hwdata[6]));
  (* keep *) MCU_DIN mcu_hwdata7(.DIN(hwdata[7]));
  (* keep *) MCU_DIN mcu_hwdata8(.DIN(hwdata[8]));
  (* keep *) MCU_DIN mcu_hwdata9(.DIN(hwdata[9]));
  (* keep *) MCU_DIN mcu_hwdata10(.DIN(hwdata[10]));
  (* keep *) MCU_DIN mcu_hwdata11(.DIN(hwdata[11]));
  (* keep *) MCU_DIN mcu_hwdata12(.DIN(hwdata[12]));
  (* keep *) MCU_DIN mcu_hwdata13(.DIN(hwdata[13]));
  (* keep *) MCU_DIN mcu_hwdata14(.DIN(hwdata[14]));
  (* keep *) MCU_DIN mcu_hwdata15(.DIN(hwdata[15]));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(state[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(state[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(state[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(state[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(state[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(state[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(state[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(state[7]));
  (* keep *) MCU_DOUT mcu_h8(.DOUT(state[8]));
  (* keep *) MCU_DOUT mcu_h9(.DOUT(state[9]));
  (* keep *) MCU_DOUT mcu_h10(.DOUT(state[10]));
  (* keep *) MCU_DOUT mcu_h11(.DOUT(state[11]));
  (* keep *) MCU_DOUT mcu_h12(.DOUT(state[12]));
  (* keep *) MCU_DOUT mcu_h13(.DOUT(state[13]));
  (* keep *) MCU_DOUT mcu_h14(.DOUT(state[14]));
  (* keep *) MCU_DOUT mcu_h15(.DOUT(state[15]));

  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0080), .FF_USED(1'b1))
    write_stage(.CLK(hclk),
                .I({reset_request, write_ready_f, hwrite, htrans1}),
                .F(), .Q(write_pending));

  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDDDD), .FF_USED(1'b0))
    write_wait_stage(.CLK(hclk),
                     .I({2'b00, reset_request, write_pending}),
                     .F(write_ready_f), .Q());

  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture0(.CLK(hclk), .I({feedback[0], reset_request, write_pending, hwdata[0]}), .F(), .Q(state[0]));
  (* keep, BEL = "X14Y10_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture1(.CLK(hclk), .I({feedback[1], reset_request, write_pending, hwdata[1]}), .F(), .Q(state[1]));
  (* keep, BEL = "X15Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture2(.CLK(hclk), .I({feedback[2], reset_request, write_pending, hwdata[2]}), .F(), .Q(state[2]));
  (* keep, BEL = "X15Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture3(.CLK(hclk), .I({feedback[3], reset_request, write_pending, hwdata[3]}), .F(), .Q(state[3]));
  (* keep, BEL = "X15Y12_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture4(.CLK(hclk), .I({feedback[4], reset_request, write_pending, hwdata[4]}), .F(), .Q(state[4]));
  (* keep, BEL = "X15Y12_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture5(.CLK(hclk), .I({feedback[5], reset_request, write_pending, hwdata[5]}), .F(), .Q(state[5]));
  (* keep, BEL = "X15Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture6(.CLK(hclk), .I({feedback[6], reset_request, write_pending, hwdata[6]}), .F(), .Q(state[6]));
  (* keep, BEL = "X14Y12_SLICE13" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture7(.CLK(hclk), .I({feedback[7], reset_request, write_pending, hwdata[7]}), .F(), .Q(state[7]));
  (* keep, BEL = "X14Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture8(.CLK(hclk), .I({feedback[8], reset_request, write_pending, hwdata[8]}), .F(), .Q(state[8]));
  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture9(.CLK(hclk), .I({feedback[9], reset_request, write_pending, hwdata[9]}), .F(), .Q(state[9]));
  (* keep, BEL = "X14Y11_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture10(.CLK(hclk), .I({feedback[10], reset_request, write_pending, hwdata[10]}), .F(), .Q(state[10]));
  (* keep, BEL = "X14Y11_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture11(.CLK(hclk), .I({feedback[11], reset_request, write_pending, hwdata[11]}), .F(), .Q(state[11]));
  // Posted capture12's X14Y11_SLICE6 is occupied by write_wait_stage.
  (* keep *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture12(.CLK(hclk), .I({feedback[12], reset_request, write_pending, hwdata[12]}), .F(), .Q(state[12]));
  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture13(.CLK(hclk), .I({feedback[13], reset_request, write_pending, hwdata[13]}), .F(), .Q(state[13]));
  (* keep, BEL = "X14Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture14(.CLK(hclk), .I({feedback[14], reset_request, write_pending, hwdata[14]}), .F(), .Q(state[14]));
  (* keep, BEL = "X14Y11_SLICE13" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture15(.CLK(hclk), .I({feedback[15], reset_request, write_pending, hwdata[15]}), .F(), .Q(state[15]));

  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer0(.CLK(hclk), .I({3'b000, state[0]}), .F(feedback[0]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer1(.CLK(hclk), .I({3'b000, state[1]}), .F(feedback[1]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer2(.CLK(hclk), .I({3'b000, state[2]}), .F(feedback[2]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer3(.CLK(hclk), .I({3'b000, state[3]}), .F(feedback[3]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer4(.CLK(hclk), .I({3'b000, state[4]}), .F(feedback[4]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer5(.CLK(hclk), .I({3'b000, state[5]}), .F(feedback[5]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer6(.CLK(hclk), .I({3'b000, state[6]}), .F(feedback[6]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer7(.CLK(hclk), .I({3'b000, state[7]}), .F(feedback[7]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer8(.CLK(hclk), .I({3'b000, state[8]}), .F(feedback[8]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer9(.CLK(hclk), .I({3'b000, state[9]}), .F(feedback[9]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer10(.CLK(hclk), .I({3'b000, state[10]}), .F(feedback[10]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer11(.CLK(hclk), .I({3'b000, state[11]}), .F(feedback[11]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer12(.CLK(hclk), .I({3'b000, state[12]}), .F(feedback[12]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer13(.CLK(hclk), .I({3'b000, state[13]}), .F(feedback[13]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer14(.CLK(hclk), .I({3'b000, state[14]}), .F(feedback[14]), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0)) feedback_buffer15(.CLK(hclk), .I({3'b000, state[15]}), .F(feedback[15]), .Q());

  assign hresp = 1'b0;
endmodule
