// AG32 hard-boundary binding for the bounded read-only fabric AHB master.
//
// This wrapper is intentionally complete: every request qualifier, address
// lane, response qualifier and read-data lane is bound to its exact hard-port
// identity. The release packer still refuses the dynamic request topology
// before placement until its independently sourced routes are qualified.
module agamemnon_fabric_ahb_read_master_ag32 #(
  parameter integer TIMEOUT_CYCLES = 16
) (
  input  wire        start,
  input  wire [31:0] address,
  output wire        busy,
  output wire        done,
  output wire        error,
  output wire        timed_out,
  output wire [31:0] read_data
);
  wire hclk;
  wire hresetn;
  wire hsel;
  wire hready;
  wire [1:0] htrans;
  wire [2:0] hsize;
  wire [2:0] hburst;
  wire hwrite;
  wire [31:0] haddr;
  wire [31:0] hwdata;
  wire hreadyout;
  wire hresp;
  wire [31:0] hrdata;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_RESETN mcu_resetn(.RESETN(hresetn));

  agamemnon_fabric_ahb_read_master #(
    .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
  ) master (
    .HCLK(hclk), .HRESETn(hresetn), .start(start), .address(address),
    .busy(busy), .done(done), .error(error), .timed_out(timed_out),
    .read_data(read_data), .HSEL(hsel), .HREADY(hready),
    .HTRANS(htrans), .HSIZE(hsize), .HBURST(hburst),
    .HWRITE(hwrite), .HADDR(haddr), .HWDATA(hwdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .HRDATA(hrdata)
  );

  (* keep *) MCU_SLAVE_AHB_HSEL mcu_slave_hsel(.DOUT(hsel));
  (* keep *) MCU_SLAVE_AHB_HREADY mcu_slave_hready(.DOUT(hready));
  (* keep *) MCU_SLAVE_AHB_HTRANS0 mcu_slave_htrans0(.DOUT(htrans[0]));
  (* keep *) MCU_SLAVE_AHB_HTRANS1 mcu_slave_htrans1(.DOUT(htrans[1]));
  (* keep *) MCU_SLAVE_AHB_HSIZE0 mcu_slave_hsize0(.DOUT(hsize[0]));
  (* keep *) MCU_SLAVE_AHB_HSIZE1 mcu_slave_hsize1(.DOUT(hsize[1]));
  (* keep *) MCU_SLAVE_AHB_HSIZE2 mcu_slave_hsize2(.DOUT(hsize[2]));
  (* keep *) MCU_SLAVE_AHB_HBURST0 mcu_slave_hburst0(.DOUT(hburst[0]));
  (* keep *) MCU_SLAVE_AHB_HBURST1 mcu_slave_hburst1(.DOUT(hburst[1]));
  (* keep *) MCU_SLAVE_AHB_HBURST2 mcu_slave_hburst2(.DOUT(hburst[2]));
  (* keep *) MCU_SLAVE_AHB_HWRITE mcu_slave_hwrite(.DOUT(hwrite));

  (* keep *) MCU_DOUT mcu_slave_haddr0(.DOUT(haddr[0]));
  (* keep *) MCU_DOUT mcu_slave_haddr1(.DOUT(haddr[1]));
  (* keep *) MCU_DOUT mcu_slave_haddr2(.DOUT(haddr[2]));
  (* keep *) MCU_DOUT mcu_slave_haddr3(.DOUT(haddr[3]));
  (* keep *) MCU_DOUT mcu_slave_haddr4(.DOUT(haddr[4]));
  (* keep *) MCU_DOUT mcu_slave_haddr5(.DOUT(haddr[5]));
  (* keep *) MCU_DOUT mcu_slave_haddr6(.DOUT(haddr[6]));
  (* keep *) MCU_DOUT mcu_slave_haddr7(.DOUT(haddr[7]));
  (* keep *) MCU_DOUT mcu_slave_haddr8(.DOUT(haddr[8]));
  (* keep *) MCU_DOUT mcu_slave_haddr9(.DOUT(haddr[9]));
  (* keep *) MCU_DOUT mcu_slave_haddr10(.DOUT(haddr[10]));
  (* keep *) MCU_DOUT mcu_slave_haddr11(.DOUT(haddr[11]));
  (* keep *) MCU_DOUT mcu_slave_haddr12(.DOUT(haddr[12]));
  (* keep *) MCU_DOUT mcu_slave_haddr13(.DOUT(haddr[13]));
  (* keep *) MCU_DOUT mcu_slave_haddr14(.DOUT(haddr[14]));
  (* keep *) MCU_DOUT mcu_slave_haddr15(.DOUT(haddr[15]));
  (* keep *) MCU_DOUT mcu_slave_haddr16(.DOUT(haddr[16]));
  (* keep *) MCU_DOUT mcu_slave_haddr17(.DOUT(haddr[17]));
  (* keep *) MCU_DOUT mcu_slave_haddr18(.DOUT(haddr[18]));
  (* keep *) MCU_DOUT mcu_slave_haddr19(.DOUT(haddr[19]));
  (* keep *) MCU_DOUT mcu_slave_haddr20(.DOUT(haddr[20]));
  (* keep *) MCU_DOUT mcu_slave_haddr21(.DOUT(haddr[21]));
  (* keep *) MCU_DOUT mcu_slave_haddr22(.DOUT(haddr[22]));
  (* keep *) MCU_DOUT mcu_slave_haddr23(.DOUT(haddr[23]));
  (* keep *) MCU_DOUT mcu_slave_haddr24(.DOUT(haddr[24]));
  (* keep *) MCU_DOUT mcu_slave_haddr25(.DOUT(haddr[25]));
  (* keep *) MCU_DOUT mcu_slave_haddr26(.DOUT(haddr[26]));
  (* keep *) MCU_DOUT mcu_slave_haddr27(.DOUT(haddr[27]));
  (* keep *) MCU_DOUT mcu_slave_haddr28(.DOUT(haddr[28]));
  (* keep *) MCU_DOUT mcu_slave_haddr29(.DOUT(haddr[29]));
  (* keep *) MCU_DOUT mcu_slave_haddr30(.DOUT(haddr[30]));
  (* keep *) MCU_DOUT mcu_slave_haddr31(.DOUT(haddr[31]));

  (* keep *) MCU_DOUT mcu_slave_hwdata0(.DOUT(hwdata[0]));
  (* keep *) MCU_DOUT mcu_slave_hwdata1(.DOUT(hwdata[1]));
  (* keep *) MCU_DOUT mcu_slave_hwdata2(.DOUT(hwdata[2]));
  (* keep *) MCU_DOUT mcu_slave_hwdata3(.DOUT(hwdata[3]));
  (* keep *) MCU_DOUT mcu_slave_hwdata4(.DOUT(hwdata[4]));
  (* keep *) MCU_DOUT mcu_slave_hwdata5(.DOUT(hwdata[5]));
  (* keep *) MCU_DOUT mcu_slave_hwdata6(.DOUT(hwdata[6]));
  (* keep *) MCU_DOUT mcu_slave_hwdata7(.DOUT(hwdata[7]));
  (* keep *) MCU_DOUT mcu_slave_hwdata8(.DOUT(hwdata[8]));
  (* keep *) MCU_DOUT mcu_slave_hwdata9(.DOUT(hwdata[9]));
  (* keep *) MCU_DOUT mcu_slave_hwdata10(.DOUT(hwdata[10]));
  (* keep *) MCU_DOUT mcu_slave_hwdata11(.DOUT(hwdata[11]));
  (* keep *) MCU_DOUT mcu_slave_hwdata12(.DOUT(hwdata[12]));
  (* keep *) MCU_DOUT mcu_slave_hwdata13(.DOUT(hwdata[13]));
  (* keep *) MCU_DOUT mcu_slave_hwdata14(.DOUT(hwdata[14]));
  (* keep *) MCU_DOUT mcu_slave_hwdata15(.DOUT(hwdata[15]));
  (* keep *) MCU_DOUT mcu_slave_hwdata16(.DOUT(hwdata[16]));
  (* keep *) MCU_DOUT mcu_slave_hwdata17(.DOUT(hwdata[17]));
  (* keep *) MCU_DOUT mcu_slave_hwdata18(.DOUT(hwdata[18]));
  (* keep *) MCU_DOUT mcu_slave_hwdata19(.DOUT(hwdata[19]));
  (* keep *) MCU_DOUT mcu_slave_hwdata20(.DOUT(hwdata[20]));
  (* keep *) MCU_DOUT mcu_slave_hwdata21(.DOUT(hwdata[21]));
  (* keep *) MCU_DOUT mcu_slave_hwdata22(.DOUT(hwdata[22]));
  (* keep *) MCU_DOUT mcu_slave_hwdata23(.DOUT(hwdata[23]));
  (* keep *) MCU_DOUT mcu_slave_hwdata24(.DOUT(hwdata[24]));
  (* keep *) MCU_DOUT mcu_slave_hwdata25(.DOUT(hwdata[25]));
  (* keep *) MCU_DOUT mcu_slave_hwdata26(.DOUT(hwdata[26]));
  (* keep *) MCU_DOUT mcu_slave_hwdata27(.DOUT(hwdata[27]));
  (* keep *) MCU_DOUT mcu_slave_hwdata28(.DOUT(hwdata[28]));
  (* keep *) MCU_DOUT mcu_slave_hwdata29(.DOUT(hwdata[29]));
  (* keep *) MCU_DOUT mcu_slave_hwdata30(.DOUT(hwdata[30]));
  (* keep *) MCU_DOUT mcu_slave_hwdata31(.DOUT(hwdata[31]));

  (* keep *) MCU_SLAVE_AHB_HREADYOUT mcu_slave_hreadyout(.DIN(hreadyout));
  (* keep *) MCU_SLAVE_AHB_HRESP mcu_slave_hresp(.DIN(hresp));
  (* keep *) MCU_SLAVE_AHB_HRDATA0 mcu_slave_hrdata0(.DIN(hrdata[0]));
  (* keep *) MCU_SLAVE_AHB_HRDATA1 mcu_slave_hrdata1(.DIN(hrdata[1]));
  (* keep *) MCU_SLAVE_AHB_HRDATA2 mcu_slave_hrdata2(.DIN(hrdata[2]));
  (* keep *) MCU_SLAVE_AHB_HRDATA3 mcu_slave_hrdata3(.DIN(hrdata[3]));
  (* keep *) MCU_SLAVE_AHB_HRDATA4 mcu_slave_hrdata4(.DIN(hrdata[4]));
  (* keep *) MCU_SLAVE_AHB_HRDATA5 mcu_slave_hrdata5(.DIN(hrdata[5]));
  (* keep *) MCU_SLAVE_AHB_HRDATA6 mcu_slave_hrdata6(.DIN(hrdata[6]));
  (* keep *) MCU_SLAVE_AHB_HRDATA7 mcu_slave_hrdata7(.DIN(hrdata[7]));
  (* keep *) MCU_SLAVE_AHB_HRDATA8 mcu_slave_hrdata8(.DIN(hrdata[8]));
  (* keep *) MCU_SLAVE_AHB_HRDATA9 mcu_slave_hrdata9(.DIN(hrdata[9]));
  (* keep *) MCU_SLAVE_AHB_HRDATA10 mcu_slave_hrdata10(.DIN(hrdata[10]));
  (* keep *) MCU_SLAVE_AHB_HRDATA11 mcu_slave_hrdata11(.DIN(hrdata[11]));
  (* keep *) MCU_SLAVE_AHB_HRDATA12 mcu_slave_hrdata12(.DIN(hrdata[12]));
  (* keep *) MCU_SLAVE_AHB_HRDATA13 mcu_slave_hrdata13(.DIN(hrdata[13]));
  (* keep *) MCU_SLAVE_AHB_HRDATA14 mcu_slave_hrdata14(.DIN(hrdata[14]));
  (* keep *) MCU_SLAVE_AHB_HRDATA15 mcu_slave_hrdata15(.DIN(hrdata[15]));
  (* keep *) MCU_SLAVE_AHB_HRDATA16 mcu_slave_hrdata16(.DIN(hrdata[16]));
  (* keep *) MCU_SLAVE_AHB_HRDATA17 mcu_slave_hrdata17(.DIN(hrdata[17]));
  (* keep *) MCU_SLAVE_AHB_HRDATA18 mcu_slave_hrdata18(.DIN(hrdata[18]));
  (* keep *) MCU_SLAVE_AHB_HRDATA19 mcu_slave_hrdata19(.DIN(hrdata[19]));
  (* keep *) MCU_SLAVE_AHB_HRDATA20 mcu_slave_hrdata20(.DIN(hrdata[20]));
  (* keep *) MCU_SLAVE_AHB_HRDATA21 mcu_slave_hrdata21(.DIN(hrdata[21]));
  (* keep *) MCU_SLAVE_AHB_HRDATA22 mcu_slave_hrdata22(.DIN(hrdata[22]));
  (* keep *) MCU_SLAVE_AHB_HRDATA23 mcu_slave_hrdata23(.DIN(hrdata[23]));
  (* keep *) MCU_SLAVE_AHB_HRDATA24 mcu_slave_hrdata24(.DIN(hrdata[24]));
  (* keep *) MCU_SLAVE_AHB_HRDATA25 mcu_slave_hrdata25(.DIN(hrdata[25]));
  (* keep *) MCU_SLAVE_AHB_HRDATA26 mcu_slave_hrdata26(.DIN(hrdata[26]));
  (* keep *) MCU_SLAVE_AHB_HRDATA27 mcu_slave_hrdata27(.DIN(hrdata[27]));
  (* keep *) MCU_SLAVE_AHB_HRDATA28 mcu_slave_hrdata28(.DIN(hrdata[28]));
  (* keep *) MCU_SLAVE_AHB_HRDATA29 mcu_slave_hrdata29(.DIN(hrdata[29]));
  (* keep *) MCU_SLAVE_AHB_HRDATA30 mcu_slave_hrdata30(.DIN(hrdata[30]));
  (* keep *) MCU_SLAVE_AHB_HRDATA31 mcu_slave_hrdata31(.DIN(hrdata[31]));
endmodule
