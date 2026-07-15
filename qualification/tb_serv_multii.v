`timescale 1ns/1ps
module tb_serv_multii;
    reg clock = 0;
    reg reset = 1;
    wire pass;
    serv_multii dut (.clock(clock), .reset(reset), .pass(pass));
    always #20 clock = ~clock;

    integer fetches = 0;
    integer stores = 0;
    reg [31:0] stored = 0;
    always @(posedge clock)
        if (!reset && dut.mem_stb && dut.mem_ack) begin
            if (dut.mem_we) begin
                stores = stores + 1;
                stored = dut.mem_dat;
            end else begin
                fetches = fetches + 1;
            end
        end

    initial begin
        repeat (16) @(posedge clock);
        reset <= 0;
        repeat (120_000) @(posedge clock);
        if (pass && stored == 32'd12 && stores == 1 && fetches >= 4)
            $display("PASS: multi-instruction SERV signature=%0d fetches=%0d stores=%0d",
                     stored, fetches, stores);
        else
            $display("FAIL: pass=%b signature=%0d fetches=%0d stores=%0d",
                     pass, stored, fetches, stores);
        $finish;
    end
endmodule
