module loop_macro (
  output             dout_in,
  input              din_out_data,
  input              din_out_en,
  input              sys_clock,
  input              bus_clock,
  input              resetn,
  input              stop,
  input       [1:0]  mem_ahb_htrans,
  input              mem_ahb_hready,
  input              mem_ahb_hwrite,
  input       [31:0] mem_ahb_haddr,
  input       [2:0]  mem_ahb_hsize,
  input       [2:0]  mem_ahb_hburst,
  input       [31:0] mem_ahb_hwdata,
  output             mem_ahb_hreadyout,
  output             mem_ahb_hresp,
  output      [31:0] mem_ahb_hrdata,
  output             slave_ahb_hsel,
  output             slave_ahb_hready,
  input              slave_ahb_hreadyout,
  output      [1:0]  slave_ahb_htrans,
  output      [2:0]  slave_ahb_hsize,
  output      [2:0]  slave_ahb_hburst,
  output             slave_ahb_hwrite,
  output      [31:0] slave_ahb_haddr,
  output      [31:0] slave_ahb_hwdata,
  input              slave_ahb_hresp,
  input       [31:0] slave_ahb_hrdata,
  output      [3:0]  ext_dma_DMACBREQ,
  output      [3:0]  ext_dma_DMACLBREQ,
  output      [3:0]  ext_dma_DMACSREQ,
  output      [3:0]  ext_dma_DMACLSREQ,
  input       [3:0]  ext_dma_DMACCLR,
  input       [3:0]  ext_dma_DMACTC,
  output      [3:0]  local_int
);
assign dout_in = ~din_out_data;          // fabric inverter: MCU GPIO4.1 -> fabric -> MCU GPIO4.2
assign mem_ahb_hreadyout = 1'b1;
assign mem_ahb_hresp     = 1'b0;
assign mem_ahb_hrdata    = 32'h0;
assign slave_ahb_hsel    = 1'b0;
assign slave_ahb_hready  = 1'b1;
assign slave_ahb_htrans  = 2'h0;
assign slave_ahb_hsize   = 3'h0;
assign slave_ahb_hburst  = 3'h0;
assign slave_ahb_hwrite  = 1'b0;
assign slave_ahb_haddr   = 32'h0;
assign slave_ahb_hwdata  = 32'h0;
assign ext_dma_DMACBREQ  = 4'h0;
assign ext_dma_DMACLBREQ = 4'h0;
assign ext_dma_DMACSREQ  = 4'h0;
assign ext_dma_DMACLSREQ = 4'h0;
assign local_int         = 4'h0;
endmodule
