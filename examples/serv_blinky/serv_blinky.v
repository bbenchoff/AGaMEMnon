// SERV blinks an LED.
//
// A SERV bit-serial RISC-V CPU repeatedly executes addi and sw instructions.
// A high bit of SERV's program-counter address drives the LED, so the visible
// blink is direct proof that the CPU keeps fetching and retiring instructions.
// Hold reset high to halt the CPU and freeze the LED.
//
// even words: addi x1, x1, 1
// odd words:  sw   x1, 0(x0)
//
// The two-word ROM is deliberately aliased over the whole address space. The
// PC therefore advances continuously and supplies the human-speed divider.
//
// The register file uses independent BRAM ports: Port A writes while Port B
// reads.  SERV overlaps write-back with operand reads, so this is required
// for general programs (a shared-address approximation corrupts collisions).
//
// Hold `reset` high, then release it to run.
`include "serv_rtl.v"

(* top *)
module serv_blinky #(
    parameter integer BLINK_ADDRESS_BIT = 16
) (
    input  wire       clock,
    input  wire       reset,
    output wire       led
);
    wire [31:0] mem_adr;
    wire [31:0] mem_dat;
    wire [3:0]  mem_sel;
    wire        mem_we;
    wire        mem_stb;
    wire [31:0] mem_rdt = mem_adr[2]
        ? 32'h00102023                    // sw   x1,0(x0)
        : 32'h00108093;                   // addi x1,x1,1
    wire        mem_ack = mem_stb;

    wire [8:0] rf_waddr;
    wire [1:0] rf_wdata;
    wire       rf_wen;
    wire [8:0] rf_raddr;
    wire [1:0] rf_rdata;
    wire       rf_ren;

    reg pc_led;
    always @(posedge clock) begin
        if (reset)
            pc_led <= 1'b0;
        else if (mem_stb && !mem_we)
            pc_led <= mem_adr[BLINK_ADDRESS_BIT];
    end
    assign led = pc_led;

    servile #(
        .width(1),
        // MINI is SERV's supported minimal architectural reset. FULL is not a
        // documented SERV mode and synthesizes reset muxes onto almost every
        // state bit without adding architectural guarantees.
        .reset_strategy("MINI"),
        .with_c(0),
        .with_csr(0)
    ) cpu (
        .i_clk(clock), .i_rst(reset), .i_timer_irq(1'b0),
        .o_wb_mem_adr(mem_adr), .o_wb_mem_dat(mem_dat),
        .o_wb_mem_sel(mem_sel), .o_wb_mem_we(mem_we),
        .o_wb_mem_stb(mem_stb), .i_wb_mem_rdt(mem_rdt),
        .i_wb_mem_ack(mem_ack),
        .o_wb_ext_adr(), .o_wb_ext_dat(), .o_wb_ext_sel(),
        .o_wb_ext_we(), .o_wb_ext_stb(),
        .i_wb_ext_rdt(32'b0), .i_wb_ext_ack(1'b0),
        .o_rf_waddr(rf_waddr), .o_rf_wdata(rf_wdata),
        .o_rf_wen(rf_wen), .o_rf_raddr(rf_raddr),
        .i_rf_rdata(rf_rdata), .o_rf_ren(rf_ren),
        .o_rf_ready_debug(), .o_cnt_done_debug(),
        .o_ctrl_pc_en_debug()
    );

    // True dual-port register file: simultaneous write-back and operand read.
    serv_rf_ram_dp rf (
        .i_clk(clock), .i_waddr(rf_waddr), .i_wdata(rf_wdata),
        .i_wen(rf_wen), .i_raddr(rf_raddr), .i_ren(rf_ren),
        .o_rdata(rf_rdata)
    );

endmodule

module serv_rf_ram_dp (
    input wire i_clk,
    input wire [8:0] i_waddr,
    input wire [1:0] i_wdata,
    input wire i_wen,
    input wire [8:0] i_raddr,
    input wire i_ren,
    output wire [1:0] o_rdata
);
    reg [1:0] memory [0:511];
    reg [1:0] rdata;
    reg       regzero;
    always @(posedge i_clk) begin
        if (i_wen)
            memory[i_waddr] <= i_wdata;
        if (i_ren)
            rdata <= memory[i_raddr];
        regzero <= !(|i_raddr[8:4]);
    end
    assign o_rdata = rdata & {2{~regzero}};
endmodule
