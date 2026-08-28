// Exact-source AG32 lowering for bounded read-only SRAM-base probes.
//
// The recovered request-side profile can present only two aligned addresses:
// 0x20000000 and 0x20000004. HADDR[29] is the registered HSEL net,
// HADDR[0]/HADDR[1] are the registered low HSIZE nets, HADDR[2] has its own
// exact registered source, and every other HADDR/HWDATA lane is hard low.
// The exact request-side HREADY source is held high, while the FSM retains
// HSEL/HTRANS until the physical slave HREADYOUT ingress acknowledges the
// transfer. The retained response ingress exposes only a one-bit XOR of
// {HRDATA[0], HREADYOUT, HRESP}; it does not claim a 32-bit data capture.
module agamemnon_fabric_ahb_read_master_ag32_sram_base (
  input  wire        start,
  input  wire        word_select,
  output reg         busy,
  output reg         done,
  output wire        response_observation,
  output reg         response_sampled,
  output reg         response_valid,
  output wire [1:0]  debug_state,
  output wire        fabric_clock,
  output wire        fabric_resetn
);
  wire hclk;
  wire hresetn;
  wire hreadyout;
  wire hready_complete;
  wire hresp;
  wire hrdata0;

  localparam [1:0] STATE_IDLE = 2'd0;
  localparam [1:0] STATE_ADDR = 2'd1;
  localparam [1:0] STATE_PRESENT = 2'd3;
  localparam [1:0] STATE_DATA = 2'd2;
  reg [1:0] state;
  assign debug_state = state;
  reg selected_word;
  // The active states share state[0], avoiding a second decode cone on the
  // two exact request registers.
  (* keep *) wire core_hsel = state[0];
  (* keep *) wire core_htrans1 = state[0];

  // These are the eleven distinct retained request-control register nets.
  // Their order is HSEL, HREADY, HTRANS[0:1], HSIZE[0:2], HBURST[0:2], HWRITE.
  wire [10:0] control;
  wire haddr2_presented;
  (* keep *) wire request_low_omux0;
  (* keep *) wire request_low_omux2;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_RESETN mcu_resetn(.RESETN(hresetn));
  assign fabric_clock = hclk;
  assign fabric_resetn = hresetn;

  // AG32 fabric FFs do not support an asynchronous reset. This bounded FSM
  // samples the hard reset synchronously and explicitly includes the physical
  // request-register presentation cycle before sampling the response.
  always @(posedge hclk) begin
    if (!hresetn) begin
      state <= STATE_IDLE;
      selected_word <= 1'b0;
      busy <= 1'b0;
      done <= 1'b0;
      response_sampled <= 1'b0;
      response_valid <= 1'b0;
    end else begin
      done <= 1'b0;
      case (state)
        STATE_IDLE: begin
          busy <= 1'b0;
          if (start) begin
            selected_word <= word_select;
            busy <= 1'b1;
            response_valid <= 1'b0;
            state <= STATE_ADDR;
          end
        end
        STATE_ADDR: state <= STATE_PRESENT;
        STATE_PRESENT: begin
          // Keep the physical registered request asserted across wait states.
          // Capture only on the slave's witnessed completion cycle.
          if (hready_complete) begin
            response_sampled <= response_observation;
            response_valid <= 1'b1;
            state <= STATE_DATA;
          end
        end
        default: begin
          busy <= 1'b0;
          done <= 1'b1;
          state <= STATE_IDLE;
        end
      endcase
    end
  end

  // INIT=AAAA passes I[0] through the LUT into the physical request FF.
  (* keep, BEL="X14Y7_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) source_hsel_haddr29(
    .CLK(hclk), .I({3'b000, core_hsel}), .F(), .Q(control[0]));
  // Zero-wait-only profile: the slave-facing HREADY input is always high.
  (* keep, BEL="X14Y10_SLICE9" *)
  GENERIC_SLICE #(.INIT(16'hFFFF), .FF_USED(1)) source_hready(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[1]));
  (* keep, BEL="X14Y7_SLICE11" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_htrans0(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[2]));
  (* keep, BEL="X16Y7_SLICE12" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) source_htrans1(
    .CLK(hclk), .I({3'b000, core_htrans1}), .F(), .Q(control[3]));
  (* keep, BEL="X16Y10_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_hsize0(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[4]));
  (* keep, BEL="X17Y8_SLICE0" *)
  GENERIC_SLICE #(.INIT(16'hFFFF), .FF_USED(1)) source_hsize1(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[5]));
  (* keep, BEL="X14Y10_SLICE10" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_hsize2(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[6]));
  (* keep, BEL="X14Y7_SLICE12" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_hburst0(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[7]));
  (* keep, BEL="X14Y10_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_hburst1(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[8]));
  (* keep, BEL="X17Y8_SLICE2" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_hburst2(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[9]));
  (* keep, BEL="X17Y8_SLICE12" *)
  GENERIC_SLICE #(.INIT(16'h0000), .FF_USED(1)) source_hwrite(
    .CLK(hclk), .I(4'b0000), .F(), .Q(control[10]));

  (* keep, BEL="X18Y9_SLICE15" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) source_haddr2(
    .CLK(hclk), .I({3'b000, selected_word}), .F(),
    .Q(haddr2_presented));

  (* keep, BEL="X14Y12_DUAL_SLICE0" *)
  AGRV2K_DUAL_LUT_CONST #(.VALUE(1'b0)) request_low_source(
    .F0(request_low_omux0), .F2(request_low_omux2));

  (* keep *) MCU_SLAVE_AHB_HSEL hsel(.DOUT(control[0]));
  (* keep *) MCU_SLAVE_AHB_HREADY hready(.DOUT(control[1]));
  (* keep *) MCU_SLAVE_AHB_HTRANS0 htrans0(.DOUT(control[2]));
  (* keep *) MCU_SLAVE_AHB_HTRANS1 htrans1(.DOUT(control[3]));
  (* keep *) MCU_SLAVE_AHB_HSIZE0 hsize0(.DOUT(control[4]));
  (* keep *) MCU_SLAVE_AHB_HSIZE1 hsize1(.DOUT(control[5]));
  (* keep *) MCU_SLAVE_AHB_HSIZE2 hsize2(.DOUT(control[6]));
  (* keep *) MCU_SLAVE_AHB_HBURST0 hburst0(.DOUT(control[7]));
  (* keep *) MCU_SLAVE_AHB_HBURST1 hburst1(.DOUT(control[8]));
  (* keep *) MCU_SLAVE_AHB_HBURST2 hburst2(.DOUT(control[9]));
  (* keep *) MCU_SLAVE_AHB_HWRITE hwrite(.DOUT(control[10]));

  (* keep *) MCU_DOUT haddr0(.DOUT(control[4]));
  (* keep *) MCU_DOUT haddr1(.DOUT(control[6]));
  (* keep *) MCU_DOUT haddr2(.DOUT(haddr2_presented));
  (* keep *) MCU_DOUT haddr3(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr4(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr5(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr6(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr7(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr8(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr9(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr10(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr11(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr12(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr13(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr14(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr15(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr16(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr17(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr18(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr19(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr20(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr21(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr22(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr23(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr24(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr25(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr26(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr27(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr28(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr29(.DOUT(control[0]));
  (* keep *) MCU_DOUT haddr30(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr31(.DOUT(request_low_omux0));

  (* keep *) MCU_DOUT hwdata0(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata1(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata2(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata3(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata4(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata5(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata6(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata7(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata8(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata9(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata10(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata11(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata12(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata13(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata14(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata15(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata16(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata17(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata18(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata19(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata20(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata21(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata22(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata23(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata24(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata25(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata26(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata27(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata28(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata29(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata30(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata31(.DOUT(request_low_omux0));

  (* keep *) MCU_SLAVE_AHB_HREADYOUT mcu_slave_hreadyout(.DIN(hreadyout));
  (* keep *) MCU_SLAVE_AHB_HRESP mcu_slave_hresp(.DIN(hresp));
  (* keep *) MCU_SLAVE_AHB_HRDATA0 mcu_slave_hrdata0(.DIN(hrdata0));

  // Keep the ready decision on the same witnessed landing tile as the
  // response signature instead of asking the placer to guess a reachable
  // consumer for this fixed MCU ingress.
  (* keep, BEL="X14Y9_SLICE2" *)
  LUT #(.K(4), .INIT(16'hAAAA)) response_ready_probe(
    .I({3'b000, hreadyout}), .Q(hready_complete));

  // Exact simultaneous retained response landing. The XOR makes all three
  // witnessed physical inputs observable while preserving the evidence-bounded
  // claim: this is one response signature bit, not independent status/data.
  (* keep, BEL="X14Y9_SLICE0" *)
  LUT #(.K(4), .INIT(16'h6996)) response_probe(
    .I({hrdata0, hreadyout, hresp, 1'b0}), .Q(response_observation));
endmodule
