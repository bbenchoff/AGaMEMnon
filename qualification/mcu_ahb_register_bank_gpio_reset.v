// SRAM qualification top for the pipelined External-AHB register bank.
//
// Reset is the already-qualified GPIO4.1 -> MCU0 fabric input and is applied
// synchronously by the protocol core.  The hard MCU_RESETN boundary remains
// deliberately unused here because its slice delivery is not qualified.
module top;
  localparam [31:0] BASE_ADDR = 32'h6000_0000;
  localparam [31:0] HADDR_SEEN_MASK = 32'h0000_003e;

  wire hclk, hready, hwrite;
  wire [1:0] htrans;
  wire [2:0] hsize, hburst;
  wire [31:0] haddr, hwdata, hrdata, hrdata_core;
  wire hreadyout, hresp;
  wire reset_request;
  wire [31:0] scratch, counter, status;

  (* keep *) MCU mcu_reset_control(.DIN(reset_request));

  // Qualification-only narrow hard-port binding. Instantiate only lanes with
  // recovered logic corridors and tie every unseen lane off. In particular,
  // HADDR[0] and hard MCU_RESETN remain absent rather than masquerading as
  // usable boundary signals.
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_AHB_HREADY mcu_hready(.DIN(hready));
  (* keep *) MCU_AHB_HTRANS0 mcu_htrans0(.DIN(htrans[0]));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans[1]));
  (* keep *) MCU_AHB_HSIZE0 mcu_hsize0(.DIN(hsize[0]));
  (* keep *) MCU_AHB_HSIZE1 mcu_hsize1(.DIN(hsize[1]));
  (* keep *) MCU_AHB_HSIZE2 mcu_hsize2(.DIN(hsize[2]));
  (* keep *) MCU_AHB_HBURST0 mcu_hburst0(.DIN(hburst[0]));
  (* keep *) MCU_AHB_HBURST1 mcu_hburst1(.DIN(hburst[1]));
  (* keep *) MCU_AHB_HBURST2 mcu_hburst2(.DIN(hburst[2]));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));

  assign haddr[31:6] = 26'b0;
  assign haddr[0] = 1'b0;
  (* keep *) MCU_DIN mcu_haddr1(.DIN(haddr[1]));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr[2]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr[3]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(haddr[4]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(haddr[5]));

  assign hwdata[31:8] = 24'b0;
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
  (* keep *) MCU_DOUT mcu_hrdata0(.DOUT(hrdata[0]));
  (* keep *) MCU_DOUT mcu_hrdata1(.DOUT(hrdata[1]));
  (* keep *) MCU_DOUT mcu_hrdata2(.DOUT(hrdata[2]));
  (* keep *) MCU_DOUT mcu_hrdata3(.DOUT(hrdata[3]));
  (* keep *) MCU_DOUT mcu_hrdata4(.DOUT(hrdata[4]));
  (* keep *) MCU_DOUT mcu_hrdata5(.DOUT(hrdata[5]));
  (* keep *) MCU_DOUT mcu_hrdata6(.DOUT(hrdata[6]));
  (* keep *) MCU_DOUT mcu_hrdata7(.DOUT(hrdata[7]));

  wire [31:0] haddr_seen = (haddr & HADDR_SEEN_MASK) |
                           (BASE_ADDR & ~HADDR_SEEN_MASK);
  wire [31:0] hwdata_seen = hwdata & 32'h0000_00ff;
  // First hardware boundary: qualify the lower byte before broadening the
  // dynamic return mux to all 32 lanes. Upper HRDATA lanes remain constant
  // zero and therefore require no fabric exit-driver allocation.
  assign hrdata = hrdata_core & 32'h0000_00ff;
  wire [31:0] status_set = {31'b0, scratch[0]};

  agamemnon_ahb_register_bank #(
    .BASE_ADDR(BASE_ADDR), .ID_VALUE(32'h4147_414d), .WAIT_STATES(0),
    .PIPELINE_WRITE_DATA(1), .ALLOW_BYTE(0)
  ) bank_i (
    .HCLK(hclk), .HRESETn(~reset_request), .HSEL(1'b1),
    .HADDR(haddr_seen), .HTRANS(htrans), .HWRITE(hwrite),
    .HSIZE(hsize), .HBURST(hburst), .HWDATA(hwdata_seen),
    .HREADY(hready), .HRDATA(hrdata_core), .HREADYOUT(hreadyout),
    .HRESP(hresp), .STATUS_SET(status_set), .SCRATCH(scratch),
    .COUNTER(counter), .STATUS(status));
endmodule
