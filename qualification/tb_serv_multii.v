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
    reg seen_pass = 0;
    always @(posedge clock)
        if (!reset) begin
            if (pass)
                seen_pass = 1;
            if (dut.mem_stb && dut.mem_ack) begin
                if (dut.mem_we) begin
                    stores = stores + 1;
                    stored = dut.mem_dat;
                end else begin
                    fetches = fetches + 1;
                end
            end
        end

    initial begin
        repeat (16) @(posedge clock);
        reset <= 0;
        repeat (120_000) @(posedge clock);
        if (seen_pass && stored > 32'd5 && stores >= 6 && fetches >= 12)
            $display("PASS: dependent SERV store reached 5; fetches=%0d stores=%0d",
                     fetches, stores);
        else
            $display("FAIL: pass=%b signature=%0d fetches=%0d stores=%0d",
                     pass, stored, fetches, stores);
        $finish;
    end
endmodule
