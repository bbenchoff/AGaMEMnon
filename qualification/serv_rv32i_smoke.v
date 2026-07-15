// Self-checking multi-operation SERV qualification workload.
//
// A dependent ADDI/SLLI/XORI chain produces signature 19.  BNE must fall
// through, BEQ must take the success edge, SW commits the signature, and a
// backward JAL repeats the success tail. The normal build latches `pass` on the
// exact store. qualification/serv_rv32i_heartbeat.v compiles this same source
// with SERV_RV32I_HEARTBEAT and toggles the output on each visit to the success
// block, proving the backward JAL keeps the loop running. The failure edge
// stores zero forever. This is a focused RV32I instruction-signature workload,
// not the complete riscv-arch-test suite.
`include "examples/serv_blinky/serv_rtl.v"

(* top *)
module serv_rv32i_smoke (
    input  wire clock,
    input  wire reset,
    output wire pass
);
    wire [31:0] mem_adr;
    wire [31:0] mem_dat;
    wire [3:0]  mem_sel;
    wire        mem_we;
    wire        mem_stb;
    reg  [31:0] mem_rdt;

    always @* begin
        case (mem_adr[5:2])
            4'd0:  mem_rdt = 32'h00500093; // addi x1,x0,5
            4'd1:  mem_rdt = 32'h00209113; // slli x2,x1,2
            4'd2:  mem_rdt = 32'h00714193; // xori x3,x2,7
            4'd3:  mem_rdt = 32'h01300213; // addi x4,x0,19
            4'd4:  mem_rdt = 32'h00419463; // bne  x3,x4,fail
            4'd5:  mem_rdt = 32'h00418663; // beq  x3,x4,okay
            4'd6:  mem_rdt = 32'h00002023; // fail: sw x0,0(x0)
            4'd7:  mem_rdt = 32'hffdff06f; // jal  x0,fail
            4'd8:  mem_rdt = 32'h00302023; // okay: sw x3,0(x0)
            4'd9:  mem_rdt = 32'hffdff06f; // jal  x0,okay
            default: mem_rdt = 32'h0000006f;
        endcase
    end
    wire mem_ack = mem_stb;

    reg pass_latched;
    always @(posedge clock) begin
        if (reset)
            pass_latched <= 1'b0;
`ifdef SERV_RV32I_HEARTBEAT
        else if (mem_stb && !mem_we && mem_adr[5:0] == 6'h20)
            pass_latched <= ~pass_latched;
`else
        else if (mem_stb && mem_we && (&mem_sel) && mem_dat == 32'd19)
            pass_latched <= 1'b1;
`endif
    end
    assign pass = pass_latched;

    wire [8:0] rf_waddr;
    wire [1:0] rf_wdata;
    wire       rf_wen;
    wire [8:0] rf_raddr;
    wire [1:0] rf_rdata;
    wire       rf_ren;

    servile #(
        .width(1), .reset_strategy("MINI"), .with_c(0), .with_csr(0)
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

    serv_rv32i_smoke_rf rf (
        .i_clk(clock), .i_waddr(rf_waddr), .i_wdata(rf_wdata),
        .i_wen(rf_wen), .i_raddr(rf_raddr), .i_ren(rf_ren),
        .o_rdata(rf_rdata)
    );
endmodule

module serv_rv32i_smoke_rf (
    input wire i_clk,
    input wire [8:0] i_waddr,
    input wire [1:0] i_wdata,
    input wire i_wen,
    input wire [8:0] i_raddr,
    input wire i_ren,
    output wire [1:0] o_rdata
);
    integer i;
    reg [1:0] memory [0:511];
    reg [1:0] rdata;
    reg       regzero;
    initial begin
        for (i = 0; i < 512; i = i + 1)
            memory[i] = 2'b00;
    end
    always @(posedge i_clk) begin
        if (i_wen)
            memory[i_waddr] <= i_wdata;
        if (i_ren)
            rdata <= memory[i_raddr];
        regzero <= !(|i_raddr[8:4]);
    end
    assign o_rdata = rdata & {2{~regzero}};
endmodule
