// Typed binding of the AG32 MCU External AHB slave port to the recovered hard
// interface. Signal directions are relative to a user peripheral in fabric.
module agamemnon_mcu_ahb_port (
  output wire        HCLK,
  output wire        HRESETn,
  output wire        HREADY,
  output wire [1:0]  HTRANS,
  output wire [2:0]  HSIZE,
  output wire [2:0]  HBURST,
  output wire        HWRITE,
  output wire [31:0] HADDR,
  output wire [31:0] HWDATA,
  input  wire        HREADYOUT,
  input  wire        HRESP,
  input  wire [31:0] HRDATA
);
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(HCLK));
  (* keep *) MCU_RESETN mcu_resetn(.RESETN(HRESETn));
  (* keep *) MCU_AHB_HREADY mcu_hready(.DIN(HREADY));
  (* keep *) MCU_AHB_HTRANS0 mcu_htrans0(.DIN(HTRANS[0]));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(HTRANS[1]));
  (* keep *) MCU_AHB_HSIZE0 mcu_hsize0(.DIN(HSIZE[0]));
  (* keep *) MCU_AHB_HSIZE1 mcu_hsize1(.DIN(HSIZE[1]));
  (* keep *) MCU_AHB_HSIZE2 mcu_hsize2(.DIN(HSIZE[2]));
  (* keep *) MCU_AHB_HBURST0 mcu_hburst0(.DIN(HBURST[0]));
  (* keep *) MCU_AHB_HBURST1 mcu_hburst1(.DIN(HBURST[1]));
  (* keep *) MCU_AHB_HBURST2 mcu_hburst2(.DIN(HBURST[2]));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(HWRITE));

  (* keep *) MCU_DIN mcu_haddr0(.DIN(HADDR[0]));
  (* keep *) MCU_DIN mcu_haddr1(.DIN(HADDR[1]));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(HADDR[2]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(HADDR[3]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(HADDR[4]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(HADDR[5]));
  (* keep *) MCU_DIN mcu_haddr6(.DIN(HADDR[6]));
  (* keep *) MCU_DIN mcu_haddr7(.DIN(HADDR[7]));
  (* keep *) MCU_DIN mcu_haddr8(.DIN(HADDR[8]));
  (* keep *) MCU_DIN mcu_haddr9(.DIN(HADDR[9]));
  (* keep *) MCU_DIN mcu_haddr10(.DIN(HADDR[10]));
  (* keep *) MCU_DIN mcu_haddr11(.DIN(HADDR[11]));
  (* keep *) MCU_DIN mcu_haddr12(.DIN(HADDR[12]));
  (* keep *) MCU_DIN mcu_haddr13(.DIN(HADDR[13]));
  (* keep *) MCU_DIN mcu_haddr14(.DIN(HADDR[14]));
  (* keep *) MCU_DIN mcu_haddr15(.DIN(HADDR[15]));
  (* keep *) MCU_DIN mcu_haddr16(.DIN(HADDR[16]));
  (* keep *) MCU_DIN mcu_haddr17(.DIN(HADDR[17]));
  (* keep *) MCU_DIN mcu_haddr18(.DIN(HADDR[18]));
  (* keep *) MCU_DIN mcu_haddr19(.DIN(HADDR[19]));
  (* keep *) MCU_DIN mcu_haddr20(.DIN(HADDR[20]));
  (* keep *) MCU_DIN mcu_haddr21(.DIN(HADDR[21]));
  (* keep *) MCU_DIN mcu_haddr22(.DIN(HADDR[22]));
  (* keep *) MCU_DIN mcu_haddr23(.DIN(HADDR[23]));
  (* keep *) MCU_DIN mcu_haddr24(.DIN(HADDR[24]));
  (* keep *) MCU_DIN mcu_haddr25(.DIN(HADDR[25]));
  (* keep *) MCU_DIN mcu_haddr26(.DIN(HADDR[26]));
  (* keep *) MCU_DIN mcu_haddr27(.DIN(HADDR[27]));
  (* keep *) MCU_DIN mcu_haddr28(.DIN(HADDR[28]));
  (* keep *) MCU_DIN mcu_haddr29(.DIN(HADDR[29]));
  (* keep *) MCU_DIN mcu_haddr30(.DIN(HADDR[30]));
  (* keep *) MCU_DIN mcu_haddr31(.DIN(HADDR[31]));

  (* keep *) MCU_DIN mcu_hwdata0(.DIN(HWDATA[0]));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(HWDATA[1]));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(HWDATA[2]));
  (* keep *) MCU_DIN mcu_hwdata3(.DIN(HWDATA[3]));
  (* keep *) MCU_DIN mcu_hwdata4(.DIN(HWDATA[4]));
  (* keep *) MCU_DIN mcu_hwdata5(.DIN(HWDATA[5]));
  (* keep *) MCU_DIN mcu_hwdata6(.DIN(HWDATA[6]));
  (* keep *) MCU_DIN mcu_hwdata7(.DIN(HWDATA[7]));
  (* keep *) MCU_DIN mcu_hwdata8(.DIN(HWDATA[8]));
  (* keep *) MCU_DIN mcu_hwdata9(.DIN(HWDATA[9]));
  (* keep *) MCU_DIN mcu_hwdata10(.DIN(HWDATA[10]));
  (* keep *) MCU_DIN mcu_hwdata11(.DIN(HWDATA[11]));
  (* keep *) MCU_DIN mcu_hwdata12(.DIN(HWDATA[12]));
  (* keep *) MCU_DIN mcu_hwdata13(.DIN(HWDATA[13]));
  (* keep *) MCU_DIN mcu_hwdata14(.DIN(HWDATA[14]));
  (* keep *) MCU_DIN mcu_hwdata15(.DIN(HWDATA[15]));
  (* keep *) MCU_DIN mcu_hwdata16(.DIN(HWDATA[16]));
  (* keep *) MCU_DIN mcu_hwdata17(.DIN(HWDATA[17]));
  (* keep *) MCU_DIN mcu_hwdata18(.DIN(HWDATA[18]));
  (* keep *) MCU_DIN mcu_hwdata19(.DIN(HWDATA[19]));
  (* keep *) MCU_DIN mcu_hwdata20(.DIN(HWDATA[20]));
  (* keep *) MCU_DIN mcu_hwdata21(.DIN(HWDATA[21]));
  (* keep *) MCU_DIN mcu_hwdata22(.DIN(HWDATA[22]));
  (* keep *) MCU_DIN mcu_hwdata23(.DIN(HWDATA[23]));
  (* keep *) MCU_DIN mcu_hwdata24(.DIN(HWDATA[24]));
  (* keep,
     AGRV2K_MCU_ENDPOINT_INTERFACE="HWDATA",
     AGRV2K_MCU_ENDPOINT_LANE=25,
     AGRV2K_MCU_ENDPOINT_MODE="DIRECT_FABRIC_INPUT",
     AGRV2K_MCU_ENDPOINT_VERSION=1 *)
  MCU_DIN mcu_hwdata25(.DIN(HWDATA[25]));
  (* keep *) MCU_DIN mcu_hwdata26(.DIN(HWDATA[26]));
  (* keep *) MCU_DIN mcu_hwdata27(.DIN(HWDATA[27]));
  (* keep *) MCU_DIN mcu_hwdata28(.DIN(HWDATA[28]));
  (* keep *) MCU_DIN mcu_hwdata29(.DIN(HWDATA[29]));
  (* keep *) MCU_DIN mcu_hwdata30(.DIN(HWDATA[30]));
  (* keep *) MCU_DIN mcu_hwdata31(.DIN(HWDATA[31]));

  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(HREADYOUT));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(HRESP));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(HRDATA[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(HRDATA[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(HRDATA[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(HRDATA[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(HRDATA[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(HRDATA[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(HRDATA[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(HRDATA[7]));
  (* keep *) MCU_DOUT mcu_h8(.DOUT(HRDATA[8]));
  (* keep *) MCU_DOUT mcu_h9(.DOUT(HRDATA[9]));
  (* keep *) MCU_DOUT mcu_h10(.DOUT(HRDATA[10]));
  (* keep *) MCU_DOUT mcu_h11(.DOUT(HRDATA[11]));
  (* keep *) MCU_DOUT mcu_h12(.DOUT(HRDATA[12]));
  (* keep *) MCU_DOUT mcu_h13(.DOUT(HRDATA[13]));
  (* keep *) MCU_DOUT mcu_h14(.DOUT(HRDATA[14]));
  (* keep *) MCU_DOUT mcu_h15(.DOUT(HRDATA[15]));
  (* keep *) MCU_DOUT mcu_h16(.DOUT(HRDATA[16]));
  (* keep *) MCU_DOUT mcu_h17(.DOUT(HRDATA[17]));
  (* keep *) MCU_DOUT mcu_h18(.DOUT(HRDATA[18]));
  (* keep *) MCU_DOUT mcu_h19(.DOUT(HRDATA[19]));
  (* keep *) MCU_DOUT mcu_h20(.DOUT(HRDATA[20]));
  (* keep *) MCU_DOUT mcu_h21(.DOUT(HRDATA[21]));
  (* keep *) MCU_DOUT mcu_h22(.DOUT(HRDATA[22]));
  (* keep *) MCU_DOUT mcu_h23(.DOUT(HRDATA[23]));
  (* keep *) MCU_DOUT mcu_h24(.DOUT(HRDATA[24]));
  (* keep *) MCU_DOUT mcu_h25(.DOUT(HRDATA[25]));
  (* keep *) MCU_DOUT mcu_h26(.DOUT(HRDATA[26]));
  (* keep *) MCU_DOUT mcu_h27(.DOUT(HRDATA[27]));
  (* keep *) MCU_DOUT mcu_h28(.DOUT(HRDATA[28]));
  (* keep *) MCU_DOUT mcu_h29(.DOUT(HRDATA[29]));
  (* keep *) MCU_DOUT mcu_h30(.DOUT(HRDATA[30]));
  (* keep *) MCU_DOUT mcu_h31(.DOUT(HRDATA[31]));
endmodule
