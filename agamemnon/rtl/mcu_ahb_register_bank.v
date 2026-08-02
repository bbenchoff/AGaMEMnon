// Reusable AHB-Lite register bank for the AG32 External AHB window.
//
// Address/control are latched in the address phase. HWDATA is consumed only
// in the completing data phase. Subword write values are accepted in the low
// 8/16 bits and shifted according to HADDR, matching the software/Python model.
module agamemnon_ahb_register_bank #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter [31:0] ID_VALUE = 32'h4147_414d,
  parameter integer WAIT_STATES = 0
) (
  input  wire        HCLK,
  input  wire        HRESETn,
  input  wire        HSEL,
  input  wire [31:0] HADDR,
  input  wire [1:0]  HTRANS,
  input  wire        HWRITE,
  input  wire [2:0]  HSIZE,
  input  wire [2:0]  HBURST,
  input  wire [31:0] HWDATA,
  input  wire        HREADY,
  output reg  [31:0] HRDATA,
  output wire        HREADYOUT,
  output wire        HRESP,
  input  wire [31:0] STATUS_SET,
  output reg  [31:0] SCRATCH,
  output reg  [31:0] COUNTER,
  output reg  [31:0] STATUS
);
  localparam [3:0] REG_ID      = 4'h0;
  localparam [3:0] REG_SCRATCH = 4'h4;
  localparam [3:0] REG_COUNTER = 4'h8;
  localparam [3:0] REG_STATUS  = 4'hc;

  reg active;
  reg [31:0] transfer_addr;
  reg transfer_write;
  reg [2:0] transfer_size;
  integer wait_count;

  wire [31:0] offset = transfer_addr - BASE_ADDR;
  wire [3:0] register_offset = {offset[3:2], 2'b00};
  wire in_range = transfer_addr >= BASE_ADDR && offset < 32'd16;
  wire valid_size = transfer_size <= 3'd2;
  wire aligned = (transfer_size == 3'd0) ||
                 (transfer_size == 3'd1 && !transfer_addr[0]) ||
                 (transfer_size == 3'd2 && transfer_addr[1:0] == 2'b00);
  wire known_register = register_offset == REG_ID || register_offset == REG_SCRATCH ||
                        register_offset == REG_COUNTER || register_offset == REG_STATUS;
  wire writable_register = register_offset == REG_SCRATCH ||
                           register_offset == REG_STATUS;
  wire valid = in_range && valid_size && aligned && known_register &&
               (!transfer_write || writable_register);
  wire complete = active && wait_count == 0;

  reg [31:0] write_mask;
  reg [31:0] write_value;
  always @* begin
    case (transfer_size)
      3'd0: begin
        write_mask = 32'h0000_00ff << (8 * offset[1:0]);
        write_value = {24'b0, HWDATA[7:0]} << (8 * offset[1:0]);
      end
      3'd1: begin
        write_mask = 32'h0000_ffff << (16 * offset[1]);
        write_value = {16'b0, HWDATA[15:0]} << (16 * offset[1]);
      end
      default: begin
        write_mask = 32'hffff_ffff;
        write_value = HWDATA;
      end
    endcase
  end

  assign HREADYOUT = !active || wait_count == 0;
  assign HRESP = complete && !valid;

  always @* begin
    HRDATA = 32'b0;
    if (complete && valid && !transfer_write) begin
      case (register_offset)
        REG_ID:      HRDATA = ID_VALUE;
        REG_SCRATCH: HRDATA = SCRATCH;
        REG_COUNTER: HRDATA = COUNTER;
        REG_STATUS:  HRDATA = STATUS;
        default:     HRDATA = 32'b0;
      endcase
    end
  end

  always @(posedge HCLK or negedge HRESETn) begin
    if (!HRESETn) begin
      active <= 1'b0;
      wait_count <= 0;
      transfer_addr <= 0;
      transfer_write <= 0;
      transfer_size <= 0;
      SCRATCH <= 0;
      COUNTER <= 0;
      STATUS <= 0;
    end else begin
      COUNTER <= COUNTER + 1'b1;

      if (active && wait_count != 0)
        wait_count <= wait_count - 1;

      if (complete && HREADY) begin
        if (valid && transfer_write && register_offset == REG_SCRATCH)
          SCRATCH <= (SCRATCH & ~write_mask) | (write_value & write_mask);
        if (valid && transfer_write && register_offset == REG_STATUS)
          STATUS <= (STATUS & ~(write_value & write_mask)) | STATUS_SET;
        else
          STATUS <= STATUS | STATUS_SET;
        active <= 1'b0;
      end else begin
        STATUS <= STATUS | STATUS_SET;
      end

      if (HREADY && HREADYOUT && HSEL && HTRANS[1]) begin
        active <= 1'b1;
        transfer_addr <= HADDR;
        transfer_write <= HWRITE;
        transfer_size <= HSIZE;
        wait_count <= WAIT_STATES;
      end
    end
  end

  wire _unused_hburst = ^HBURST;
endmodule


// Hard-port wrapper. Keep this module separate from the protocol core so all
// behavior remains simulatable without AG32 primitives.
module agamemnon_mcu_ahb_register_bank #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter [31:0] ID_VALUE = 32'h4147_414d,
  parameter integer WAIT_STATES = 0
) (
  input  wire [31:0] STATUS_SET,
  output wire [31:0] SCRATCH,
  output wire [31:0] COUNTER,
  output wire [31:0] STATUS
);
  wire hclk, hresetn, hready, hwrite;
  wire [1:0] htrans;
  wire [2:0] hsize, hburst;
  wire [31:0] haddr, hwdata, hrdata;
  wire hreadyout, hresp;

  agamemnon_mcu_ahb_port port_i(
    .HCLK(hclk), .HRESETn(hresetn), .HREADY(hready), .HTRANS(htrans),
    .HSIZE(hsize), .HBURST(hburst), .HWRITE(hwrite), .HADDR(haddr),
    .HWDATA(hwdata), .HREADYOUT(hreadyout), .HRESP(hresp), .HRDATA(hrdata));

  agamemnon_ahb_register_bank #(
    .BASE_ADDR(BASE_ADDR), .ID_VALUE(ID_VALUE), .WAIT_STATES(WAIT_STATES)
  ) bank_i (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(1'b1), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .STATUS_SET(STATUS_SET),
    .SCRATCH(SCRATCH), .COUNTER(COUNTER), .STATUS(STATUS));
endmodule
