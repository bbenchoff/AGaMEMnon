// Reusable AHB-Lite register bank for the AG32 External AHB window.
//
// Address/control are latched in the address phase. HWDATA is consumed only
// in the completing data phase. Subword write values are accepted in the low
// 8/16 bits and shifted according to HADDR, matching the software/Python model.
module agamemnon_ahb_register_bank #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter [31:0] ID_VALUE = 32'h4147_414d,
  parameter integer WAIT_STATES = 0,
  // 0 completes byte-sized transfers with HRESP=1 instead of accepting them.
  // The AG32 binding disables byte access because HADDR[0] has no recovered
  // LUT-input corridor in the release routing graph yet.
  parameter ALLOW_BYTE = 1
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
  localparam [3:0] WAIT_INIT   = WAIT_STATES;
  localparam [3:0] REG_ID      = 4'h0;
  localparam [3:0] REG_SCRATCH = 4'h4;
  localparam [3:0] REG_COUNTER = 4'h8;
  localparam [3:0] REG_STATUS  = 4'hc;

  // BASE_ADDR must be 16-byte aligned: the window decode is an equality on
  // HADDR[31:4], evaluated once in the address phase. Only the in-range bit
  // and the 4-bit offset are latched; a full latched address plus a 32-bit
  // subtract/compare synthesizes to hundreds of extra LUT4s on this fabric.
  reg active;
  reg transfer_in_range;
  reg [3:0] transfer_offset;
  reg transfer_write;
  reg [2:0] transfer_size;
  reg [3:0] wait_count; // bounds WAIT_STATES to 0..15

  wire [3:0] offset = transfer_offset;
  wire [3:0] register_offset = {offset[3:2], 2'b00};
  wire in_range = transfer_in_range;
  wire valid_size = transfer_size <= 3'd2 && (ALLOW_BYTE != 0 || transfer_size != 3'd0);
  wire aligned = (transfer_size == 3'd0) ||
                 (transfer_size == 3'd1 && !offset[0]) ||
                 (transfer_size == 3'd2 && offset[1:0] == 2'b00);
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

  // Synchronous reset: the AGRV2K slice model has no async set/reset
  // flip-flop, so an async HRESETn cannot be legalized by the open flow.
  always @(posedge HCLK) begin
    if (!HRESETn) begin
      active <= 1'b0;
      wait_count <= 0;
      transfer_in_range <= 0;
      transfer_offset <= 0;
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
        transfer_in_range <= HADDR[31:4] == BASE_ADDR[31:4];
        transfer_offset <= HADDR[3:0];
        transfer_write <= HWRITE;
        transfer_size <= HSIZE;
        wait_count <= WAIT_INIT;
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
  parameter integer WAIT_STATES = 0,
  // Writable-register capture width.  The release routing graph is a union
  // of per-oracle vendor corridors; no oracle proves a simultaneous 32-lane
  // HWDATA logic capture, and the joint allocator cannot conjure corridors
  // that were never recovered.  HWDATA[7:0] are corpus-rich lanes that route
  // simultaneously today; lanes 10-17/30-31 exist only as single narrow
  // corridors and contend at the boundary tiles.  Scratch/status upper bits
  // read as zero and ignore writes.  HRDATA remains full-width.
  parameter integer DATA_BITS = 8
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

  // Only these HADDR bits have recovered LUT-input corridors in the release
  // routing graph; the identity-readback oracles prove the other bits reach
  // the HRDATA exit funnel but not fabric logic.  Unseen bits are replaced by
  // their BASE_ADDR values, so addresses differing only in an unseen bit
  // alias into the window.  HADDR[0] is unseen; byte access is disabled via
  // ALLOW_BYTE=0 and completes with HRESP=1.
  // Window-decode bits are restricted to lanes with corpus-rich logic-input
  // corridors: {5:1}, which give the near window including the 0x60000010
  // error address via bit 4.  The MCU bus matrix already routes only the
  // fabric window to this slave, so the 0x6 prefix is not re-verified here;
  // bits {31,30} and the wider LUT-reachable set {10-15,21,24,25} exist only
  // as single narrow vendor corridors whose simultaneous logic use is not
  // yet allocatable.  Addresses differing only in an unseen bit alias into
  // the window (documented).
  localparam [31:0] HADDR_SEEN_MASK = 32'h0000_003E; // bits 5,4,3,2,1
  wire [31:0] haddr_seen = (haddr & HADDR_SEEN_MASK) | (BASE_ADDR & ~HADDR_SEEN_MASK);
  localparam [31:0] DATA_MASK = (DATA_BITS >= 32) ? 32'hFFFF_FFFF : ((32'h1 << DATA_BITS) - 1);
  wire [31:0] hwdata_seen = hwdata & DATA_MASK;

  agamemnon_mcu_ahb_port port_i(
    .HCLK(hclk), .HRESETn(hresetn), .HREADY(hready), .HTRANS(htrans),
    .HSIZE(hsize), .HBURST(hburst), .HWRITE(hwrite), .HADDR(haddr),
    .HWDATA(hwdata), .HREADYOUT(hreadyout), .HRESP(hresp), .HRDATA(hrdata));

  agamemnon_ahb_register_bank #(
    .BASE_ADDR(BASE_ADDR), .ID_VALUE(ID_VALUE), .WAIT_STATES(WAIT_STATES),
    .ALLOW_BYTE(0)
  ) bank_i (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(1'b1), .HADDR(haddr_seen),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata_seen), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .STATUS_SET(STATUS_SET),
    .SCRATCH(SCRATCH), .COUNTER(COUNTER), .STATUS(STATUS));
endmodule
