// Vendor-independent AHB-Lite memory slave for protocol simulation.
//
// Address/control are latched in one phase; HWDATA is consumed in the data
// phase. Byte, halfword, and word accesses are supported. Unsupported sizes,
// misalignment, and out-of-range addresses complete with HRESP=1.
module agamemnon_ahb_slave_model #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter integer WORDS = 16,
  parameter integer WAIT_STATES = 0
) (
  input wire HCLK,
  input wire HRESETn,
  input wire HSEL,
  input wire [31:0] HADDR,
  input wire [1:0] HTRANS,
  input wire HWRITE,
  input wire [2:0] HSIZE,
  input wire [2:0] HBURST,
  input wire [31:0] HWDATA,
  input wire HREADY,
  output reg [31:0] HRDATA,
  output wire HREADYOUT,
  output wire HRESP
);
  reg [31:0] memory [0:WORDS-1];
  reg active;
  reg [31:0] transfer_addr;
  reg transfer_write;
  reg [2:0] transfer_size;
  integer wait_count;
  integer i;
  wire [31:0] offset = transfer_addr - BASE_ADDR;
  wire valid_size = transfer_size <= 3'd2;
  wire aligned = (transfer_size == 3'd0) ||
                 (transfer_size == 3'd1 && transfer_addr[0] == 1'b0) ||
                 (transfer_size == 3'd2 && transfer_addr[1:0] == 2'b00);
  wire in_range = transfer_addr >= BASE_ADDR && offset < WORDS * 4;
  wire valid = valid_size && aligned && in_range;
  wire complete = active && wait_count == 0;
  assign HREADYOUT = !active || wait_count == 0;
  assign HRESP = complete && !valid;

  always @* begin
    HRDATA = 32'b0;
    if (complete && valid && !transfer_write)
      HRDATA = memory[offset[31:2]];
  end

  always @(posedge HCLK or negedge HRESETn) begin
    if (!HRESETn) begin
      active <= 1'b0;
      wait_count <= 0;
      transfer_addr <= 0;
      transfer_write <= 0;
      transfer_size <= 0;
      for (i = 0; i < WORDS; i = i + 1)
        memory[i] <= 0;
    end else begin
      if (active && wait_count != 0 && HREADY)
        wait_count <= wait_count - 1;
      if (complete && HREADY) begin
        if (valid && transfer_write) begin
          case (transfer_size)
            3'd0: memory[offset[31:2]][8*offset[1:0] +: 8] <= HWDATA[7:0];
            3'd1: memory[offset[31:2]][16*offset[1] +: 16] <= HWDATA[15:0];
            3'd2: memory[offset[31:2]] <= HWDATA;
          endcase
        end
        active <= 1'b0;
      end
      // HREADY is the global pipeline advance. It is low while this slave
      // inserts a wait state, so a new address cannot overwrite the held one.
      if (HREADY && HREADYOUT && HSEL && HTRANS[1]) begin
        active <= 1'b1;
        transfer_addr <= HADDR;
        transfer_write <= HWRITE;
        transfer_size <= HSIZE;
        wait_count <= WAIT_STATES;
      end
    end
  end

  // HBURST is accepted and held by the bus master; individual SEQ/NONSEQ
  // beats use the same transfer rules. Keep it named for interface parity.
  wire _unused_hburst = ^HBURST;
endmodule
