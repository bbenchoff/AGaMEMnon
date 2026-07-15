// Multi-instruction SERV qualification workload.
//
// The minimized silicon-isolation program executes dependent ADDI operations,
// then stores their result and parks in JAL. The output latches high only after
// observing the expected signature on SERV's memory bus. Broader instruction
// coverage remains in the negative evidence log until its larger route works.
`include "examples/serv_blinky/serv_rtl.v"

(* top *)
module serv_multii (
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
    wire        mem_ack = mem_stb;

    always @* begin
        case (mem_adr[3:2])
            2'd0: mem_rdt = 32'h00500093; // addi x1,x0,5
            2'd1: mem_rdt = 32'h00708113; // addi x2,x1,7       = 12
            2'd2: mem_rdt = 32'h00202023; // sw   x2,0(x0)      (12)
            default: mem_rdt = 32'h0000006f; // jal x0,0
        endcase
    end

    reg pass_latched;
    always @(posedge clock) begin
        if (reset)
            pass_latched <= 1'b0;
        else if (mem_stb && mem_ack && mem_we)
            // One LUT is enough to distinguish the expected low-nibble
            // signature; a full 32-bit equality tree needlessly doubled the
            // unqualified output cone in the first silicon isolation.
            pass_latched <= (mem_dat[3:0] == 4'hc);
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

    serv_multii_rf rf (
        .i_clk(clock), .i_waddr(rf_waddr), .i_wdata(rf_wdata),
        .i_wen(rf_wen), .i_raddr(rf_raddr), .i_ren(rf_ren),
        .o_rdata(rf_rdata)
    );
endmodule

module serv_multii_rf (
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
